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
YELLOW = (255, 197, 66)      # <-- replace: this video's ONE accent color
PEEL = (66, 48, 20)          # <-- example-only detail color, delete if unused

AUDIO_END = 65.750204        # <-- replace with your audio's real duration (seconds)
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

# ============================================================ SCENES: soda fizz is acid =====
ACID = (182, 255, 64)   # the ONE accent: acid

def bubbles(fr, x0, x1, yb, yt, t, n=14, color=WHITE, alpha=1.0, rmin=6, rmax=16, speed=1.0, seed=1, width=3):
    import random
    rnd = random.Random(seed)
    for k in range(n):
        x = rnd.uniform(x0, x1); ph0 = rnd.random(); per = rnd.uniform(1.6, 2.8) / speed
        r = rnd.uniform(rmin, rmax); wob = rnd.uniform(4, 10)
        ph = (t / per + ph0) % 1.0
        y = lerp(yb, yt, ph)
        a = alpha * min(1, ph * 6, (1 - ph) * 6)
        fr.circle(x + wob * math.sin(ph * 9 + k), y, r, outline=color, width=width, alpha=a)

def glass(fr, cx, cy, w=300, h=420, alpha=1.0, liquid=None, la=1.0, color=WHITE):
    tw, bw = w / 2, w * 0.38
    top, bot = cy - h / 2, cy + h / 2
    if liquid:
        ly = top + h * 0.18
        f = (ly - top) / h
        lw = tw + (bw - tw) * f
        fr.poly([(cx - lw, ly), (cx + lw, ly), (cx + bw, bot), (cx - bw, bot)], liquid, alpha * la)
    fr.line(cx - tw, top, cx - bw, bot, color, 7, alpha)
    fr.line(cx + tw, top, cx + bw, bot, color, 7, alpha)
    fr.line(cx - bw, bot, cx + bw, bot, color, 7, alpha)

def molecule(fr, cx, cy, s=1.0, alpha=1.0, color=WHITE, label=True):
    for dx in (-1, 1):
        fr.line(cx, cy, cx + dx * 92 * s, cy, color, 6 * s, alpha)
        fr.circle(cx + dx * 92 * s, cy, 40 * s, fill=BLACK, alpha=1.0) if alpha > 0.5 else None
        fr.circle(cx + dx * 92 * s, cy, 40 * s, outline=color, width=6 * s, alpha=alpha)
        if label: stext(fr, "O", BD(int(44 * s)), color, cx + dx * 92 * s, cy, alpha=alpha)
    fr.circle(cx, cy, 46 * s, fill=color, alpha=alpha)
    if label: stext(fr, "C", BD(int(50 * s)), BLACK, cx, cy, alpha=1.0 if alpha > 0.5 else 0)

def tongue(fr, cx, cy, w=760, h=260, alpha=1.0, color=WHITE):
    # dome-shaped tongue surface with papillae bumps
    fr.arc(cx, cy + h, w / 2, -90, 90, color, 6, alpha)
    for k in range(9):
        a = math.radians(-70 + k * 17.5)
        x = cx + (w / 2 - 22) * math.sin(a); y = cy + h - (w / 2 - 22) * math.cos(a)
        fr.circle(x, y, 12, fill=color, alpha=alpha * 0.55)

def can(fr, cx, cy, s=1.0, alpha=1.0, opened=0.0):
    w, h = 220 * s, 380 * s
    fr.rrect_outline(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, 34 * s, WHITE, 7, alpha)
    fr.line(cx - w / 2 + 14, cy - h / 2 + 40 * s, cx + w / 2 - 14, cy - h / 2 + 40 * s, DIM, 4, alpha)
    ang = -38 * opened
    L = 70 * s; ar = math.radians(ang)
    fr.line(cx - 10, cy - h / 2 + 18 * s, cx - 10 + L * math.cos(ar), cy - h / 2 + 18 * s + L * math.sin(ar), WHITE, 8, alpha)

def cross(fr, cx, cy, r, p, color=WHITE, alpha=1.0, width=12):
    if p <= 0: return
    fr.line(cx - r, cy - r, cx - r + 2 * r * clamp(p * 2), cy - r + 2 * r * clamp(p * 2), color, width, alpha)
    if p > 0.5:
        q = clamp(p * 2 - 1)
        fr.line(cx + r, cy - r, cx + r - 2 * r * q, cy - r + 2 * r * q, color, width, alpha)

def times_of(c, words):
    return [T(c, w) if not isinstance(w, tuple) else T(c, *w) for w in words]

def v_hook(fr, t, s0, s1):
    c = 0
    ta = T(c, "acid")
    gp = clamp((t - (ta - 0.3)) / 0.5)
    glass(fr, CX, 650, 420, 560, liquid=pc(ACID, 0.35) if gp > 0 else None, la=gp)
    col = WHITE if gp < 0.5 else ACID
    bubbles(fr, CX - 140, CX + 140, 900, 440, t + 3, n=24, color=col, alpha=1.0, speed=1.2)
    ktext(fr, "The fizz in your soda isn't the bubbles.", XB(96), WHITE, CX, 1140, t, maxw=920, lh=112,
          times=[-0.12, 0.02, 0.62, 0.74, 0.88, 1.40, 1.68, 1.76], dur=0.3)
    p = eback(t, ta - 0.25, 0.5)
    stext(fr, "It's acid.", XB(150), ACID, CX, 1500, alpha=ein(t, ta - 0.3, 0.25), dy=(1 - clamp(p)) * 40)

def v_myth(fr, t, s0, s1):
    c = 1
    ktext(fr, "What everyone thinks:", MD(48), DIM, CX, 470, t, s0 + 0.1)
    tongue(fr, CX, 820, alpha=ein(t, T(c, "bite") - 0.2, 0.4))
    tb = T(c, "popping")
    import random
    rnd = random.Random(3)
    for k in range(9):
        x = CX + rnd.uniform(-260, 260); y = 900 + rnd.uniform(-60, 40)
        t0 = T(c, "bubbles") - 0.2 + k * 0.08
        a = ein(t, t0, 0.3)
        if t < tb + k * 0.12:
            fr.circle(x, y, 26, outline=WHITE, width=4, alpha=a)
        else:
            q = clamp((t - tb - k * 0.12) / 0.35)
            for j in range(6):
                an = j * math.pi / 3
                fr.line(x + 18 * q * math.cos(an), y + 18 * q * math.sin(an), x + (24 + 30 * q) * math.cos(an), y + (24 + 30 * q) * math.sin(an), WHITE, 4, 1 - q)
    ktext(fr, "Tiny bubbles popping on your tongue.", BD(70), WHITE, CX, 1350, t, maxw=860, lh=86,
          times=times_of(c, ["tiny", "bubbles", "popping", "on", "your", "tongue"]))

def v_nope(fr, t, s0, s1):
    c = 2
    p = eback(t, T(c, "nope") - 0.1, 0.45)
    stext(fr, "Nope.", XB(240), WHITE, CX, 800, alpha=ein(t, T(c, "nope") - 0.12, 0.2), dy=(1 - clamp(p)) * 50)
    ktext(fr, "Scientists sat people in a...", MD(54), DIM, CX, 1150, t, maxw=860,
          times=times_of(c, ["scientists", "sat", "people", "in", "a"]))

def v_chamber(fr, t, s0, s1):
    c = 2
    t0 = T(c, "pressure")
    a = ein(t, t0 - 0.1, 0.4)
    fr.rrect_outline(170, 520, 910, 1220, 60, WHITE, 8, a)
    # pressure gauge
    gx, gy = 810, 600
    fr.circle(gx, gy, 70, fill=BLACK, alpha=1)
    fr.circle(gx, gy, 70, outline=WHITE, width=6, alpha=a)
    ang = lerp(-120, 60, ein(t, t0, 1.0))
    fr.line(gx, gy, gx + 52 * math.sin(math.radians(ang)), gy - 52 * math.cos(math.radians(ang)), WHITE, 6, a)
    stext(fr, "2x air pressure", SB(40), DIM, CX, 470, alpha=a)
    # person + glass inside
    fr.circle(400, 820, 60, outline=WHITE, width=7, alpha=a)
    fr.arc(400, 1080, 130, -90, 90, WHITE, 7, a)
    glass(fr, 640, 1010, 170, 250, alpha=a, liquid=(60, 60, 60), la=1)
    tb = T(c, "bubbles")
    cross(fr, 640, 1010, 70, ein(t, tb, 0.5), WHITE, 1.0, 10)
    ktext(fr, "Bubbles physically can't form.", BD(70), WHITE, CX, 1420, t, maxw=860, lh=86,
          times=times_of(c, ["bubbles", "physically", "can't", "form"]))

def bar(fr, x, ybot, w, hmax, p, color, alpha=1.0):
    if p <= 0: return
    fr.rect(x - w / 2, ybot - hmax * p, x + w / 2, ybot, color, alpha, radius=10)

def v_same(fr, t, s0, s1):
    c = 3
    cols = [(CX - 220, "Normal", True), (CX + 220, "Chamber", False)]
    for x, lab, bub in cols:
        a = ein(t, s0 + 0.1, 0.4)
        glass(fr, x, 700, 200, 290, alpha=a, liquid=(60, 60, 60))
        if bub:
            bubbles(fr, x - 60, x + 60, 820, 600, t, n=8, rmin=5, rmax=11)
        stext(fr, lab, SB(42), DIM, x, 910, alpha=a)
        pb = ein(t, T(c, "bite") - 0.3, 0.6)
        bar(fr, x, 1330, 120, 300, pb, WHITE)
    fr.line(160, 1330, 920, 1330, FAINT, 3)
    stext(fr, "bite", MD(38), DIM, CX, 1380, alpha=ein(t, T(c, "bite") - 0.3, 0.4))
    tz = T(c, "zero")
    p = eback(t, tz - 0.1, 0.45)
    stext(fr, "Zero bubbles.", XB(110), WHITE, CX, 1570, alpha=ein(t, tz - 0.12, 0.25), dy=(1 - clamp(p)) * 30)
    ktext(fr, "Same fizz. Same bite.", BD(66), WHITE, CX, 470, t, times=times_of(c, ["same", "fizz", ("same", 2), "bite"]))

def v_insane(fr, t, s0, s1):
    c = 4
    ktext(fr, "So what are you actually feeling?", BD(66), DIM, CX, 700, t, maxw=860, lh=82,
          times=times_of(c, ["so", "what", "are", "you", "actually", "feeling"]))
    th = T(c, "here's")
    p = eback(t, th - 0.1, 0.5)
    sc = clamp(p)
    stext(fr, "Here's the", XB(110), WHITE, CX, 1060, alpha=ein(t, th - 0.12, 0.2), dy=(1 - sc) * 40)
    ti = T(c, "insane")
    p2 = eback(t, ti - 0.1, 0.5)
    stext(fr, "insane part.", XB(130), WHITE, CX, 1220, alpha=ein(t, ti - 0.12, 0.2), dy=(1 - clamp(p2)) * 40)

def enzyme(fr, x, y, r, alpha=1.0, color=WHITE, mouth=40):
    fr.pieslice(x, y, r, 90 + mouth / 2 + 180, 90 - mouth / 2 + 360 + 180, color, alpha)

def v_enzyme(fr, t, s0, s1):
    c = 5
    tongue(fr, CX, 760, alpha=ein(t, T(c, "tongue") - 0.2, 0.4))
    te = T(c, "enzyme")
    for k in range(7):
        a = math.radians(-60 + k * 20)
        x = CX + 420 * math.sin(a); y = 1020 - 420 * math.cos(a) - 30
        s = clamp(eback(t, te - 0.15 + k * 0.06, 0.45))
        if s > 0:
            enzyme(fr, x, y - 10, 24 * s, alpha=ein(t, te - 0.15 + k * 0.06, 0.3), mouth=50 + 25 * math.sin(t * 8 + k))
    ktext(fr, "Your tongue is coated with an enzyme", MD(54), DIM, CX, 1180, t, maxw=860,
          times=times_of(c, ["your", "tongue", "is", "coated", "with", "an", "enzyme"]))
    tc = T(c, "carbonic")
    p = ein(t, tc - 0.1, 0.4)
    stext(fr, "carbonic anhydrase", XB(84), WHITE, CX, 1420, alpha=p, dy=(1 - p) * 24)

def v_grab(fr, t, s0, s1):
    c = 6
    tc = T(c, "carbon")
    a = ein(t, tc - 0.15, 0.4)
    molecule(fr, CX, 760, 1.3, alpha=a)
    stext(fr, "CO₂", XB(120), WHITE, CX, 1000, alpha=a)
    stext(fr, "carbon dioxide", MD(46), DIM, CX, 1110, alpha=a)
    td = T(c, "dissolved")
    bubbles(fr, 200, 880, 1600, 1250, t, n=10, color=DIM, alpha=ein(t, td - 0.1, 0.4), rmin=5, rmax=10)
    ktext(fr, "dissolved in your drink", BD(64), WHITE, CX, 1400, t, times=times_of(c, ["dissolved", "in", "your", "drink"]))
    # enzyme sweeps in to grab
    tg = T(c, "grabs")
    x = lerp(-80, CX - 260, ein(t, tg - 0.2, 0.6))
    enzyme(fr, x, 760, 60, alpha=1.0, mouth=30 + 40 * abs(math.sin(t * 6)))
    ktext(fr, "It grabs the", MD(50), DIM, CX, 470, t, times=times_of(c, ["it", "grabs", "the"]))

def v_snap(fr, t, s0, s1):
    c = 6
    ts = T(c, "snaps")
    p = eio(t, ts - 0.1, 0.5)
    # CO2 + H2O -> H2CO3
    y = 700
    stext(fr, "CO₂ + H₂O", XB(90), WHITE, CX, y - 110, alpha=1)
    arrow(fr, CX, y - 40, CX, y + 70, WHITE, 8, 26, alpha=ein(t, ts, 0.3))
    ta = T(c, "carbonic")
    pa = eback(t, ta - 0.15, 0.5)
    stext(fr, "H₂CO₃", XB(150), ACID, CX, y + 190, alpha=ein(t, ta - 0.2, 0.25), dy=(1 - clamp(pa)) * 30)
    ktext(fr, "carbonic acid", BD(72), ACID, CX, 1080, t, times=times_of(c, ["carbonic", "acid"]))
    ti = T(c, "almost")
    a = ein(t, ti - 0.1, 0.3)
    # stopwatch
    sx, sy = CX, 1380
    fr.circle(sx, sy, 90, outline=WHITE, width=7, alpha=a)
    fr.line(sx, sy - 90, sx, sy - 112, WHITE, 8, a)
    sw = (t - ti) * 900 if t > ti else 0
    fr.line(sx, sy, sx + 70 * math.sin(math.radians(sw)), sy - 70 * math.cos(math.radians(sw)), ACID, 6, a)
    ktext(fr, "almost instantly", MD(48), DIM, CX, 1560, t, times=times_of(c, ["almost", "instantly"]))

def bolt(fr, x0, y0, x1, y1, color, alpha, seed=0, n=7, amp=30, width=6):
    import random
    rnd = random.Random(seed)
    pts = []
    for k in range(n + 1):
        f = k / n
        off = 0 if k in (0, n) else rnd.uniform(-amp, amp)
        pts.append((lerp(x0, x1, f), lerp(y0, y1, f) + off))
    for a, b in zip(pts, pts[1:]):
        fr.line(a[0], a[1], b[0], b[1], color, width, alpha)

def v_sour(fr, t, s0, s1):
    c = 7
    ta = T(c, "acid")
    # acid drops raining from the top
    for k in range(10):
        ph = ((t - ta) * 0.9 + k / 10) % 1.0
        x = 200 + (k * 73) % 680
        fr.circle(x, lerp(420, 800, ph), 10, fill=ACID, alpha=ein(t, ta - 0.2, 0.4) * (1 - ph))
    tl = T(c, "lights")
    lit = ein(t, tl, 0.3)
    for i in range(4):
        x = CX - 300 + i * 200
        fr.rrect_outline(x - 70, 830, x + 70, 1110, 50, WHITE, 6, 1)
        fr.rect(x - 64, 836, x + 64, 1104, ACID, lit * (0.55 + 0.25 * math.sin(t * 7 + i)), radius=46)
    ktext(fr, "sour taste cells", BD(64), WHITE, CX, 1200, t, times=times_of(c, ["sour", "taste", "cells"]))
    tp = T(c, "pain")
    pa = ein(t, tp - 0.15, 0.3)
    flick = 0.6 + 0.4 * abs(math.sin(t * 13))
    bolt(fr, 160, 1360, 920, 1360, WHITE, pa * flick, seed=int(t * 10) % 5, n=9, amp=40, width=7)
    ktext(fr, "+ pain nerves", BD(64), WHITE, CX, 1520, t, times=times_of(c, ["pokes", "pain", "nerves"]))

def v_making(fr, t, s0, s1):
    c = 8
    ktext(fr, "Your mouth is literally making", BD(70), WHITE, CX, 780, t, maxw=880, lh=86,
          times=times_of(c, ["so", "is", "literally", "your", "mouth"]))
    ta = T(c, "acid")
    p = eback(t, ta - 0.15, 0.5)
    stext(fr, "acid.", XB(220), ACID, CX, 1100, alpha=ein(t, ta - 0.2, 0.2), dy=(1 - clamp(p)) * 50)

def v_hurt(fr, t, s0, s1):
    c = 8
    stext(fr, "acid", XB(100), ACID, CX, 620, alpha=1)
    th = T(c, "hurting")
    p = ein(t, th - 0.1, 0.9)
    r = 230
    fr.arc(CX, 900, r, 30, 30 + 300 * p, WHITE, 8, 1)
    if p > 0.05:
        an = math.radians(30 + 300 * p)
        x, y = CX + r * math.sin(an), 900 - r * math.cos(an)
        tx, ty = math.cos(an), math.sin(an)
        arrow(fr, x - tx * 30, y - ty * 30, x + tx * 12, y + ty * 12, WHITE, 8, 36)
    stext(fr, "you", XB(100), WHITE, CX, 1180, alpha=1)
    ktext(fr, "...then hurting itself with it.", BD(70), WHITE, CX, 1450, t, maxw=860, lh=86,
          times=times_of(c, ["then", "hurting", "itself", "with", "it"]))

def v_weirder(fr, t, s0, s1):
    c = 9
    tw = T(c, "weirder")
    ktext(fr, "But it gets", BD(80), DIM, CX, 820, t, times=times_of(c, ["but", "it", "gets"]))
    p = eback(t, tw - 0.12, 0.45)
    sh = 6 * math.sin(t * 50) * fout(t, tw + 0.3, 0.4) if t > tw else 0
    stext(fr, "weirder.", XB(190), WHITE, CX + sh, 1020, alpha=ein(t, tw - 0.15, 0.2), dy=(1 - clamp(p)) * 40)

def v_mountain(fr, t, s0, s1):
    c = 10
    a = ein(t, T(c, "mountain") - 0.15, 0.5)
    fr.line(140, 1000, 470, 520, WHITE, 8, a)
    fr.line(470, 520, 640, 760, WHITE, 8, a)
    fr.line(640, 760, 740, 640, WHITE, 8, a)
    fr.line(740, 640, 940, 1000, WHITE, 8, a)
    cl = ein(t, T(c, "climbers") - 0.1, 1.5)
    fr.circle(lerp(220, 430, cl), lerp(890, 590, cl), 16, fill=WHITE, alpha=ein(t, T(c, "climbers") - 0.1, 0.3))
    tp = T(c, "pill")
    pa = ein(t, tp - 0.1, 0.35)
    ps = clamp(eback(t, tp - 0.1, 0.5))
    px, py = CX, 1200
    fr.rect(px - 110 * ps, py - 42 * ps, px, py + 42 * ps, WHITE, pa, radius=42 * ps)
    fr.rect(px, py - 42 * ps, px + 110 * ps, py + 42 * ps, DIM, pa, radius=42 * ps)
    ktext(fr, "for altitude sickness", MD(46), DIM, CX, 1330, t, times=times_of(c, ["for", "altitude", "sickness"]))
    tb = T(c, "blocks")
    ea = ein(t, tb - 0.1, 0.3)
    enzyme(fr, CX, 1520, 52, alpha=ea, mouth=50)
    cross(fr, CX, 1520, 70, ein(t, T(c, "enzyme") - 0.2, 0.4), WHITE, 1.0, 10)
    ktext(fr, "blocks that exact enzyme", BD(56), WHITE, CX, 1660, t, times=times_of(c, ["blocks", "that", "exact", "enzyme"]))

def v_flat(fr, t, s0, s1):
    c = 11
    items = [("soda", CX - 280), ("beer", CX), ("champagne", CX + 280)]
    for lab, x in items:
        t0 = T(c, lab)
        a = ein(t, t0 - 0.15, 0.35)
        glass(fr, x, 760, 170, 250, alpha=a, liquid=(60, 60, 60))
        stext(fr, lab, SB(42), WHITE, x, 950, alpha=a)
    tf = T(c, "flat")
    p = eback(t, tf - 0.12, 0.45)
    stext(fr, "FLAT.", XB(200), WHITE, CX, 1270, alpha=ein(t, tf - 0.15, 0.2), dy=(1 - clamp(p)) * 40)
    ktext(fr, "and suddenly...", MD(50), DIM, CX, 480, t, times=times_of(c, ["and", "suddenly"]))

def v_blues(fr, t, s0, s1):
    c = 11
    ktext(fr, "Doctors actually named it", MD(54), DIM, CX, 700, t, times=times_of(c, ["doctors", "actually", "named", "it"]))
    tc = T(c, "champagne", 2)
    ktext(fr, "the champagne blues.", XB(104), WHITE, CX, 960, t, maxw=860, lh=120,
          times=[T(c, "the"), tc, T(c, "blues")], dur=0.35)
    glass(fr, CX, 1380, 170, 250, alpha=ein(t, tc, 0.4), liquid=(60, 60, 60))
    stext(fr, "— Am J Med, 1988", MD(36), NOTE, CX, 1620, alpha=ein(t, T(c, "blues"), 0.5))

def v_still(fr, t, s0, s1):
    c = 12
    a = ein(t, s0 + 0.05, 0.3)
    glass(fr, CX, 800, 380, 520, alpha=a, liquid=(60, 60, 60))
    bubbles(fr, CX - 130, CX + 130, 1030, 640, t, n=18, color=WHITE, alpha=ein(t, T(c, "bubbles") - 0.1, 0.4))
    ktext(fr, "Still fizzing in the glass.", BD(70), WHITE, CX, 1300, t, maxw=860, lh=86,
          times=times_of(c, ["still", "fizzing", "in", "the", "glass"]))

def v_matter(fr, t, s0, s1):
    c = 12
    glass(fr, CX, 800, 380, 520, alpha=1, liquid=(60, 60, 60))
    dimp = ein(t, T(c, "stopped"), 0.5)
    col = (int(lerp(255, 90, dimp)),) * 3
    bubbles(fr, CX - 130, CX + 130, 1030, 640, t, n=18, color=col, alpha=1, speed=lerp(1, 0.4, dimp))
    ktext(fr, "They just stopped mattering.", XB(84), WHITE, CX, 1350, t, maxw=860, lh=100,
          times=times_of(c, ["they", "just", "stopped", "mattering"]))

def v_help(fr, t, s0, s1):
    c = 13
    ktext(fr, "Bubbles do help a little.", BD(70), WHITE, CX, 520, t, maxw=860,
          times=times_of(c, ["bubbles", "do", "help", "a", "little"]))
    tongue(fr, CX, 820, alpha=1)
    td = T(c, "drag")
    for k in range(6):
        ph = ((t - td) * 0.5 + k / 6) % 1.0
        an = math.radians(lerp(-70, 70, ph))
        x = CX + 420 * math.sin(an); y = 1080 - 420 * math.cos(an) - 50
        aa = ein(t, td - 0.1, 0.4) * min(1, ph * 5, (1 - ph) * 5)
        fr.circle(x, y, 20, outline=WHITE, width=4, alpha=aa)
        fr.circle(x - 34 * math.cos(an), y - 34 * math.sin(an), 9, fill=ACID, alpha=aa)
    ktext(fr, "dragging the acid around", MD(50), DIM, CX, 1240, t, times=times_of(c, ["drag", "the", "acid", "around"]))
    tb = T(c, "bite")
    # bite meter
    fr.rect(190, 1420, 890, 1490, (40, 40, 40), 1, radius=35)
    fill = lerp(0.72, 0.9, ein(t, T(c, "stronger") - 0.2, 0.6))
    bw = 700 * fill * ein(t, tb - 0.4, 0.5)
    if bw > 4: fr.rect(190, 1420, 190 + bw, 1490, ACID, 1, radius=35)
    stext(fr, "bite", MD(40), DIM, CX, 1550, alpha=ein(t, tb - 0.4, 0.4))

def v_sidekick(fr, t, s0, s1):
    c = 14
    ts = T(c, "sidekick")
    a1 = ein(t, ts - 0.15, 0.35)
    bubbles(fr, CX - 330, CX - 170, 900, 660, t, n=5, rmin=8, rmax=14, alpha=a1)
    stext(fr, "bubbles", SB(44), DIM, CX - 250, 960, alpha=a1)
    stext(fr, "sidekick", BD(60), WHITE, CX - 250, 1060, alpha=a1)
    tst = T(c, "star")
    a2 = ein(t, tst - 0.15, 0.3)
    sc = clamp(eback(t, tst - 0.15, 0.5))
    pts = []
    for k in range(10):
        r = (120 if k % 2 == 0 else 50) * sc
        an = math.radians(k * 36)
        pts.append((CX + 250 + r * math.sin(an), 780 - r * math.cos(an)))
    if sc > 0.02: fr.poly(pts, ACID, a2)
    stext(fr, "acid", SB(44), ACID, CX + 250, 960, alpha=a2)
    stext(fr, "star", BD(60), WHITE, CX + 250, 1060, alpha=a2)
    ktext(fr, "Sidekick, not the star.", XB(84), WHITE, CX, 1350, t, maxw=860,
          times=times_of(c, ["sidekick", "not", "the", "star"]))

def v_can(fr, t, s0, s1):
    c = 15
    tc = T(c, "crack")
    can(fr, CX, 820, 1.3, alpha=ein(t, s0 + 0.05, 0.3), opened=ein(t, tc, 0.25))
    if t > tc:
        bubbles(fr, CX - 100, CX + 100, 560, 380, t, n=8, rmin=5, rmax=10, alpha=ein(t, tc, 0.3))
    ktext(fr, "So next time you crack open a can...", BD(70), WHITE, CX, 1300, t, maxw=860, lh=86,
          times=times_of(c, ["so", "next", "time", "you", "crack", "open", "a", "can"]))

def v_remember(fr, t, s0, s1):
    c = 15
    tj = T(c, "just")
    ktext(fr, "just remember.", XB(120), WHITE, CX, 960, t, times=[tj, T(c, "remember")], dur=0.35)
    glass(fr, CX, 1380, 200, 290, alpha=ein(t, tj, 0.4), liquid=pc(ACID, 0.35))
    bubbles(fr, CX - 60, CX + 60, 1490, 1270, t, n=8, rmin=5, rmax=10, color=ACID)

def W_(c, w, occ=1, lead=0.2):
    return T(c, w, occ) - lead

SC = [
    (v_hook, 0.0), (v_myth, boundary(1)), (v_nope, boundary(2)), (v_chamber, W_(2, "pressure", lead=0.25)),
    (v_same, boundary(3)), (v_insane, boundary(4)), (v_enzyme, boundary(5)), (v_grab, boundary(6)),
    (v_snap, W_(6, "and", lead=0.12)), (v_sour, boundary(7)), (v_making, boundary(8)), (v_hurt, W_(8, "then", lead=0.3)),
    (v_weirder, boundary(9)), (v_mountain, boundary(10)), (v_flat, boundary(11)), (v_blues, W_(11, "doctors", lead=0.45)),
    (v_still, boundary(12)), (v_matter, W_(12, "they", lead=0.3)), (v_help, boundary(13)), (v_sidekick, boundary(14)),
    (v_can, boundary(15)), (v_remember, W_(15, "just", lead=0.35)),
]
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
    f = clamp((s1 - t) / 0.18) if i < len(SC) - 1 else clamp((TOTAL - t) / 1.0)
    if i > 0:
        f = min(f, clamp((t - s0) / 0.1))
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
