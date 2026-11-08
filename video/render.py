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

# ============================================================ SCENES: belly button lint =====
import random

SKIN = (38, 38, 38)
HOLE = (12, 12, 12)

def wt(c, i0, n):
    """start times of words i0..i0+n-1 in chunk c"""
    return [CHW[c][i]["s"] for i in range(i0, i0 + n)]

def cut(c, key, occ=1):
    return T(c, key, occ) - 0.12

def wavy(cx0, cy0, cx1, cy1, amp=10, waves=3, n=24, phase=0.0):
    L = math.hypot(cx1 - cx0, cy1 - cy0) or 1
    ux, uy = (cx1 - cx0) / L, (cy1 - cy0) / L
    px, py = -uy, ux
    pts = []
    for i in range(n + 1):
        s = i / n
        o = amp * math.sin(s * waves * 2 * math.pi + phase)
        pts.append((cx0 + ux * L * s + px * o, cy0 + uy * L * s + py * o))
    return pts

def polyline(fr, pts, color, width=4, alpha=1.0):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        fr.line(x1, y1, x2, y2, color, width, alpha, cap=True)

def navel(fr, cx, cy, r, alpha=1.0):
    if alpha <= 0.004:
        return
    fr.circle(cx, cy, r * 1.55, fill=SKIN, alpha=alpha * 0.55)
    fr.circle(cx, cy, r, fill=HOLE, alpha=1.0 if alpha > 0.5 else alpha * 2)
    fr.circle(cx, cy, r, outline=WHITE, width=max(3, r * 0.06), alpha=alpha * 0.9)
    fr.arc(cx, cy, r * 0.62, 200, 340, DIM, width=max(2, r * 0.05), alpha=alpha * 0.8)

def hair_ring(fr, cx, cy, R, n, grow=1.0, alpha=1.0, color=DIM, length=46, width=4, rot=0.0):
    if grow <= 0.01 or alpha <= 0.004:
        return
    for k in range(n):
        a = math.radians(rot + k * 360 / n)
        x0, y0 = cx + R * math.cos(a), cy + R * math.sin(a)
        # hair lies tangent-ish, swirling around the navel
        ta = a + math.radians(90 + 20)
        L = length * grow
        x1, y1 = x0 + L * math.cos(ta), y0 + L * math.sin(ta)
        fr.line(x0, y0, x1, y1, color, width, alpha)

def hairs(fr, cx, cy, t, grow=1.0, alpha=1.0, rings=(170, 250, 330), spin=6.0):
    for i, R in enumerate(rings):
        hair_ring(fr, cx, cy, R, 14 + i * 6, grow=grow, alpha=alpha, rot=t * spin + i * 11)

def spiral_fibers(fr, cx, cy, t, t0, n=7, R0=470, period=2.4, alpha=1.0, color=LINT, width=5):
    """fibers spiral inward into the navel"""
    if alpha <= 0.004:
        return
    tt = t - t0
    for k in range(n):
        ph = (tt / period + k / n) % 1.0
        pts = []
        for j in range(14):
            p = clamp(ph - j * 0.018)
            r = R0 * (1 - p) ** 0.9 + 18
            ang = k * 2 * math.pi / n + p * 3.4 * math.pi
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        a = alpha * clamp(ph * 5) * clamp((1 - ph) * 6)
        polyline(fr, pts, color, width, a)

_LB = {}
def lint_ball(fr, cx, cy, r, alpha=1.0, seed=3, n=40, wob=0.0):
    if alpha <= 0.004:
        return
    if seed not in _LB:
        rnd = random.Random(seed)
        segs = []
        for _ in range(n):
            a = rnd.uniform(0, 2 * math.pi); d = rnd.uniform(0, 0.75) ** 0.7
            b = rnd.uniform(0, 2 * math.pi); L = rnd.uniform(0.35, 0.8)
            segs.append((a, d, b, L, rnd.uniform(0, 6.28), rnd.choice([LINT, LINT, LINT, DIM])))
        _LB[seed] = segs
    for (a, d, b, L, ph, col) in _LB[seed]:
        x = cx + r * d * math.cos(a); y = cy + r * d * math.sin(a)
        x0, y0 = x - r * L / 2 * math.cos(b), y - r * L / 2 * math.sin(b)
        x1, y1 = x + r * L / 2 * math.cos(b), y + r * L / 2 * math.sin(b)
        pts = wavy(x0, y0, x1, y1, amp=r * 0.05, waves=1.5, n=8, phase=ph + wob)
        polyline(fr, pts, col, max(2, r * 0.025), alpha * (0.9 if col == LINT else 0.6))

def microbe(fr, x, y, s, ang, alpha=1.0, color=LINT, kind=0):
    if alpha <= 0.004:
        return
    if kind == 0:   # rod
        dx, dy = s * math.cos(ang), s * math.sin(ang)
        fr.line(x - dx, y - dy, x + dx, y + dy, color, s * 0.9, alpha, cap=True)
    elif kind == 1:  # coccus cluster
        for k in range(3):
            a = ang + k * 2.1
            fr.circle(x + s * 0.5 * math.cos(a), y + s * 0.5 * math.sin(a), s * 0.45, fill=color, alpha=alpha)
    else:  # spiral
        pts = wavy(x - s * 1.4 * math.cos(ang), y - s * 1.4 * math.sin(ang),
                   x + s * 1.4 * math.cos(ang), y + s * 1.4 * math.sin(ang), amp=s * 0.35, waves=2, n=14)
        polyline(fr, pts, color, s * 0.3, alpha)

_SW = {}
def swarm(fr, cx, cy, R, t, n, appear=1.0, alpha=1.0, seed=7, size=14, color=LINT):
    if seed not in _SW:
        rnd = random.Random(seed)
        _SW[seed] = [(rnd.uniform(0, 6.28), rnd.uniform(0.08, 1) ** 0.5, rnd.uniform(0, 6.28),
                      rnd.randint(0, 2), rnd.uniform(0.6, 1.3), rnd.uniform(0, 1)) for _ in range(400)]
    m = int(n * clamp(appear))
    for (a, d, ang, kind, sz, ph) in _SW[seed][:m]:
        aa = a + 0.08 * math.sin(t * 1.3 + ph * 6)
        x = cx + R * d * math.cos(aa); y = cy + R * d * math.sin(aa) * 0.95
        microbe(fr, x, y, size * sz, ang + t * 0.6 * (ph - 0.5), alpha, color, kind)

def scaled_hair(fr, cx, y0, y1, w, t, alpha=1.0, hooks=0.0):
    """magnified hair shaft with overlapping cuticle scales"""
    fr.rect(cx - w / 2, y0, cx + w / 2, y1, (60, 60, 60), alpha, radius=w / 2)
    step = w * 0.55
    y = y1 - step
    while y > y0 + step * 0.5:
        fr.line(cx - w / 2 + 6, y + step * 0.45, cx, y - step * 0.05, WHITE, 4, alpha * 0.85)
        fr.line(cx, y - step * 0.05, cx + w / 2 - 6, y + step * 0.45, WHITE, 4, alpha * 0.85)
        if hooks > 0.01:
            L = 34 * hooks
            for sgn in (-1, 1):
                ex = cx + sgn * w / 2
                fr.line(ex - sgn * 4, y + step * 0.42, ex + sgn * L * 0.8, y + step * 0.42 - L * 0.7, LINT, 5, alpha * hooks)
        y -= step

def flask(fr, cx, cy, s, alpha=1.0):
    neck_w, neck_h, body = 40 * s, 90 * s, 150 * s
    top = cy - neck_h - body * 0.5
    pts = [(cx - neck_w / 2, top), (cx - neck_w / 2, top + neck_h), (cx - body * 0.9, cy + body * 0.5),
           (cx + body * 0.9, cy + body * 0.5), (cx + neck_w / 2, top + neck_h), (cx + neck_w / 2, top)]
    for p, q in zip(pts, pts[1:]):
        fr.line(p[0], p[1], q[0], q[1], WHITE, 7, alpha)
    fr.line(cx - body * 0.9, cy + body * 0.5, cx + body * 0.9, cy + body * 0.5, WHITE, 7, alpha)
    fr.line(cx - neck_w * 0.9, top, cx + neck_w * 0.9, top, WHITE, 7, alpha)

# ---------------------------------------------------------------- scenes
def v_hook(fr, t, s0, s1):
    c = 0
    ny = 1380
    navel(fr, CX, ny, 105, alpha=1.0)
    hairs(fr, CX, ny, t, grow=1.0, alpha=0.9, rings=(170, 250, 330, 410))
    spiral_fibers(fr, CX, ny, t, -2.0, n=11, R0=520, period=2.0, width=7)
    times = wt(c, 0, 7)
    times = [-0.3 if i == 0 else x for i, x in enumerate(times)]
    ktext(fr, "Your belly hair is harvesting your shirt,", XB(124), WHITE, CX, 620, t,
          times=times, maxw=960, lh=140, dur=0.22, rise=30)

def v_onefiber(fr, t, s0, s1):
    c = 0
    ny = 1150
    navel(fr, CX, ny, 92)
    hairs(fr, CX, ny, t, alpha=0.6, rings=(150, 220, 290))
    # a single long fiber gets reeled in
    p = ein(t, s0, 1.6)
    x0 = lerp(CX - 470, CX - 40, p)
    pts = wavy(x0 - 300, ny - 330 + p * 300, CX - 10, ny, amp=18, waves=3, n=40, phase=t * 4)
    polyline(fr, pts, LINT, 7, 1.0)
    ktext(fr, "One fiber at a time.", XB(96), WHITE, CX, 560, t, times=wt(c, 7, 5), maxw=900, lh=112)

def v_lint(fr, t, s0, s1):
    c = 1
    pb = eback(t, s0 + 0.05, 0.6)
    lint_ball(fr, CX, 1050, 230 * (0.5 + 0.5 * clamp(pb)), alpha=ein(t, s0, 0.4), wob=t * 0.8)
    ktext(fr, "That lint in your belly button?", BD(70), WHITE, CX, 560, t, times=wt(c, 0, 6), maxw=880, lh=86)
    tn = T(c, "not")
    p = eback(t, tn - 0.05, 0.5)
    stext(fr, "Not random.", XB(110), LINT, CX, 1480, alpha=ein(t, tn - 0.08, 0.25), dy=(1 - clamp(p)) * 40)

def v_chemist(fr, t, s0, s1):
    c = 2
    a = ein(t, s0, 0.4)
    flask(fr, CX, 980, 1.3 * (0.7 + 0.3 * eback(t, s0, 0.6)), alpha=a)
    for k in range(4):
        ph = ((t - s0) * 0.7 + k / 4) % 1
        fr.circle(CX - 40 + k * 26, 1010 - ph * 160, 10 + 6 * ph, outline=LINT, width=4, alpha=a * (1 - ph))
    ktext(fr, "A chemist in Vienna", XB(86), WHITE, CX, 560, t, times=wt(c, 0, 4), maxw=900, lh=100)
    stext(fr, "Vienna University of Technology", MD(42), DIM, CX, 1330, alpha=ein(t, T(c, "vienna"), 0.4))

def v_503(fr, t, s0, s1):
    c = 2
    t5, te = T(c, "five"), T(c, "lint", end=True)
    n = int(round(503 * ein(t, t5, te - t5 - 0.2)))
    stext(fr, f"{n}", XB(300), LINT, CX, 820, alpha=ein(t, t5 - 0.1, 0.25), tnum=True)
    ktext(fr, "pieces of navel lint", BD(72), WHITE, CX, 1080, t, times=wt(c, 9, 4), maxw=900)
    # pile of tiny lint balls
    m = int(30 * ein(t, t5, 1.8))
    rnd = random.Random(11)
    for k in range(30):
        x = CX + rnd.uniform(-380, 380); y = 1400 + rnd.uniform(-90, 90)
        if k < m:
            lint_ball(fr, x, y, 34, alpha=0.9, seed=100 + (k % 6), n=12)

def v_3years(fr, t, s0, s1):
    c = 2
    ktext(fr, "Over three years.", XB(96), WHITE, CX, 600, t, times=wt(c, 13, 3), maxw=900)
    for k in range(3):
        t0 = T(c, "three", 2) + k * 0.18
        a = ein(t, t0, 0.35); sc = eback(t, t0, 0.5)
        x = CX + (k - 1) * 280; y = 1080
        hw = 110 * clamp(sc, 0, 1.2)
        fr.rrect_outline(x - hw, y - hw, x + hw, y + hw, 22, WHITE, 6, a)
        fr.rect(x - hw, y - hw, x + hw, y - hw * 0.55, WHITE, a * 0.9, radius=10)
        lint_ball(fr, x, y + 25, 50, alpha=a, seed=200 + k, n=14)

def v_cotton(fr, t, s0, s1):
    c = 3
    ktext(fr, "Mostly cotton fibers from clothes", XB(84), WHITE, CX, 560, t, times=wt(c, 0, 5), maxw=900, lh=100)
    for k in range(9):
        t0 = T(c, "cotton") + k * 0.08
        p = ein(t, t0, 0.7)
        y = 920 + k * 62
        x1 = lerp(CX - 420, CX + 420, p)
        pts = wavy(CX - 420, y, x1, y, amp=10, waves=4 * p + 0.01, n=30, phase=t * 3 + k)
        polyline(fr, pts, LINT, 6, ein(t, t0, 0.3))

def v_mix(fr, t, s0, s1):
    c = 3
    lint_ball(fr, CX, 760, 190, alpha=1.0, seed=3, wob=t)
    stext(fr, "+", XB(80), DIM, CX, 1040, alpha=ein(t, T(c, "mixed") - 0.05, 0.3))
    items = [("dead skin", "dead"), ("sweat", "sweat"), ("fat", "fat"), ("dust", "dust")]
    for i, (lab, key) in enumerate(items):
        t0 = T(c, key) - 0.06
        p = ein(t, t0, 0.35)
        x = CX + (-1 if i % 2 == 0 else 1) * 220
        y = 1220 + (i // 2) * 160
        stext(fr, lab, BD(70), WHITE, x, y, alpha=p, dy=(1 - p) * 22)

def v_insane(fr, t, s0, s1):
    c = 4
    p = eback(t, T(c, "insane") - 0.1, 0.5)
    fl = clamp(1 - (t - T(c, "insane")) / 0.35) if t > T(c, "insane") else 0
    fr.rect(0, 0, W, H, LINT, fl * 0.18)
    ktext(fr, "Here's the", BD(80), WHITE, CX, 760, t, times=wt(c, 0, 2), maxw=900)
    stext(fr, "INSANE", XB(int(190 * clamp(p, 0.3, 1.15))), LINT, CX, 960, alpha=ein(t, T(c, "insane") - 0.1, 0.2))
    ktext(fr, "part.", BD(80), WHITE, CX, 1160, t, times=wt(c, 3, 1), maxw=900)

def v_scales(fr, t, s0, s1):
    c = 4
    a = ein(t, s0, 0.4)
    zoom = lerp(0.6, 1.0, ein(t, s0, 1.2))
    scaled_hair(fr, CX, 1100 - 450 * zoom, 1750, 150 * zoom, t, alpha=a)
    ktext(fr, "Belly hair is covered in tiny scales", BD(66), WHITE, CX, 470, t, times=wt(c, 4, 7), maxw=900, lh=82)
    stext(fr, "magnified", MD(38), NOTE, CX + 110, 1300, alpha=a * 0.9, align="l")

def v_hooks(fr, t, s0, s1):
    c = 4
    hk = eback(t, T(c, "barbed") - 0.05, 0.5)
    scaled_hair(fr, CX, 650, 1750, 150, t, alpha=1.0, hooks=clamp(hk, 0, 1.1))
    ktext(fr, "like barbed hooks.", XB(90), WHITE, CX, 470, t, times=wt(c, 13, 3), maxw=900)

def v_snag(fr, t, s0, s1):
    c = 5
    # hair horizontal-ish rows; fibers drift across and snag
    for r in range(3):
        y = 980 + r * 170
        fr.line(CX - 420, y + 30, CX + 420, y - 30, DIM, 8, 0.9)
        for k in range(10):
            x = CX - 400 + k * 88
            yy = y + 30 - (x - (CX - 420)) / 840 * 60
            fr.line(x, yy, x - 18, yy - 18, WHITE, 3, 0.7)
    ts = T(c, "snag")
    for k in range(6):
        t0 = ts - 0.6 + k * 0.22
        p = ein(t, t0, 0.8)
        y = 900 + k * 95
        x = lerp(CX + 600, CX - 160 + k * 60, p)
        pts = wavy(x, y - 40, x + 260, y + 60, amp=12, waves=2.5, n=24, phase=t * 3 + k)
        polyline(fr, pts, LINT, 6, ein(t, t0, 0.2))
    ktext(fr, "Every time you move,", BD(70), WHITE, CX, 470, t, times=wt(c, 0, 4), maxw=900)
    sp = eback(t, ts - 0.05, 0.45)
    stext(fr, "SNAG.", XB(int(140 * clamp(sp, 0.3, 1.15))), LINT, CX, 640, alpha=ein(t, ts - 0.08, 0.2))

def v_circles(fr, t, s0, s1):
    c = 6
    ny = 1120
    navel(fr, CX, ny, 80, alpha=ein(t, s0, 0.3))
    for i, R in enumerate((150, 230, 310, 390)):
        g = ein(t, T(c, "circles") - 0.6 + i * 0.15, 0.6)
        hair_ring(fr, CX, ny, R, 14 + i * 6, grow=g, alpha=0.95, color=WHITE if i % 2 else DIM, rot=t * 10 + i * 9)
    ktext(fr, "Belly hair often grows in circles", BD(70), WHITE, CX, 470, t, times=wt(c, 1, 6), maxw=900, lh=86)

def v_funnel(fr, t, s0, s1):
    c = 6
    ny = 1120
    navel(fr, CX, ny, 80)
    for i, R in enumerate((150, 230, 310, 390)):
        hair_ring(fr, CX, ny, R, 14 + i * 6, grow=1, alpha=0.6, color=DIM, rot=t * 10 + i * 9)
    spiral_fibers(fr, CX, ny, t, s0 - 1.5, n=12, R0=520, period=1.5, width=6)
    ktext(fr, "so it funnels everything into the hole.", XB(76), WHITE, CX, 470, t, times=wt(c, 10, 7), maxw=920, lh=90)

def v_shave(fr, t, s0, s1):
    c = 7
    ny = 1100
    navel(fr, CX, ny, 80)
    tsh = T(c, "shaved")
    p = ein(t, tsh, 0.9)
    # razor sweep
    rx = lerp(CX - 520, CX + 520, p)
    hairs(fr, CX, ny, t, grow=1 - p, alpha=0.9, rings=(150, 230, 310))
    if 0.01 < p < 0.99:
        fr.rect(rx - 14, ny - 420, rx + 14, ny + 420, WHITE, 0.9, radius=8)
    ktext(fr, "He shaved his stomach.", BD(72), WHITE, CX, 470, t, times=wt(c, 1, 4), maxw=900)
    # lint meter
    tst = T(c, "stopped")
    lvl = 1 - 0.95 * ein(t, T(c, "lint") - 0.1, 0.9)
    fr.rrect_outline(CX - 360, 1620, CX + 360, 1680, 30, DIM, 4, 1)
    fr.rect(CX - 352, 1628, CX - 352 + 704 * lvl, 1672, LINT, 1, radius=22)
    stext(fr, "lint", MD(40), DIM, CX - 360, 1570, align="l")
    stext(fr, "basically stopped", BD(56), WHITE, CX, 1760, alpha=ein(t, tst - 0.1, 0.3))

def v_regrow(fr, t, s0, s1):
    c = 7
    ny = 1100
    navel(fr, CX, ny, 80)
    g = ein(t, T(c, "grew") - 0.2, 0.6)
    hairs(fr, CX, ny, t, grow=g, alpha=0.9, rings=(150, 230, 310))
    spiral_fibers(fr, CX, ny, t, T(c, "back"), n=6, R0=440, period=1.6, alpha=g)
    ktext(fr, "Until the hair grew back.", XB(80), WHITE, CX, 470, t, times=wt(c, 9, 5), maxw=900)

def v_worse(fr, t, s0, s1):
    c = 8
    tw = T(c, "worse")
    p = eback(t, tw - 0.1, 0.5)
    ktext(fr, "But it gets", BD(84), WHITE, CX, 820, t, times=wt(c, 0, 3), maxw=900)
    stext(fr, "WORSE.", XB(int(200 * clamp(p, 0.3, 1.15))), LINT, CX, 1040, alpha=ein(t, tw - 0.1, 0.2))
    swarm(fr, CX, 1040, 520, t, 60, appear=ein(t, tw, 0.8), alpha=0.35, seed=5, size=12)

def v_scrub(fr, t, s0, s1):
    c = 8
    ny = 1150
    navel(fr, CX, ny, 120)
    # water droplets slide past around the navel, never into it
    for k in range(14):
        ph = ((t - s0) * 0.9 + k / 14) % 1
        side = -1 if k % 2 else 1
        x = CX + side * (200 + (k * 37) % 200)
        y = 700 + ph * 1000
        fr.circle(x, y, 12, fill=DIM, alpha=0.7 * (1 - ph))
    swarm(fr, CX, ny, 100, t, 30, appear=ein(t, T(c, "nobody"), 0.6), alpha=1, seed=9, size=10)
    ktext(fr, "The one spot almost nobody scrubs.", XB(78), WHITE, CX, 470, t, times=[T(c, "the")] + wt(c, 4, 5), maxw=900, lh=92)

def v_swab(fr, t, s0, s1):
    c = 9
    t0 = T(c, "sixty")
    for k in range(60):
        r_, col = divmod(k, 6)
        x = CX + (col - 2.5) * 140; y = 760 + r_ * 100
        a = ein(t, t0 - 0.3 + k * 0.012, 0.25)
        fr.circle(x, y, 30, fill=HOLE, alpha=a)
        fr.circle(x, y, 30, outline=WHITE, width=3, alpha=a)
    ktext(fr, "60 belly buttons swabbed", XB(84), WHITE, CX, 470, t, t0=s0 + 0.05, maxw=900, lh=96)

def v_2368(fr, t, s0, s1):
    c = 9
    t2, te = T(c, "two"), T(c, "eight", end=True)
    n = int(round(2368 * ein(t, t2, te - t2)))
    stext(fr, f"{n:,}", XB(250), LINT, CX, 700, alpha=ein(t, t2 - 0.1, 0.2), tnum=True)
    ktext(fr, "kinds of bacteria", BD(80), WHITE, CX, 920, t, times=wt(c, 14, 3), maxw=900)
    swarm(fr, CX, 1380, 380, t, 220, appear=ein(t, t2, te - t2), alpha=0.95, seed=7, size=13)

def v_new(fr, t, s0, s1):
    c = 10
    stext(fr, "~1,400", XB(230), LINT, CX, 700, alpha=ein(t, T(c, "fourteen") - 0.1, 0.25), tnum=True)
    ktext(fr, "might be new to science.", BD(76), WHITE, CX, 920, t, times=wt(c, 3, 5), maxw=900)
    swarm(fr, CX, 1380, 380, t, 220, alpha=0.35, seed=7, size=13)
    rnd = random.Random(4)
    for k in range(10):
        x = CX + rnd.uniform(-340, 340); y = 1380 + rnd.uniform(-300, 300)
        a = ein(t, T(c, "new") + k * 0.06, 0.3)
        stext(fr, "?", XB(70), WHITE, x, y, alpha=a)

def v_japan(fr, t, s0, s1):
    c = 11
    a = ein(t, T(c, "microbe") - 0.1, 0.4)
    sc = 0.6 + 0.4 * clamp(eback(t, T(c, "microbe") - 0.1, 0.6))
    glow_dot(fr, CX, 1050, 10, LINT, alpha=a * 0.6, glow=0.5, glow_r=120)
    microbe(fr, CX, 1050, 120 * sc, math.radians(-20 + 6 * math.sin(t * 1.5)), alpha=a, kind=0)
    for k in range(10):  # flagella
        ang = math.radians(-20) + math.pi + (k - 4.5) * 0.12
        pts = wavy(CX - 120 * sc * math.cos(math.radians(-20)), 1050 + 120 * sc * 0.34,
                   CX - 330 * sc, 1180 + (k - 4.5) * 14, amp=10, waves=2, n=12, phase=t * 6 + k) if k < 3 else []
        if pts:
            polyline(fr, pts, LINT, 4, a * 0.8)
    ktext(fr, "One man carried a microbe", BD(72), WHITE, CX, 470, t, times=wt(c, 0, 5), maxw=900, lh=86)
    tj = T(c, "only")
    stext(fr, "only ever found in", MD(48), DIM, CX, 1400, alpha=ein(t, tj - 0.05, 0.3))
    pj = eback(t, T(c, "japan") - 0.08, 0.45)
    stext(fr, "Japan", XB(int(130 * clamp(pj, 0.3, 1.15))), WHITE, CX, 1530, alpha=ein(t, T(c, "japan") - 0.1, 0.2))

def v_never(fr, t, s0, s1):
    c = 11
    microbe(fr, CX, 1300, 70, math.radians(-20), alpha=0.8, kind=0)
    ktext(fr, "He had never been to Japan.", XB(98), WHITE, CX, 720, t, times=wt(c, 13, 6), maxw=900, lh=114)

def v_jungle(fr, t, s0, s1):
    c = 12
    ta, tb = T(c, "sweater"), T(c, "jungle")
    # sweater: knit of fibers (left)
    a1 = ein(t, ta - 0.1, 0.4)
    for r in range(6):
        y = 1000 + r * 60
        pts = wavy(CX - 440, y, CX - 80, y, amp=14, waves=5, n=40, phase=r)
        polyline(fr, pts, LINT, 6, a1)
    stext(fr, "sweater", BD(56), WHITE, CX - 260, 1460, alpha=a1)
    a2 = ein(t, tb - 0.1, 0.4)
    swarm(fr, CX + 260, 1150, 190, t, 80, appear=a2, alpha=1, seed=13, size=11)
    stext(fr, "jungle", BD(56), WHITE, CX + 260, 1460, alpha=a2)
    ktext(fr, "You're growing a sweater and a jungle.", XB(78), WHITE, CX, 520, t, times=wt(c, 1, 7), maxw=900, lh=92)

def v_remember(fr, t, s0, s1):
    c = 12
    lint_ball(fr, CX, 1150, 200 * hold_pulse(t, 1.4, 0.95, 1.05), alpha=1, seed=3, wob=t)
    ktext(fr, "Next time you find that fuzz,", BD(76), WHITE, CX, 520, t, times=wt(c, 8, 6), maxw=900, lh=90)
    stext(fr, "remember:", XB(96), LINT, CX, 1560, alpha=ein(t, T(c, "remember") - 0.08, 0.3))

def follow_pill(fr, cx, cy, s, alpha):
    if alpha <= 0.004 or s < 0.05:
        return
    w, h = 400 * s, 130 * s
    fr.rrect_outline(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, h / 2, WHITE, 6, alpha)
    px = cx - w / 2 + 80 * s
    fr.line(px - 26 * s, cy, px + 26 * s, cy, WHITE, 8 * s, alpha)
    fr.line(px, cy - 26 * s, px, cy + 26 * s, WHITE, 8 * s, alpha)
    stext(fr, "FOLLOW", XB(int(60 * s)), WHITE, cx + 40 * s, cy, alpha=alpha)

def v_follow(fr, t, s0, s1):
    c = 13
    ktext(fr, "Follow for a new unhinged fact every day.", XB(96), WHITE, CX, 700, t,
          times=wt(c, 0, 8), maxw=920, lh=112)
    p = eback(t, T(c, "follow") + 0.1, 0.6)
    follow_pill(fr, CX, 1180, clamp(p, 0, 1.2) * hold_pulse(t, 1.2, 0.97, 1.03), ein(t, T(c, "follow"), 0.3))
    lint_ball(fr, CX, 1520, 90, alpha=ein(t, s0, 0.5), seed=3, wob=t)

SC = [
    (v_hook, 0.0), (v_onefiber, cut(0, "one")), (v_lint, boundary(1)),
    (v_chemist, boundary(2)), (v_503, cut(2, "five")), (v_3years, cut(2, "over")),
    (v_cotton, boundary(3)), (v_mix, cut(3, "mixed")),
    (v_insane, boundary(4)), (v_scales, cut(4, "belly")), (v_hooks, cut(4, "that")),
    (v_snag, boundary(5)), (v_circles, boundary(6)), (v_funnel, cut(6, "so")),
    (v_shave, boundary(7)), (v_regrow, cut(7, "until")),
    (v_worse, boundary(8)), (v_scrub, cut(8, "that")),
    (v_swab, boundary(9)), (v_2368, cut(9, "they")), (v_new, boundary(10)),
    (v_japan, boundary(11)), (v_never, cut(11, "he")),
    (v_jungle, boundary(12)), (v_remember, cut(12, "next")),
    (v_follow, boundary(13)),
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
    f = clamp((s1 - t) / 0.18) if i < len(SC) - 1 else 1.0   # follow card held to last frame
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
