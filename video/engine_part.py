"""
Rendering engine + worked example, for one Black Box Facts video.

HOW TO USE THIS TEMPLATE:
1. Run align_template.py first (see that file) to produce words.json for
   YOUR script. This file reads that words.json.
2. Copy this file into the same working directory as render.py.
3. In the CONFIG section: set AUDIO_END to your audio's real duration
   (`ffprobe -show_entries format=duration audio/vo.mp3`), and replace the
   accent color(s) with the ONE color this video's topic needs (see
   references/design-system.md for the color rule).
4. Everything from "CORE ENGINE" through the T()/boundary() helpers is
   generic — leave it alone unless something genuinely doesn't fit.
5. Everything from "EXAMPLE SCENES" down is the radioactive-banana video,
   kept as a complete, runnable reference. Delete it and write scene
   functions for YOUR script instead, following the same pattern: one
   function per SC entry, reading timing from T()/boundary(), drawing with
   the Frame/ktext/stext/arrow/etc. primitives.
6. Sanity-check with `python3 render.py bench` (prints sec/frame) and
   `python3 render.py sheet check.png <t1> <t2> ...` (contact sheet of
   specific timestamps) before committing to a full render.
7. Full render: use `part` mode in 2-3 foreground calls, not `full` in the
   background — see SKILL.md stage 4 for why, and the exact concat/mux
   commands.

CLI modes:
  frames <t1> <t2> ...        render specific timestamps to preview/*.png
  sheet <out.png> <t1> ...    contact sheet of specific timestamps
  part <a> <b> <out.mp4>      render frames [a, b) to a silent clip (foreground, blocks until done)
  bench                       print seconds/frame
  full                        render the whole video + mux audio in one shot (fine for quick local tests; avoid backgrounding this for the real deliverable)
"""
import os, sys, json, math, re, subprocess, time
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ============================================================ CONFIG =====
W, H, FPS, SS = 1080, 1920, 30, 2   # SS = supersampling factor for shapes
CX = W // 2

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
DIM = (150, 150, 150)
NOTE = (112, 112, 112)
FAINT = (70, 70, 70)
LINT = (110, 172, 255)      # accent: lint / what lives in your navel

AUDIO_END = 65.985306        # <-- replace with your audio's real duration (seconds)
OUTRO_HOLD = 1.5             # seconds of hold+fade after the last word
TOTAL = AUDIO_END + OUTRO_HOLD

# ============================================================ CORE ENGINE (keep as-is) =====

FD = "/usr/share/fonts/opentype/inter"
_fc = {}
def _font(name, size):
    k = (name, size)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(f"{FD}/{name}", size)
    return _fc[k]
XB = lambda s: _font("InterDisplay-ExtraBold.otf", s)
BD = lambda s: _font("InterDisplay-Bold.otf", s)
SB = lambda s: _font("Inter-SemiBold.otf", s)
MD = lambda s: _font("Inter-Medium.otf", s)
CAP = 0.727                  # cap-height fraction, for vertical centering in stext()
TNUM = ["tnum"]              # tabular-figure font feature; pass to any animated number

D = json.load(open("words.json"))
CHW = {}
for w in D["words"]:
    CHW.setdefault(w["chunk"], []).append(w)

def _n(s):
    return re.sub(r"[^a-z0-9'\-]", "", s.lower())

def T(c, key, occ=1, end=False):
    """Start (or end, if end=True) time of the `occ`-th occurrence of `key`
    (normalized word text) in chunk c. This is how every animation beat gets
    tied to a specific spoken word instead of a guessed timestamp."""
    k = 0
    for w in CHW[c]:
        if _n(w["text"]) == key:
            k += 1
            if k == occ:
                return w["e"] if end else w["s"]
    raise KeyError((c, key, occ))

def boundary(c):
    """Scene-cut time between chunk c-1 and c: the midpoint of the silence
    between them, from the actual aligned audio."""
    if c == 0:
        return 0.0
    return (CHW[c - 1][-1]["e"] + CHW[c][0]["s"]) / 2

# ---- easing ----
def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x
def ein(t, t0, d):
    x = clamp((t - t0) / d) if d > 0 else float(t >= t0)
    return 1 - (1 - x) ** 3
def eio(t, t0, d):
    x = clamp((t - t0) / d) if d > 0 else float(t >= t0)
    return 4 * x ** 3 if x < 0.5 else 1 - ((-2 * x + 2) ** 3) / 2
def eback(t, t0, d):
    x = clamp((t - t0) / d)
    c1 = 1.70158
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2
def fout(t, t0, d):
    return 1 - ein(t, t0, d)
def lerp(a, b, p):
    return a + (b - a) * p
def pc(col, a):
    a = clamp(a)
    return (int(col[0] * a + .5), int(col[1] * a + .5), int(col[2] * a + .5))
def hold_pulse(t, period=1.6, lo=0.93, hi=1.07):
    ph = (t % period) / period
    return lo + (hi - lo) * (0.5 - 0.5 * math.cos(ph * 2 * math.pi))

# ---- frame: shapes at 2x (premultiplied on black -> alpha==brightness for
# additive-light effects), text at 1x after downsampling ----
class Frame:
    def __init__(self):
        self.hi = Image.new("RGB", (W * SS, H * SS), BLACK)
        self.d = ImageDraw.Draw(self.hi)
        self.post = []

    def circle(self, cx, cy, r, fill=None, outline=None, width=4, alpha=1.0):
        if alpha <= 0.004 or r <= 0.5:
            return
        bb = [(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS]
        self.d.ellipse(bb, fill=pc(fill, alpha) if fill else None,
                       outline=pc(outline, alpha) if outline else None,
                       width=max(1, int(round(width * SS))))

    def line(self, x1, y1, x2, y2, color, width=4, alpha=1.0, cap=True):
        if alpha <= 0.004:
            return
        col = pc(color, alpha)
        w = max(1, int(round(width * SS)))
        self.d.line([(x1 * SS, y1 * SS), (x2 * SS, y2 * SS)], fill=col, width=w)
        if cap and width >= 2.5:
            r = w / 2
            for (x, y) in ((x1, y1), (x2, y2)):
                self.d.ellipse([x * SS - r, y * SS - r, x * SS + r, y * SS + r], fill=col)

    def poly(self, pts, fill, alpha=1.0):
        if alpha <= 0.004:
            return
        self.d.polygon([(x * SS, y * SS) for x, y in pts], fill=pc(fill, alpha))

    def pieslice(self, cx, cy, r, a0, a1, fill, alpha=1.0):
        if alpha <= 0.004 or a1 - a0 <= 0.05:
            return
        bb = [(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS]
        self.d.pieslice(bb, a0 - 90, a1 - 90, fill=pc(fill, alpha))

    def arc(self, cx, cy, r, a0, a1, color, width=4, alpha=1.0):
        if alpha <= 0.004 or a1 - a0 <= 0.05:
            return
        bb = [(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS]
        self.d.arc(bb, a0 - 90, a1 - 90, fill=pc(color, alpha), width=max(1, int(round(width * SS))))

    def rect(self, x0, y0, x1, y1, fill, alpha=1.0, radius=0):
        if alpha <= 0.004:
            return
        x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
        rad = min(radius, (x1 - x0) / 2, (y1 - y0) / 2)
        if rad >= 1:
            self.d.rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], radius=rad * SS, fill=pc(fill, alpha))
        else:
            self.d.rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], fill=pc(fill, alpha))

    def rrect_outline(self, x0, y0, x1, y1, rad, color, width=3, alpha=1.0):
        if alpha <= 0.004:
            return
        self.d.rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], radius=rad * SS,
                                 outline=pc(color, alpha), width=max(1, int(round(width * SS))))

    def text(self, fn):
        """Queue a function(draw) to run once, on the 1x downsampled image."""
        self.post.append(fn)

    def render(self, fade=1.0):
        lo = self.hi.reduce(SS)
        d = ImageDraw.Draw(lo)
        for fn in self.post:
            fn(d)
        if fade < 0.999:
            f = clamp(fade)
            lo = lo.point(lambda p: int(p * f))
        return lo

# ---- text layout ----
_LC = {}
def layout(text, font, maxw):
    """Greedy word-wrap, then narrow the width until the line count would
    increase -- avoids a lonely single word stranded on its own line."""
    key = (text, id(font), maxw)
    if key in _LC:
        return _LC[key]
    words = text.split()
    def greedy(mw):
        lines, cur = [], []
        for w in words:
            if cur and font.getlength(" ".join(cur + [w])) > mw:
                lines.append(cur); cur = [w]
            else:
                cur.append(w)
        if cur:
            lines.append(cur)
        return lines
    res = greedy(maxw)
    if len(res) > 1:
        lo, hi = 0.0, float(maxw)
        for _ in range(18):
            mid = (lo + hi) / 2
            if len(greedy(mid)) <= len(res):
                hi = mid
            else:
                lo = mid
        res = greedy(hi)
    _LC[key] = res
    return res

def ktext(fr, text, font, color, x, cy, t, t0=None, alpha=1.0, maxw=900, lh=None,
          align="c", stagger=0.055, dur=0.42, rise=22, times=None):
    """Kinetic text: words rise + fade in one after another. Pass `times`
    (a list of per-word start times from T()) instead of t0/stagger when
    words should land on specific spoken words rather than an even cadence."""
    if alpha <= 0.004:
        return
    lines = layout(text, font, maxw)
    lh = lh or round(font.size * 1.2)
    base0 = cy - (len(lines) - 1) * lh / 2 + font.size * CAP / 2
    sp = font.getlength(" ")
    items, k = [], 0
    for li, line in enumerate(lines):
        lw = font.getlength(" ".join(line))
        xx = x - lw / 2 if align == "c" else (x if align == "l" else x - lw)
        by = base0 + li * lh
        for w in line:
            if times is not None:
                p = ein(t, times[k] - 0.06, dur)
            elif t0 is None:
                p = 1.0
            else:
                p = ein(t, t0 + k * stagger, dur)
            a = p * alpha
            if a > 0.004:
                items.append((xx, by + (1 - p) * rise, w, pc(color, a)))
            xx += font.getlength(w) + sp
            k += 1
    def _d(d):
        for (px, py, w, c) in items:
            d.text((px, py), w, font=font, fill=c, anchor="ls")
    fr.text(_d)

def stext(fr, s, font, color, x, cy, alpha=1.0, align="c", dy=0.0, tnum=False):
    """Static (non-kinetic) single/multi-line-free text, vertically centered
    on cy using the CAP constant. Use tnum=True for any number that animates."""
    if alpha <= 0.004:
        return
    base = cy + font.size * CAP / 2 + dy
    anchor = {"c": "ms", "l": "ls", "r": "rs"}[align]
    col = pc(color, alpha)
    feats = TNUM if tnum else None
    fr.text(lambda d: d.text((x, base), s, font=font, fill=col, anchor=anchor, features=feats))

def tlen(s, font, tnum=False):
    return font.getlength(s, features=TNUM if tnum else None)

# ---- generic glyphs ----
def arrow(fr, x1, y1, x2, y2, color, width=7, head=24, alpha=1.0):
    L = math.hypot(x2 - x1, y2 - y1)
    if L < 1 or alpha <= 0.004:
        return
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    hl = min(head, L * 0.65)
    bx, by = x2 - ux * hl, y2 - uy * hl
    if L - hl > 1:
        fr.line(x1, y1, bx + ux, by + uy, color, width, alpha, cap=True)
    px, py = -uy, ux
    hw = hl * 0.62
    fr.poly([(x2, y2), (bx + px * hw, by + py * hw), (bx - px * hw, by - py * hw)], color, alpha)

def dashed_line(fr, x1, y1, x2, y2, color, width=3, alpha=1.0, dash=14, gap=10):
    L = math.hypot(x2 - x1, y2 - y1)
    if L < 1 or alpha <= 0.004:
        return
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    s = 0.0
    while s < L:
        e = min(s + dash, L)
        fr.line(x1 + ux * s, y1 + uy * s, x1 + ux * e, y1 + uy * e, color, width, alpha, cap=False)
        s += dash + gap

def glow_dot(fr, cx, cy, r, color, alpha=1.0, glow=0.55, glow_r=24, scale=1.0):
    """Soft-glow circle: a small local RGBA canvas (shape + blurred halo),
    composited onto the frame's high-res canvas with Image.paste(rgb, box,
    rgba_mask) -- passing an RGBA image as the mask argument makes paste()
    alpha-blend correctly (verified: this is NOT the same as drawing with
    ImageDraw.Draw(im, "RGBA"), which does not blend -- see
    references/design-system.md)."""
    alpha = clamp(alpha)
    if alpha <= 0.004:
        return
    r = r * scale
    pad = int(r * 3.2) + glow_r
    size = int(pad * 2 * SS)
    local = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ld = ImageDraw.Draw(local)
    rs = r * SS
    ga = int(255 * alpha * glow)
    ld.ellipse([pad * SS - rs * 1.7, pad * SS - rs * 1.7, pad * SS + rs * 1.7, pad * SS + rs * 1.7], fill=color + (ga,))
    local = local.filter(ImageFilter.GaussianBlur(glow_r * SS / 2))
    ld2 = ImageDraw.Draw(local)
    ld2.ellipse([pad * SS - rs, pad * SS - rs, pad * SS + rs, pad * SS + rs], fill=color + (int(255 * alpha),))
    fr.hi.paste(local.convert("RGB"), (int((cx - pad) * SS), int((cy - pad) * SS)), local)

def pulse_rings(fr, cx, cy, t, t0, color, n=3, period=1.1, r0=40, r1=210, width=5):
    """Expanding, fading concentric rings -- a 'something is emitting/pulsing
    here' cue. Reused for radiation, GPS pings, anything periodic."""
    if t < t0:
        return
    for k in range(n):
        ph = ((t - t0) / period - k / n) % 1.0
        r = lerp(r0, r1, ph)
        a = (1 - ph) * 0.55
        fr.circle(cx, cy, r, outline=color, width=width, alpha=a)

