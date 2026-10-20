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

AUDIO_END = 78.106063        # <-- replace with your audio's real duration (seconds)
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

# ============================================================ EXAMPLE SCENES =====
# Everything below is the radioactive-banana video. It's a complete, shipped
# reference for the PATTERN (one function per scene, timed off T()/boundary(),
# drawn with the primitives above) -- replace the content for your own script.

def banana(fr, cx, cy, size=1.0, angle=0.0, alpha=1.0, color=YELLOW, stem=True):
    """Example of the 'tapered organic band' icon technique from
    design-system.md: sample points along an arc, taper the width toward
    both ends, offset perpendicular for inner/outer boundaries, close into
    one polygon. Adapt this shape-generation approach for a new icon rather
    than reusing the banana itself."""
    if alpha <= 0.004 or size <= 0.01:
        return
    R = 118 * size
    a0, a1 = -68, 68
    Wd = 40 * size
    N = 22
    outer, inner = [], []
    for i in range(N + 1):
        t = i / N
        ang = math.radians(a0 + (a1 - a0) * t)
        wt = Wd * (0.24 + 0.76 * math.sin(math.pi * t) ** 0.6)
        rO, rI = R + wt / 2, R - wt / 2
        outer.append((rO * math.cos(ang), rO * math.sin(ang)))
        inner.append((rI * math.cos(ang), rI * math.sin(ang)))
    poly_local = outer + inner[::-1]
    ar = math.radians(angle)
    ca, sa = math.cos(ar), math.sin(ar)
    poly = [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in poly_local]
    fr.poly(poly, color, alpha)
    if stem:
        ang_tip = math.radians(a1)
        sx, sy = R * math.cos(ang_tip), R * math.sin(ang_tip)
        sx, sy = cx + sx * ca - sy * sa, cy + sx * sa + sy * ca
        fr.circle(sx, sy, Wd * 0.15 * size, fill=PEEL, alpha=alpha)

def trefoil(fr, cx, cy, r, alpha=1.0, color=WHITE, spin=0.0):
    """Example of the 'radial symbol' technique: evenly-spaced pieslice
    wedges with gaps, plus a center circle."""
    if alpha <= 0.004:
        return
    for k in range(3):
        a0 = -30 + k * 120 + spin
        fr.pieslice(cx, cy, r, a0, a0 + 60, color, alpha)
    fr.circle(cx, cy, r * 0.22, fill=BLACK, alpha=1.0)
    fr.circle(cx, cy, r * 0.22, outline=color, width=r * 0.05, alpha=alpha)

def v_hook(fr, t, s0, s1):
    c = 0
    pb = ein(t, s0 + 0.05, 0.5) * eback(t, s0 + 0.05, 0.6)
    pulse_rings(fr, CX, 640, t, T(c, "radioactive", end=True) + 0.15, YELLOW, n=3, period=1.15)
    banana(fr, CX, 640, size=1.35 * (0.6 + 0.4 * clamp(pb)), angle=-8, alpha=ein(t, s0 + 0.05, 0.45))
    ktext(fr, "The banana on your counter is radioactive.", XB(70), WHITE, CX, 990, t, s0 + 0.1, maxw=880, lh=88)
    items = [("Your table", T(c, "kitchen") - 0.1), ("Your soil", T(c, "soil") - 0.15), ("You", T(c, "you", end=False) - 0.1)]
    y = 1430
    n = len(items)
    for i, (label, t0) in enumerate(items):
        x = CX + (i - (n - 1) / 2) * 300
        a = ein(t, t0, 0.4)
        sc = 0.5 + 0.5 * eback(t, t0, 0.5)
        pulse_rings(fr, x, y, t, t0 + 0.1, YELLOW, n=2, period=1.0, r0=14, r1=64, width=3)
        fr.circle(x, y, 20 * clamp(sc), fill=YELLOW, alpha=a)
        stext(fr, label, MD(34), DIM, x, y + 62, alpha=a)

def v_100ns(fr, t, s0, s1):
    """A clean example of a 'big number lands as the narrator finishes
    saying it' beat -- a very common shape for this channel's videos."""
    c = 5
    ba = ein(t, s0 + 0.1, 0.5)
    banana(fr, CX, 560, size=1.15, angle=-10, alpha=ba)
    t100 = T(c, "hundred")
    p = eback(t, t100 - 0.15, 0.6)
    stext(fr, "100", XB(230), WHITE, CX, 860, alpha=ein(t, t100 - 0.2, 0.3), dy=(1 - clamp(p)) * 20, tnum=True)
    stext(fr, "nanosieverts", SB(58), YELLOW, CX, 1050, alpha=ein(t, T(c, "nanosieverts") - 0.05, 0.4))
    ktext(fr, "Tiny, but real.", MD(50), DIM, CX, 1230, t, T(c, "tiny") - 0.1, maxw=820)

def v_compare(fr, t, s0, s1):
    """Example of a scene spanning TWO chunks (6 and 7) because they're one
    continuous idea (a growing comparison chart) -- see production-notes.md
    for when this is worth doing instead of a scene per chunk."""
    c6, c7 = 6, 7
    ktext(fr, "For comparison:", MD(46), DIM, CX, 400, t, s0 + 0.15)
    rows = [
        (T(c6, "chest") - 0.05, "Chest X-ray", 200, 2),
        (T(c6, "transatlantic") - 0.15, "Flight", 400, 4),
        (T(c7, "sleeping") - 0.05, "Sleeping next to someone", 10, 1),
    ]
    y0 = 660
    for i, (t0, label, val, n_icons) in enumerate(rows):
        y = y0 + i * 330
        a = ein(t, t0, 0.4)
        stext(fr, label, SB(42), WHITE, CX, y - 78, alpha=a)
        gx0 = CX - (n_icons - 1) * 72 / 2
        for k in range(n_icons):
            bal = ein(t, t0 + 0.25 + k * 0.12, 0.4)
            banana(fr, gx0 + k * 72, y + 20, size=0.62, angle=-12 + k * 4, alpha=bal)
        va = ein(t, t0 + 0.35 + n_icons * 0.12, 0.4)
        stext(fr, f"{val}", XB(90), YELLOW, CX, y + 118, alpha=va, tnum=True, dy=(1 - va) * 14)
        stext(fr, "bananas", MD(34), DIM, CX, y + 190, alpha=va)

def v_outro(fr, t, s0, s1):
    c = 11
    ktext(fr, "You've been mildly radioactive since the day you were born.",
          XB(66), WHITE, CX, 760, t, s0 + 0.15, maxw=900, lh=84)
    th = T(c, "harmless")
    p = ein(t, th - 0.05, 0.5)
    stext(fr, "Harmless. Constant. Completely normal.", BD(52), YELLOW, CX, 1200, alpha=p, dy=(1 - p) * 18)

# The full banana video has 11 scenes; v_element/v_decay/v_bed/v_pile/v_balance/
# v_flow are omitted here for brevity but follow the exact same pattern as the
# four kept above. Write your own scene per line of YOUR script instead.

# --- FILL IN: one (scene_function, chunk_index) per scene, in order ---------
SC = [(v_hook, 0), (v_100ns, 5), (v_compare, 6), (v_outro, 11)]
# NOTE: the real banana video's SC list is
#   [(v_hook,0),(v_natural,1),(v_element,2),(v_decay,3),(v_bed,4),(v_100ns,5),
#    (v_compare,6),(v_pile,8),(v_balance,9),(v_flow,10),(v_outro,11)]
# -- notice chunks 7 and 8 don't start their own scene: 7 is consumed by
# v_compare (spans 6-7) and the chunk after a spanned range is simply the
# next tuple's chunk index, which is how boundary() knows where the previous
# scene ends.

STARTS = [boundary(c) for _, c in SC]
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
    f = clamp((s1 - t) / 0.22) if i < len(SC) - 1 else clamp((TOTAL - t) / 1.2)
    if t < 0.15:
        f = min(f, t / 0.15)
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
