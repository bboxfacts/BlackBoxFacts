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
AMBER = (242, 166, 64)

AUDIO_END = 71.131429
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

# ============================================================ SCENES: grey hair =====
import random

def ell(fr, cx, cy, rx, ry, fill=None, outline=None, width=4, alpha=1.0):
    if alpha <= 0.004:
        return
    fr.d.ellipse([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS],
                 fill=pc(fill, alpha) if fill else None,
                 outline=pc(outline, alpha) if outline else None, width=max(1, int(round(width * SS))))

def strand(fr, x, yb, yt, w, segs=(), alpha=1.0, ow=4, ocol=WHITE):
    """Vertical hair shaft from yb (root) up to yt (tip). segs: (y_lo, y_hi, color, a) fills."""
    if alpha <= 0.004 or yb - yt < 2:
        return
    for (y0, y1, col, a) in segs:
        y0, y1 = min(yb, y0), max(yt, y1)
        if y0 - y1 > 1:
            rad = w / 2 if y1 <= yt + w / 2 else 0
            fr.rect(x - w / 2, y1, x + w / 2, y0, col, a * alpha, radius=rad)
    fr.rrect_outline(x - w / 2, yt, x + w / 2, yb, w / 2, ocol, ow, alpha)

def hstrand(fr, xr, xl, y, h, segs=(), alpha=1.0, ow=4):
    """Horizontal shaft, root at xr (right), tip at xl (left). segs: (x_lo, x_hi, color, a)."""
    if alpha <= 0.004 or xr - xl < 2:
        return
    for (x0, x1, col, a) in segs:
        x0, x1 = max(xl, x0), min(xr, x1)
        if x1 - x0 > 1:
            rad = h / 2 if x0 <= xl + h / 2 else 0
            fr.rect(x0, y - h / 2, x1, y + h / 2, col, a * alpha, radius=rad)
    fr.rrect_outline(xl, y - h / 2, xr, y + h / 2, h / 2, WHITE, ow, alpha)

def skin(fr, y, alpha=1.0, label=True):
    fr.line(110, y, 970, y, DIM, 3, alpha, cap=False)
    if label:
        stext(fr, "skin", MD(34), NOTE, 120, y + 34, alpha=alpha, align="l")

def bulb(fr, x, y, r, alpha=1.0, col=DIM):
    fr.arc(x, y, r, 25, 335, col, 4, alpha)

def mouse(fr, cx, cy, s=1.0, fur=(40, 40, 40), white_p=0.0, alpha=1.0):
    if alpha <= 0.004:
        return
    col = tuple(int(lerp(fur[i], 255, white_p)) for i in range(3))
    pts = [(cx - 130 * s + k * 6 * s, cy + 40 * s + 40 * s * math.sin(k * 0.35)) for k in range(14)]
    for a, b in zip(pts, pts[1:]):
        fr.line(a[0] - 60 * s, a[1], b[0] - 60 * s, b[1], DIM, 5 * s, alpha)
    ell(fr, cx, cy, 120 * s, 72 * s, fill=col, outline=WHITE, width=4, alpha=alpha)
    fr.circle(cx + 118 * s, cy - 12 * s, 52 * s, fill=col, outline=WHITE, width=4, alpha=alpha)
    fr.circle(cx + 96 * s, cy - 62 * s, 28 * s, fill=col, outline=WHITE, width=4, alpha=alpha)
    fr.circle(cx + 140 * s, cy - 22 * s, 7 * s, fill=WHITE if white_p < 0.5 else BLACK, alpha=alpha)

def lamp(fr, cx, cy, t, alpha=1.0):
    glow_dot(fr, cx, cy, 46, WHITE, alpha=alpha, glow=0.6, glow_r=40, scale=hold_pulse(t, 1.4, 0.95, 1.05))
    for k in range(10):
        a = math.radians(k * 36 + t * 12)
        fr.line(cx + 80 * math.cos(a), cy + 80 * math.sin(a), cx + 120 * math.cos(a), cy + 120 * math.sin(a), WHITE, 5, alpha * 0.7)

def big_rehook(fr, t, s0, text, y=900):
    p = eback(t, s0 + 0.05, 0.5)
    ktext(fr, text, XB(112), WHITE, CX, y, t, s0 + 0.05, maxw=900, lh=128, stagger=0.07, dur=0.35, rise=40)
    wl = 420 * ein(t, s0 + 0.25, 0.4)
    fr.line(CX - wl, y + 200, CX + wl, y + 200, AMBER, 8, 1.0)

# ---------------------------------------------------------------- scenes
def s_hook(fr, t, s0, s1):
    x, yb, yt0, w = CX, 1480, 760, 170
    g = ein(t, 0.0, 0.55)
    yt = lerp(yb - 200, yt0, g)
    tst = T(1, "see-through")
    fill = 1 - ein(t, tst - 0.05, 0.45)
    for k in range(12):
        y = 790 + k * 58
        col = DIM if k % 2 == 0 else NOTE
        fr.line(110, y, x - w / 2 - 6, y, col, 3, 1.0, cap=False)
        fr.line(x + w / 2 + 6, y, 970, y, col, 3, 1.0, cap=False)
    strand(fr, x, yb, yt, w, [(yb, yt, WHITE, fill)], ow=5)
    for k in range(12):
        y = 790 + k * 58
        if yt + 10 < y < yb - 4:
            fr.line(x - w / 2 + 5, y, x + w / 2 - 5, y, DIM if k % 2 == 0 else NOTE, 3, 1 - fill, cap=False)
    fr.line(x - w / 2 + 34, yt + 90, x - w / 2 + 34, yb - 60, WHITE, 8, 0.55 * (1 - fill))
    ktext(fr, "Grey hair isn't grey.", XB(116), WHITE, CX, 470, t, maxw=920, lh=130, dur=0.3, rise=30,
          times=[0.06, 0.16, T(0, "isn't"), T(0, "grey", 2)])
    ktext(fr, "It's see-through.", XB(92), AMBER if False else WHITE, CX, 1640, t, maxw=920, dur=0.3,
          times=[T(1, "it's"), tst])

def s_clear(fr, t, s0, s1):
    c = 2
    yb, yt = 1420, 760
    g = ein(t, s0, 1.6)
    strand(fr, CX, yb, lerp(yb, yt, g), 110)
    skin(fr, yb - 80, ein(t, s0, 0.3))
    bulb(fr, CX, yb, 90, ein(t, s0, 0.3))
    ktext(fr, "Every hair starts out clear", BD(76), WHITE, CX, 470, t, s0 + 0.05, maxw=900, lh=92)
    tf = T(c, "fishing")
    ktext(fr, "like fishing line", MD(52), DIM, CX, 1600, t, tf - 0.1)

def s_root(fr, t, s0, s1):
    c = 3
    yb, yt = 1420, 760
    ti = T(c, "injected")
    fp = eio(t, ti - 0.1, 1.2)
    strand(fr, CX, yb, yt, 110, [(yb, lerp(yb, yt, fp), AMBER, 1.0)])
    skin(fr, yb - 80)
    bulb(fr, CX, yb, 90)
    ta = ein(t, T(c, "root") - 0.1, 0.4)
    arrow(fr, CX + 300, yb + 30, CX + 120, yb + 10, AMBER, 8, 30, ta)
    stext(fr, "root", SB(46), AMBER, CX + 330, yb + 30, alpha=ta, align="l")
    ktext(fr, "Color gets injected from the root", BD(76), WHITE, CX, 470, t, s0 + 0.05, maxw=900, lh=92)

def follicle_cells(fr, t, x, y, n, alpha, active=1.0, jitter=0.0, scale=1.0):
    for k in range(n):
        a = math.radians(20 + k * (140 / max(1, n - 1)))
        r = 112
        jx = jitter * 10 * math.sin(t * 37 + k * 2.1)
        jy = jitter * 10 * math.cos(t * 41 + k * 1.3)
        px, py = x + r * math.cos(a) + jx, y + r * math.sin(a) * 0.9 + 30 + jy
        fr.circle(px, py, 22 * scale, fill=AMBER, alpha=alpha * active)
        fr.circle(px, py, 22 * scale, outline=AMBER, width=3, alpha=alpha * (1 - active) * 0.6)

def s_follicle(fr, t, s0, s1):
    c = 4
    x, y = CX, 1100
    ktext(fr, "Deep in each follicle", XB(84), WHITE, CX, 470, t, s0 + 0.05, maxw=900)
    a = ein(t, s0, 0.3)
    sc = 1.0 + 0.06 * ein(t, s0, 2.5)
    fr.arc(x, y, 300 * sc, 25, 335, DIM, 5, a)
    fr.line(x - 120 * sc, y - 287 * sc, x - 120 * sc, 560, DIM, 5, a, cap=False)
    fr.line(x + 120 * sc, y - 287 * sc, x + 120 * sc, 560, DIM, 5, a, cap=False)
    tp = T(c, "pigment")
    for k in range(9):
        ang = math.radians(20 + k * 140 / 8)
        p = eback(t, tp - 0.1 + k * 0.05, 0.45)
        fr.circle(x + 220 * sc * math.cos(ang), y + 220 * sc * math.sin(ang) * 0.85, 40 * clamp(p, 0, 1.2), fill=AMBER, alpha=ein(t, tp - 0.1 + k * 0.05, 0.3))
    stext(fr, "pigment cells", SB(52), AMBER, x, 1580, alpha=ein(t, tp, 0.4))

def s_melanin(fr, t, s0, s1):
    c = 4
    x, yb = CX, 1350
    ktext(fr, "They pump melanin into the growing hair", BD(70), WHITE, CX, 470, t, s0 + 0.02, maxw=900, lh=86)
    a = ein(t, s0, 0.3)
    skin(fr, 920, a)
    bulb(fr, x, yb, 160, a)
    strand(fr, x, yb, 640, 110, [(yb, 640, AMBER, 0.85)], alpha=a)
    tp = T(c, "pigment")
    follicle_cells(fr, t, x, yb, 7, 1.0)
    tm = T(c, "melanin")
    if t > tm - 0.2:
        for k in range(14):
            ph = ((t - tm) * 0.9 + k / 14) % 1.0
            px = x + 28 * math.sin(k * 2.3)
            py = lerp(yb + 40, yb - 520, ph)
            fr.circle(px, py, 9, fill=(255, 220, 160), alpha=ein(t, tm - 0.2, 0.4) * (1 - ph))
    stext(fr, "melanin", SB(50), AMBER, x + 120, 1080, alpha=ein(t, tm, 0.4), align="l")


def s_quit(fr, t, s0, s1):
    c = 5
    x, yb = CX, 1350
    tq = T(c, "quit")
    te = T(c, "empty")
    grow = 260 * eio(t, tq + 0.1, 1.6)
    ktext(fr, "When those cells quit...", BD(76), WHITE, CX, 440, t, s0 + 0.05, maxw=900)
    ktext(fr, "the hair grows in empty", BD(76), WHITE, CX, 560, t, T(c, "hair") - 0.1, maxw=900)
    skin(fr, 1100)
    bulb(fr, x, yb, 160)
    top = 940 - grow
    strand(fr, x, yb, top, 110, [(yb - grow, top, AMBER, 0.85)])
    follicle_cells(fr, t, x, yb, 7, 1.0, active=1 - ein(t, tq - 0.05, 0.5))
    ea = ein(t, te - 0.1, 0.4)
    stext(fr, "empty", SB(50), WHITE, x + 120, yb - 200, alpha=ea, align="l")

def s_scatter(fr, t, s0, s1):
    c = 6
    y, xl, xr, h = 1050, 140, 940, 300
    ktext(fr, "Air pockets scatter light", BD(80), WHITE, CX, 470, t, s0 + 0.05, maxw=900)
    hstrand(fr, xr, xl, y, h, alpha=ein(t, s0, 0.3), ow=5)
    rnd = random.Random(7)
    bubbles = [(rnd.uniform(xl + 90, xr - 60), rnd.uniform(y - 100, y + 100), rnd.uniform(14, 34)) for _ in range(16)]
    ta = T(c, "air")
    for k, (bx, by, r) in enumerate(bubbles):
        fr.circle(bx, by, r * eback(t, ta + k * 0.03, 0.4), outline=WHITE, width=3, alpha=ein(t, ta + k * 0.03, 0.3) * 0.8)
    ts = T(c, "scatter")
    for k in range(6):
        yy = y - 110 + k * 44
        p = clamp((t - ts - k * 0.07) / 0.5)
        if p > 0:
            arrow(fr, 0 + 0 * k, yy, lerp(10, 360 + 40 * (k % 3), p), yy, WHITE, 5, 18, 0.9)
        q = clamp((t - ts - 0.5 - k * 0.07) / 0.6)
        if q > 0:
            ang = math.radians(-150 + k * 52 + 20)
            sx, sy = 400 + 40 * (k % 3), yy
            arrow(fr, sx, sy, sx + 300 * q * math.cos(ang), sy + 300 * q * math.sin(ang), WHITE, 5, 18, 0.9 * (1 - 0.3 * q))
    tw = T(c, "white")
    ktext(fr, "clear  →  looks white", BD(64), WHITE, CX, 1500, t, T(c, "clear") - 0.05)
    p = ein(t, tw - 0.05, 0.4)

def s_lamp(fr, t, s0, s1):
    c = 7
    a = ein(t, s0, 0.3)
    lamp(fr, CX, 800, t, a)
    ty = T(c, "hold")
    yo = 200 * (1 - eio(t, ty - 0.2, 0.6))
    strand(fr, CX, 1300 + yo, 760 + yo, 46, ow=3, alpha=ein(t, T(c, "pull") - 0.1, 0.3))
    ktext(fr, "Try it: hold one up to a lamp", BD(72), WHITE, CX, 1560, t, s0 + 0.05, maxw=880, lh=88)

def s_insane(fr, t, s0, s1):
    big_rehook(fr, t, s0, "But here's the insane part.")

def s_stress(fr, t, s0, s1):
    c = 9
    ktext(fr, "Stress really can turn you grey", XB(92), WHITE, CX, 560, t, s0 + 0.05, maxw=900, lh=108)
    tg = T(c, "grey")
    for i in range(5):
        x = CX + (i - 2) * 130
        p = eio(t, tg - 0.3 + i * 0.08, 0.6)
        strand(fr, x, 1500, 900, 56, [(1500, 900, AMBER, 0.9 * (1 - p)), (1500, 900, WHITE, 0.9 * p)], ow=3,
               alpha=ein(t, s0 + 0.2 + i * 0.05, 0.3))

def s_hormones(fr, t, s0, s1):
    c = 9
    ktext(fr, "...and it isn't", XB(96), WHITE, CX, 640, t, s0 + 0.02, maxw=900)
    th = T(c, "isn't")
    a = ein(t, th - 0.1, 0.4)
    stext(fr, "stress hormones", BD(80), DIM, CX, 1150, alpha=a)
    ts = T(c, "hormones", end=True)
    sl = 330 * ein(t, ts - 0.25, 0.3)
    fr.line(CX - 330, 1150, CX - 330 + 2 * sl, 1150, AMBER, 10, 1.0 if sl > 1 else 0)

def s_harvard(fr, t, s0, s1):
    c = 10
    ktext(fr, "2020", XB(220), WHITE, CX, 800, t, T(c, "2020") - 0.25, dur=0.35)
    ktext(fr, "Harvard scientists", BD(72), DIM, CX, 1040, t, T(c, "harvard") - 0.1)
    mouse(fr, CX - 40, 1380, 1.0, alpha=ein(t, T(c, "stressed") - 0.1, 0.4))

def s_mice(fr, t, s0, s1):
    c = 10
    ktext(fr, "Stressed out mice with", BD(80), WHITE, CX, 520, t, s0 + 0.02, maxw=900)
    tm = T(c, "mice")
    for i, (lab, key) in enumerate([("pain", "pain"), ("confinement", "confinement"), ("chaos", "chaos")]):
        y = 860 + i * 300
        tk = T(c, key)
        mouse(fr, CX - 60, y, 0.85, alpha=ein(t, tm - 0.2 + i * 0.1, 0.4))
        la = ein(t, tk - 0.05, 0.35)
        stext(fr, lab, SB(46), AMBER, CX + 200, y + 10, alpha=la, align="l", dy=(1 - la) * 12)

def s_white(fr, t, s0, s1):
    c = 11
    ktext(fr, "Within weeks...", BD(80), WHITE, CX, 470, t, s0 + 0.05)
    tb = T(c, "black")
    tw = T(c, "white")
    wp = eio(t, tw - 0.4, 1.0)
    sc = 1.9 + 0.05 * ein(t, s0, 2.5)
    mouse(fr, CX - 40, 1050, sc, white_p=wp, alpha=ein(t, s0, 0.3))
    stext(fr, "black fur", SB(56), DIM, CX - 200, 1420, alpha=ein(t, tb - 0.05, 0.4))
    stext(fr, "→", SB(56), DIM, CX, 1420, alpha=ein(t, tw - 0.3, 0.4))
    stext(fr, "white", SB(56), WHITE, CX + 170, 1420, alpha=ein(t, tw - 0.05, 0.4))

def s_culprit(fr, t, s0, s1):
    big_rehook(fr, t, s0, "The culprit?")

def nerve_pts(x, y):
    pts = []
    for k in range(60):
        u = k / 59
        ang = math.radians(200 + u * 500)
        r = 220 - u * 40
        pts.append((x + r * math.cos(ang) + 0, y + r * math.sin(ang) * 0.75 - 140 + u * 260))
    return pts

def draw_nerve(fr, x, y, prog, alpha=1.0, col=WHITE):
    pts = nerve_pts(x, y)
    n = int(len(pts) * clamp(prog))
    for a, b in zip(pts[:n], pts[1:n]):
        fr.line(a[0], a[1], b[0], b[1], col, 6, alpha)
    return pts

def s_nerves(fr, t, s0, s1):
    c = 13
    x, yb = CX, 1250
    ktext(fr, "Fight-or-flight nerves", XB(84), WHITE, CX, 470, t, T(c, "fight") - 0.1, maxw=900)
    ktext(fr, "wrap every follicle", BD(64), DIM, CX, 580, t, T(c, "wrapped") - 0.1, maxw=900)
    skin(fr, 860)
    bulb(fr, x, yb, 140)
    strand(fr, x, yb, 700, 100, [(yb, 700, AMBER, 0.85)])
    follicle_cells(fr, t, x, yb - 20, 7, 1.0, scale=0.85)
    pts = draw_nerve(fr, x, yb, eio(t, T(c, "wrapped") - 0.2, 1.3))
    if t > T(c, "nerves"):
        for k in range(3):
            ph = ((t - T(c, "nerves")) * 0.8 + k / 3) % 1.0
            px, py = pts[int(ph * (len(pts) - 1))]
            glow_dot(fr, px, py, 10, WHITE, alpha=0.9, glow_r=16)

def s_flood(fr, t, s0, s1):
    c = 14
    x, yb = CX, 1250
    ktext(fr, "Under stress they flood it with", BD(70), WHITE, CX, 420, t, s0 + 0.05, maxw=900)
    tn = T(c, "noradrenaline")
    ktext(fr, "noradrenaline", XB(96), WHITE, CX, 610, t, tn - 0.1)
    skin(fr, 860)
    bulb(fr, x, yb, 140)
    strand(fr, x, yb, 700, 100, [(yb, 700, AMBER, 0.85)])
    follicle_cells(fr, t, x, yb - 20, 7, 1.0, scale=0.85, jitter=ein(t, tn, 0.6) * 0.5)
    pts = draw_nerve(fr, x, yb, 1.0)
    rnd = random.Random(3)
    tf = T(c, "flood")
    for k in range(70):
        src = pts[rnd.randrange(len(pts))]
        st = tf - 0.3 + rnd.uniform(0, 1.6)
        ph = clamp((t - st) / 0.9)
        if ph <= 0:
            continue
        tx, ty = x + rnd.uniform(-90, 90), yb + rnd.uniform(-60, 80)
        fr.circle(lerp(src[0], tx, ein(ph, 0, 1)), lerp(src[1], ty, ein(ph, 0, 1)), 7, fill=WHITE, alpha=0.85)

def s_panic(fr, t, s0, s1):
    c = 15
    x, y = CX, 1100
    ktext(fr, "Pigment stem cells panic", XB(80), WHITE, CX, 470, t, s0 + 0.05, maxw=900)
    tw = T(c, "wake")
    ktext(fr, "and all wake up at once", BD(64), DIM, CX, 660, t, tw - 0.1, maxw=900)
    jit = ein(t, T(c, "panic") - 0.1, 0.3)
    wk = eback(t, tw, 0.5)
    rnd = random.Random(5)
    for k in range(12):
        a = math.radians(k * 30)
        r = 230
        px = x + r * math.cos(a) + jit * 9 * math.sin(t * 40 + k)
        py = y + r * math.sin(a) + jit * 9 * math.cos(t * 43 + k)
        rr = 34 * (1 + 0.35 * clamp(wk) if t > tw else 1)
        fr.circle(px, py, rr, fill=AMBER, alpha=ein(t, s0 + k * 0.03, 0.3))
        if t > tw:
            pulse_rings(fr, px, py, t, tw, AMBER, n=1, period=0.7, r0=30, r1=80, width=3)
    stext(fr, "stem cell reserve", MD(40), DIM, x, y, alpha=ein(t, s0, 0.4))

def s_burn(fr, t, s0, s1):
    c = 15
    x, y = CX, 1100
    ktext(fr, "...and burn through the entire reserve", XB(76), WHITE, CX, 480, t, s0 + 0.02, maxw=900, lh=92)
    tb = T(c, "burn")
    te = T(c, "reserve", end=True)
    for k in range(12):
        a = math.radians(k * 30)
        r = 230
        tk = lerp(tb, te, k / 11)
        al = 1 - ein(t, tk, 0.35)
        fr.circle(x + r * math.cos(a), y + r * math.sin(a), 44 * (0.6 + 0.4 * al), fill=AMBER, alpha=al)
        fr.circle(x + r * math.cos(a), y + r * math.sin(a), 44, outline=FAINT, width=3, alpha=1 - al)
    p = clamp((t - tb) / (te - tb))
    pct = int(round(100 * (1 - p)))
    stext(fr, f"{pct}%", XB(130), AMBER if pct > 0 else WHITE, x, y, tnum=True)
    stext(fr, "left", MD(40), DIM, x, y + 110)

def s_never(fr, t, s0, s1):
    c = 16
    x, yb = CX, 1250
    ktext(fr, "The cells never came back", XB(84), WHITE, CX, 480, t, s0 + 0.05, maxw=900, lh=100)
    yb = 1400
    skin(fr, 1100)
    bulb(fr, x, yb, 140)
    g = 120 * ein(t, s0, 2.4)
    strand(fr, x, yb, 820 - g, 100, [(yb - 380 - g, 820 - g, AMBER, 0.85)])
    for k in range(7):
        a = math.radians(20 + k * (140 / 6))
        px, py = x + 112 * math.cos(a), yb - 20 + 112 * math.sin(a) * 0.9 + 30
        dashed_line(fr, px - 18, py, px + 18, py, FAINT, 3, 1.0, dash=8, gap=6)
    stext(fr, "in mice: permanent", MD(42), DIM, x, 1640, alpha=ein(t, T(c, "never") - 0.05, 0.4))

def s_weirder(fr, t, s0, s1):
    big_rehook(fr, t, s0, "And it gets weirder.")

def s_dead(fr, t, s0, s1):
    c = 18
    x, sk = CX, 1250
    ktext(fr, "The hair on your head is already dead", XB(74), WHITE, CX, 480, t, s0 + 0.05, maxw=900, lh=90)
    skin(fr, sk, label=False)
    strand(fr, x, 1500, 760, 90, [(sk, 760, DIM, 0.5), (1500, sk, AMBER, 0.85)])
    bulb(fr, x, 1500, 110)
    td = T(c, "dead")
    stext(fr, "dead", SB(50), WHITE, x + 90, 960, alpha=ein(t, td - 0.05, 0.4), align="l")
    stext(fr, "alive", SB(50), AMBER, x + 90, 1390, alpha=ein(t, td + 0.1, 0.4), align="l")
    to = T(c, "overnight")
    oa = ein(t, T(c, "white") - 0.1, 0.4)
    stext(fr, "white overnight", BD(62), DIM, CX, 1700, alpha=oa)
    sl = ein(t, to + 0.1, 0.3)
    if sl > 0:
        fr.line(CX - 250, 1700, CX - 250 + 500 * sl, 1700, AMBER, 9)

HY, HXL, HXR, HH = 1150, 110, 970, 64
def s_mapped(fr, t, s0, s1):
    c = 19
    ktext(fr, "2021 · Columbia", BD(64), DIM, CX, 430, t, T(c, "2021") - 0.2)
    ktext(fr, "Researchers mapped single human hairs", XB(74), WHITE, CX, 590, t, T(c, "researchers") - 0.1, maxw=900, lh=90)
    a = ein(t, T(c, "mapped") - 0.2, 0.4)
    hstrand(fr, HXR, HXL, HY, HH, [(HXL, HXR, AMBER, 0.85)], alpha=a)
    for k in range(18):
        xx = HXL + k * (HXR - HXL) / 17
        fr.line(xx, HY + 60, xx, HY + (90 if k % 3 == 0 else 76), DIM, 3, a, cap=False)
    sx = lerp(HXL, HXR, clamp((t - T(c, "mapped")) / 1.4))
    fr.line(sx, HY - 80, sx, HY + 80, WHITE, 4, a * (1 if t < T(c, "mapped") + 1.4 else 0))

def hair_tl(t, tdark):
    d = eio(t, tdark - 0.2, 0.7)
    split = lerp(HXR, 560, d)
    return [(HXL, 560, WHITE, 0.9), (560, split, WHITE, 0.9), (split, HXR, AMBER, 0.9)]

def s_dark(fr, t, s0, s1):
    c = 19
    ktext(fr, "Grey strands went dark again", XB(80), WHITE, CX, 520, t, T(c, "grey") - 0.1, maxw=900, lh=96)
    hstrand(fr, HXR, HXL, HY, HH, hair_tl(t, T(c, "dark")))
    stext(fr, "tip", MD(40), DIM, HXL + 10, HY + 90, align="l")
    stext(fr, "root", MD(40), DIM, HXR - 10, HY + 90, align="r")
    a = ein(t, T(c, "dark") + 0.2, 0.4)
    arrow(fr, 600, HY - 120, 900, HY - 120, AMBER, 7, 26, a)
    stext(fr, "color returns", SB(44), AMBER, 750, HY - 180, alpha=a)

def s_calm(fr, t, s0, s1):
    c = 19
    ktext(fr, "...lining up with calmer stretches of life", BD(70), WHITE, CX, 480, t, s0 + 0.02, maxw=900, lh=86)
    hstrand(fr, HXR, HXL, HY + 250, HH, hair_tl(99, 0))
    p = eio(t, T(c, "calmer") - 0.3, 1.2)
    ys = lambda xx: 830 if xx < 520 else (830 + (xx - 520) / 80 * 220 if xx < 600 else 1050)
    n = int(40 * p)
    pts = [(HXL + k * (HXR - HXL) / 39, ys(HXL + k * (HXR - HXL) / 39)) for k in range(40)]
    for q1, q2 in zip(pts[:n], pts[1:n]):
        fr.line(q1[0], q1[1], q2[0], q2[1], WHITE, 6)
    stext(fr, "stress", SB(44), WHITE, HXL, 770, alpha=ein(t, s0, 0.4), align="l")
    stext(fr, "calm", SB(44), AMBER, HXR, 990, alpha=ein(t, T(c, "calmer"), 0.4), align="r")

def s_notall(fr, t, s0, s1):
    c = 20
    ktext(fr, "Not everyone. Not every hair.", XB(78), WHITE, CX, 480, t, s0 + 0.05, maxw=900, lh=96)
    for i in range(9):
        x = 180 + i * 90
        rv = i in (2, 6)
        p = ein(t, T(c, "every") + 0.1 * i, 0.5) if rv else 0
        strand(fr, x, 1500, 850, 44, [(1500, 850, WHITE, 0.85), (1500, lerp(1500, 1180, p), AMBER, 1.0)], ow=3,
               alpha=ein(t, s0 + i * 0.04, 0.3))

def s_negotiable(fr, t, s0, s1):
    c = 21
    ktext(fr, "But your grey might be negotiable.", XB(92), WHITE, CX, 560, t, s0 + 0.05, maxw=900, lh=108)
    p = eio(t, T(c, "negotiable") - 0.2, 0.9)
    strand(fr, CX, 1550, 900, 110, [(1550, 900, WHITE, 0.85), (1550, lerp(1550, 1250, p), AMBER, 1.0)])

def s_mirror(fr, t, s0, s1):
    c = 22
    a = ein(t, s0, 0.35)
    fr.rrect_outline(250, 760, 830, 1500, 280, DIM, 6, a)
    tf = T(c, "one")
    strand(fr, CX, 1250, 980, 30, [(1250, 980, WHITE, 1.0)], ow=2, alpha=ein(t, tf - 0.2, 0.3))
    if t > tf:
        glow_dot(fr, CX + 4, 1010, 8, WHITE, alpha=ein(t, tf, 0.3), glow_r=30, scale=hold_pulse(t, 0.9, 0.8, 1.3))
    ktext(fr, "Next time you find one in the mirror,", BD(70), WHITE, CX, 480, t, s0 + 0.05, maxw=900, lh=86)

def s_remember(fr, t, s0, s1):
    ktext(fr, "remember.", XB(130), WHITE, CX, 900, t, s0 + 0.05, dur=0.35, rise=36)
    strand(fr, CX, 1500, 1150, 60, [(1500, 1150, WHITE, 0.9)], ow=3, alpha=ein(t, s0 + 0.2, 0.4))

# --- scene list: (function, start time) -----------------------------------
SC = [(s_hook, 0.0), (s_clear, boundary(2)), (s_root, boundary(3)), (s_follicle, boundary(4)), (s_melanin, T(4, "pump") - 0.1),
      (s_quit, boundary(5)), (s_scatter, boundary(6)), (s_lamp, boundary(7)), (s_insane, boundary(8)),
      (s_stress, boundary(9)), (s_hormones, T(9, "and") - 0.05), (s_harvard, boundary(10)), (s_mice, T(10, "stressed") + 0.6), (s_white, boundary(11)), (s_culprit, boundary(12)),
      (s_nerves, boundary(13)), (s_flood, boundary(14)), (s_panic, boundary(15)),
      (s_burn, T(15, "and") - 0.08), (s_never, boundary(16)), (s_weirder, boundary(17)),
      (s_dead, boundary(18)), (s_mapped, boundary(19)), (s_dark, T(19, "and") - 0.03),
      (s_calm, (T(19, "again", end=True) + T(19, "lining")) / 2), (s_notall, boundary(20)),
      (s_negotiable, boundary(21)), (s_mirror, boundary(22)), (s_remember, T(22, "remember") - 0.12)]

STARTS = [s for _, s in SC]
ENDS = STARTS[1:] + [TOTAL]

def render(t):
    i = len(SC) - 1
    for j in range(len(SC)):
        if t < ENDS[j]:
            i = j
            break
    fn, _ = SC[i]
    s0, s1 = STARTS[i], ENDS[i]
    fr = Frame()
    fn(fr, t, s0, s1)
    f = clamp((s1 - t) / 0.18) if i < len(SC) - 1 else clamp((TOTAL - t) / 1.2)
    return fr.render(f)
# ============================================================ CLI (keep as-is) =====
if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    if mode == "frames":
        os.makedirs("preview", exist_ok=True)
        for arg in sys.argv[2:]:
            render(float(arg)).save(f"preview/t_{float(arg):07.2f}.png")
    elif mode == "sheet":
        ts = [float(a) for a in sys.argv[3:]]
        cols = 3
        tw, th = 360, 640
        rows = math.ceil(len(ts) / cols)
        sheet = Image.new("RGB", (cols * tw + (cols + 1) * 8, rows * th + (rows + 1) * 8), (40, 40, 40))
        for k, tt in enumerate(ts):
            im = render(tt).resize((tw, th), Image.LANCZOS)
            sheet.paste(im, (8 + (k % cols) * (tw + 8), 8 + (k // cols) * (th + 8)))
        sheet.save(sys.argv[2])
    elif mode == "part":
        a, b, outp = int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
        b = min(b, int(math.ceil(TOTAL * FPS)))
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
               "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
               "-pix_fmt", "yuv420p", outp]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        t0 = time.time()
        for k in range(a, b):
            p.stdin.write(render(k / FPS).tobytes())
        p.stdin.close(); p.wait()
        print(f"frames {a}-{b} done in {time.time() - t0:.0f}s", flush=True)
    elif mode == "bench":
        t0 = time.time()
        for k in range(20):
            render(min(TOTAL - 0.1, 5 + k * (TOTAL / 25)))
        print("sec/frame:", (time.time() - t0) / 20)
    else:  # full -- fine for quick local tests; use `part` x N for the real deliverable
        n = int(math.ceil(TOTAL * FPS))
        print("frames:", n, "duration:", TOTAL, flush=True)
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
               "-r", str(FPS), "-i", "-", "-i", "audio/vo.mp3", "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "out.mp4"]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for k in range(n):
            p.stdin.write(render(k / FPS).tobytes())
        p.stdin.close(); p.wait()
        print("done", flush=True)
