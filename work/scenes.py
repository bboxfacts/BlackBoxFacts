# ============================================================ SCENES: clothes moths =====
ACC = (255, 196, 54)   # accent = the larvae and what they do (chewing, digesting)

import random

def sweater_pts(cx, cy, s):
    P = [(-55, -150), (-150, -125), (-265, 60), (-205, 95), (-130, -10), (-130, 190),
         (130, 190), (130, -10), (205, 95), (265, 60), (150, -125), (55, -150), (0, -105)]
    return [(cx + x * s, cy + y * s) for x, y in P]

def outline(fr, pts, color, width=6, alpha=1.0):
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]; x2, y2 = pts[(i + 1) % n]
        fr.line(x1, y1, x2, y2, color, width, alpha)

def sweater(fr, cx, cy, s=1.0, alpha=1.0, color=WHITE):
    outline(fr, sweater_pts(cx, cy, s), color, 6, alpha)
    # ribbing lines at hem and cuffs
    for k in range(-4, 5):
        x = cx + k * 26 * s
        fr.line(x, cy + 165 * s, x, cy + 185 * s, color, 3, alpha * 0.6)

def hole(fr, cx, cy, r, p, seed=0, color=ACC):
    if p <= 0.01:
        return
    rnd = random.Random(seed)
    N = 14
    pts = []
    for i in range(N):
        ang = 2 * math.pi * i / N
        rr = r * clamp(p, 0, 1.2) * (0.72 + 0.5 * rnd.random())
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    fr.poly(pts, color, min(1, p))

def larva(fr, cx, cy, s=1.0, t=0.0, alpha=1.0, n=8, ang=0.0, color=ACC):
    if alpha <= 0.004:
        return
    ca, sa = math.cos(ang), math.sin(ang)
    for i in range(n):
        u = i / (n - 1)
        lx = (u - 0.5) * 220 * s
        ly = math.sin(t * 6 + i * 0.9) * 10 * s
        x = cx + lx * ca - ly * sa; y = cy + lx * sa + ly * ca
        r = (22 - 6 * abs(u - 0.75)) * s if i < n - 1 else 26 * s
        fr.circle(x, y, r, fill=color, alpha=alpha)
        fr.circle(x, y, r, outline=BLACK, width=3 * s, alpha=1.0)
    # head marker
    u = 1.0; lx = 0.5 * 220 * s; ly = math.sin(t * 6 + (n - 1) * 0.9) * 10 * s
    x = cx + lx * ca - ly * sa; y = cy + lx * sa + ly * ca
    fr.circle(x + 8 * s * ca, y + 8 * s * sa, 8 * s, fill=BLACK, alpha=1.0)

def moth(fr, cx, cy, s=1.0, t=0.0, alpha=1.0, color=WHITE, flap=True):
    if alpha <= 0.004:
        return
    f = 0.75 + 0.25 * math.cos(t * 14) if flap else 1.0
    for sg in (-1, 1):
        fr.poly([(cx, cy - 20 * s), (cx + sg * 150 * s * f, cy - 95 * s), (cx + sg * 120 * s * f, cy + 25 * s)], color, alpha)
        fr.poly([(cx, cy + 5 * s), (cx + sg * 95 * s * f, cy + 40 * s), (cx + sg * 55 * s * f, cy + 95 * s)], color, alpha * 0.75)
        fr.line(cx + sg * 6 * s, cy - 55 * s, cx + sg * 50 * s, cy - 120 * s, color, 4 * s, alpha)
    fr.rect(cx - 13 * s, cy - 60 * s, cx + 13 * s, cy + 80 * s, color, alpha, radius=13 * s)
    fr.rect(cx - 9 * s, cy - 56 * s, cx + 9 * s, cy + 76 * s, (200, 200, 200), alpha, radius=9 * s)

def cross(fr, cx, cy, r, p, color=WHITE, width=12):
    if p <= 0:
        return
    a = clamp(p * 2); b = clamp(p * 2 - 1)
    fr.line(cx - r, cy - r, lerp(cx - r, cx + r, a), lerp(cy - r, cy + r, a), color, width)
    if b > 0:
        fr.line(cx + r, cy - r, lerp(cx + r, cx - r, b), lerp(cy - r, cy + r, b), color, width)

def W_(c, w, occ=1, end=False):
    return T(c, w, occ, end)

def wtimes(c, words_from, n):
    ws = CHW[c]
    i = [k for k, w in enumerate(ws) if _n(w["text"]) == words_from][0]
    return [ws[i + k]["s"] for k in range(n)]

# ---------------- scenes ----------------
def s_hook(fr, t, s0, s1):
    # sweater visible from frame 0; holes punch in; larvae appear on "babies"
    sweater(fr, CX, 1210, 1.35, alpha=1.0)
    hs = [(-60, -20, 46, -0.2), (80, 90, 38, 0.9), (-20, 170, 30, 1.5), (110, -60, 26, 1.95), (-120, 110, 28, 2.4)]
    for i, (dx, dy, r, tt) in enumerate(hs):
        hole(fr, CX + dx, 1210 + dy, r, eback(t, tt, 0.35), seed=i + 3)
    tb = W_(0, "babies")
    la = ein(t, tb - 0.1, 0.35)
    larva(fr, CX + 10, 1580, 1.25 * (0.6 + 0.4 * eback(t, tb - 0.1, 0.5)), t, la, ang=-0.12)
    ktext(fr, "The moth in your closet never ate your sweater.", XB(84), WHITE, CX, 560, t, -0.12,
          maxw=900, lh=98, stagger=0.03, dur=0.2, rise=26)
    p = eback(t, W_(0, "its") - 0.05, 0.45)
    stext(fr, "Its babies did.", XB(96), ACC, CX, 860, alpha=ein(t, W_(0, "its") - 0.05, 0.25), dy=(1 - clamp(p)) * 30)

def s_mouth(fr, t, s0, s1):
    moth(fr, CX, 1000, 1.6, t, ein(t, s0, 0.4))
    # mouth location crossed out
    pr = ein(t, W_(1, "mouthparts") - 0.1, 0.5)
    fr.circle(CX, 880, 44 * clamp(pr), outline=WHITE, width=6, alpha=pr)
    ktext(fr, "Adult clothes moths have shrunken mouthparts.", BD(66), WHITE, CX, 520, t,
          times=wtimes(1, "adult", 6), maxw=880, lh=80)
    tn = W_(1, "never")
    sp = eback(t, tn - 0.1, 0.5)
    stext(fr, "0", XB(220), WHITE, CX - 120, 1460, alpha=ein(t, tn - 0.1, 0.3), dy=(1 - clamp(sp)) * 30, tnum=True)
    stext(fr, "meals.", BD(80), WHITE, CX + 110, 1490, alpha=ein(t, tn - 0.1, 0.3))
    stext(fr, "Ever.", MD(54), DIM, CX, 1640, alpha=ein(t, W_(1, "single"), 0.3))

def s_life(fr, t, s0, s1):
    steps = [("Mate.", W_(2, "mate")), ("Lay eggs.", W_(2, "lay")), ("Die.", W_(2, "die"))]
    for i, (lab, tt) in enumerate(steps):
        y = 520 + i * 0
        x = CX + (i - 1) * 300
        a = ein(t, tt - 0.08, 0.35)
        stext(fr, lab, XB(70), WHITE, x, 470, alpha=a, dy=(1 - a) * 22)
    # moth descends and fades on "die"
    td = W_(2, "die")
    fall = ein(t, td - 0.05, 0.6)
    moth(fr, CX, 820 + fall * 160, 1.0, t if fall < 0.05 else 0, alpha=1 - 0.65 * fall, flap=fall < 0.05)
    # eggs: dozens of dots on a fabric line
    te = W_(2, "dozens")
    fr.line(140, 1330, 940, 1330, FAINT, 4)
    rnd = random.Random(7)
    for k in range(40):
        x = 170 + rnd.random() * 740; y = 1240 + rnd.random() * 70
        a = ein(t, te - 0.1 + k * 0.03, 0.25)
        fr.circle(x, y, 9, fill=WHITE, alpha=a)
    stext(fr, "dozens of eggs, on your clothes", MD(46), DIM, CX, 1430, alpha=ein(t, W_(2, "clothes") - 0.2, 0.4))

def s_hatch(fr, t, s0, s1):
    th = W_(3, "hatch")
    rnd = random.Random(7)
    for k in range(12):
        x = 200 + k * 62; y = 1000 + rnd.random() * 30
        crack = ein(t, th - 0.1 + k * 0.04, 0.3)
        fr.circle(x, y, 12 * (1 - crack), fill=WHITE, alpha=1 - crack)
    for i, (x, y, s, a0) in enumerate([(CX - 190, 1000, 0.65, -0.3), (CX + 200, 980, 0.6, 0.25), (CX, 1180, 0.85, 0.05)]):
        a = ein(t, th + 0.1 + i * 0.15, 0.4)
        larva(fr, x, y, 1.5 * s * (0.5 + 0.5 * a), t + i, a, ang=a0)
    ktext(fr, "Those eggs hatch into little caterpillars.", BD(70), WHITE, CX, 560, t,
          times=wtimes(3, "those", 6), maxw=900, lh=84)

def s_chew(fr, t, s0, s1):
    sweater(fr, CX, 1150, 1.25)
    tc = W_(3, "chewing")
    for i, (dx, dy, r) in enumerate([(-40, 60, 70), (90, -40, 40), (-110, -60, 30)]):
        hole(fr, CX + dx, 1150 + dy, r, ein(t, tc - 0.2 + i * 0.25, 0.6), seed=20 + i)
    larva(fr, CX + 150, 1150 + 50, 1.0, t * 1.8, 1.0, ang=0.2)
    ktext(fr, "They're the ones chewing the holes.", XB(80), WHITE, CX, 560, t,
          times=wtimes(3, "they're", 6), maxw=900, lh=96)

def s_insane(fr, t, s0, s1):
    p = eback(t, s0 + 0.05, 0.4)
    stext(fr, "Here's the", BD(80), DIM, CX, 760, alpha=ein(t, s0, 0.25), dy=(1 - clamp(p)) * 30)
    sc = 1 + 0.04 * math.sin(t * 9)
    stext(fr, "insane part.", XB(int(118 * sc)), WHITE, CX, 900, alpha=ein(t, W_(4, "insane") - 0.1, 0.25))
    tk = W_(4, "eating")
    stext(fr, "They eat", BD(70), WHITE, CX, 1230, alpha=ein(t, tk - 0.2, 0.3))
    pk = eback(t, W_(4, "keratin") - 0.05, 0.5)
    stext(fr, "KERATIN", XB(150), ACC, CX, 1400, alpha=ein(t, W_(4, "keratin") - 0.05, 0.3), dy=(1 - clamp(pk)) * 40)

def strand(fr, x, y0, y1, t, color=WHITE, amp=14, width=5, alpha=1.0, ph=0):
    N = 24
    pts = []
    for i in range(N + 1):
        u = i / N
        pts.append((x + amp * math.sin(u * 9 + ph + t * 2), lerp(y0, y1, u)))
    for i in range(N):
        fr.line(*pts[i], *pts[i + 1], color, width, alpha, cap=False)

def s_protein(fr, t, s0, s1):
    stext(fr, "Keratin is in:", MD(56), DIM, CX, 470, alpha=ein(t, s0, 0.3))
    items = [("Wool", "wool"), ("Fur", "fur"), ("Feathers", "feathers"), ("Your hair", "hair")]
    for i, (lab, key) in enumerate(items):
        tt = W_(5, key)
        a = ein(t, tt - 0.12, 0.3); sp = eback(t, tt - 0.12, 0.45)
        y = 700 + i * 260
        for k in range(5):
            strand(fr, 230 + k * 22, y - 70, y + 70, t, WHITE, amp=8, width=4, alpha=a * 0.8, ph=k)
        stext(fr, lab, XB(int(96 * (0.7 + 0.3 * clamp(sp)))), WHITE, 380, y, alpha=a, align="l")

def s_bridges(fr, t, s0, s1, snap_t=None, title=None, title_times=None):
    xs = [CX - 150, CX + 150]
    for k, x in enumerate(xs):
        strand(fr, x, 760, 1500, t, WHITE, amp=10, width=7, ph=k * 3.1)
    tb = W_(6, "sulfur") if snap_t is None else s0 - 2
    rungs = 6
    for r in range(rungs):
        y = 820 + r * 120
        a = ein(t, tb - 0.15 + r * 0.06, 0.3)
        snap = 0 if snap_t is None else ein(t, snap_t + r * 0.12, 0.25)
        gap = snap * 60
        xl = CX - 150; xr = CX + 150
        col = WHITE if snap < 0.01 else ACC
        fr.line(xl, y, CX - 18 - gap, y, col, 6, a)
        fr.line(CX + 18 + gap, y, xr, y, col, 6, a)
        stext(fr, "S", SB(34), DIM if snap < 0.01 else ACC, CX - 50 - gap, y - 26, alpha=a)
        stext(fr, "S", SB(34), DIM if snap < 0.01 else ACC, CX + 50 + gap, y - 26, alpha=a)
    if title:
        ktext(fr, title, BD(68), WHITE, CX, 500, t, times=title_times, maxw=900, lh=82)

def s_locked(fr, t, s0, s1):
    s_bridges(fr, t, s0, s1, title="Keratin is locked with sulfur bridges.",
              title_times=[W_(6, "keratin"), W_(6, "is"), W_(6, "locked"), W_(6, "with"), W_(6, "sulfur"), W_(6, "bridges")])

def s_nothing(fr, t, s0, s1):
    s_bridges(fr, t, s0, s1)
    for dx in (-1, 1):
        pass
    ktext(fr, "Almost nothing on Earth can digest it.", XB(76), WHITE, CX, 500, t,
          times=wtimes(6, "almost", 7), maxw=900, lh=90)
    pulse = 0.5 + 0.5 * math.sin(t * 6)
    fr.rrect_outline(CX - 260, 720, CX + 260, 1540, 40, WHITE, 4, alpha=ein(t, W_(6, "digest"), 0.3) * (0.5 + 0.5 * pulse))

def s_can(fr, t, s0, s1):
    a = ein(t, s0, 0.3); p = eback(t, s0 + 0.05, 0.6)
    larva(fr, CX, 1100, 1.9 * (0.6 + 0.4 * clamp(p)), t * 1.5, a)
    ktext(fr, "These larvae can.", XB(100), ACC, CX, 600, t, times=wtimes(7, "these", 3), maxw=900, lh=110)

def s_ph(fr, t, s0, s1):
    # gut tube
    fr.rrect_outline(160, 880, 920, 1100, 110, WHITE, 6)
    ga = ein(t, W_(7, "alkaline") - 0.2, 0.6)
    fr.rect(172, 892, 908, 1088, pc(ACC, 0.35), ga, radius=100)
    ktext(fr, "Their guts are brutally alkaline.", BD(70), WHITE, CX, 520, t, times=wtimes(7, "their", 5), maxw=900, lh=84)
    tp = W_(7, "ph")
    v = lerp(7.0, 10.0, ein(t, tp - 0.1, 0.8))
    a = ein(t, tp - 0.2, 0.3)
    stext(fr, "pH", BD(80), DIM, CX - 210, 1400, alpha=a)
    stext(fr, f"{v:4.1f}", XB(230), ACC, CX + 80, 1380, alpha=a, tnum=True)
    stext(fr, "about as alkaline as soapy water", MD(42), NOTE, CX, 1580, alpha=ein(t, W_(7, "ten"), 0.4))
    # bubbles inside gut
    for k in range(8):
        ph_ = ((t * 0.5 + k / 8) % 1.0)
        fr.circle(220 + ph_ * 640, 990 + 50 * math.sin(k * 2.3 + t * 3), 10 + 4 * (k % 3), outline=WHITE, width=3, alpha=ga * (1 - abs(ph_ - 0.5) * 2) * 0.8)

def s_snap(fr, t, s0, s1):
    s_bridges(fr, t, s0, s1, snap_t=W_(7, "snaps") - 0.1)
    ktext(fr, "Loaded with chemistry that snaps sulfur bridges.", BD(66), WHITE, CX, 500, t,
          times=[W_(7, "loaded"), W_(7, "with"), W_(7, "chemistry"), W_(7, "that"), W_(7, "snaps"), W_(7, "sulfur"), W_(7, "bridges")],
          maxw=900, lh=80)

def s_unsure(fr, t, s0, s1):
    p = eback(t, s0 + 0.05, 0.6)
    sc = hold_pulse(t, 1.2, 0.95, 1.05)
    stext(fr, "?", XB(int(420 * sc)), ACC, CX, 1150, alpha=ein(t, s0, 0.3), dy=(1 - clamp(p)) * 60)
    ktext(fr, "Scientists still aren't totally sure how.", BD(72), WHITE, CX, 560, t,
          times=wtimes(8, "scientists", 6), maxw=900, lh=86)

def drop(fr, cx, cy, s, color=WHITE, alpha=1.0):
    fr.poly([(cx, cy - 60 * s), (cx - 34 * s, cy), (cx + 34 * s, cy)], color, alpha)
    fr.circle(cx, cy + 8 * s, 36 * s, fill=color, alpha=alpha)

def s_worse(fr, t, s0, s1):
    sh = math.sin(t * 40) * 6 * fout(t, s0 + 0.5, 0.3)
    stext(fr, "And it gets worse.", XB(96), WHITE, CX + sh, 640, alpha=ein(t, s0, 0.2))
    tl = W_(9, "love")
    ktext(fr, "They love your sweat.", BD(80), ACC, CX, 900, t, times=wtimes(9, "they", 4), maxw=900)
    for i in range(3):
        y = 1150 + ((t - tl) * 300 + i * 160) % 480
        drop(fr, CX - 200 + i * 200, y, 1.0, WHITE, ein(t, tl + i * 0.12, 0.3))

def s_attract(fr, t, s0, s1):
    items = [("Sweat", "sweat", "drop"), ("Skin flakes", "skin", "flake"), ("Food stains", "food", "stain")]
    for i, (lab, key, kind) in enumerate(items):
        tt = W_(10, key)
        a = ein(t, tt - 0.12, 0.3); sp = clamp(eback(t, tt - 0.12, 0.5))
        y = 700 + i * 300
        x = 280
        if kind == "drop":
            drop(fr, x, y, 1.1 * (0.6 + 0.4 * sp), WHITE, a)
        elif kind == "flake":
            rnd = random.Random(4)
            for k in range(6):
                fx = x + (rnd.random() - 0.5) * 120; fy = y + (rnd.random() - 0.5) * 100
                fr.poly([(fx - 18, fy), (fx, fy - 14), (fx + 20, fy + 4), (fx + 2, fy + 16)], WHITE, a)
        else:
            hole(fr, x, y, 60 * (0.6 + 0.4 * sp), 1.0 * a, seed=11, color=(150, 150, 150))
        stext(fr, lab, XB(80), WHITE, 400, y, alpha=a, align="l")
    ktext(fr, "draw them in.", BD(64), DIM, CX, 1640, t, times=wtimes(10, "draw", 3), maxw=900)

def s_dirty(fr, t, s0, s1):
    sweater(fr, CX, 1150, 1.3)
    spots = [(-70, 40), (60, -50), (20, 120)]
    td = W_(10, "eaten")
    for i, (dx, dy) in enumerate(spots):
        hole(fr, CX + dx, 1150 + dy, 48, 1.0 * ein(t, s0 + 0.1, 0.3), seed=30 + i, color=(110, 110, 110))
        hole(fr, CX + dx, 1150 + dy, 42, eback(t, td - 0.1 + i * 0.15, 0.4), seed=40 + i)
    ktext(fr, "The dirty spots get eaten first.", XB(80), WHITE, CX, 560, t, times=wtimes(10, "the", 6), maxw=900, lh=96)

def s_where(fr, t, s0, s1):
    cy = 1120; s = 1.35
    sweater(fr, CX, cy, s)
    marks = [("armpits", (-130, -10), (-300, 230)), ("collars", (0, -120), (0, -300)), ("folds", (60, 150), (260, 330))]
    for i, (key, (dx, dy), (lx, ly)) in enumerate(marks):
        tt = W_(11, key)
        a = ein(t, tt - 0.1, 0.3)
        hx, hy = CX + dx * s, cy + dy * s
        hole(fr, hx, hy, 34, eback(t, tt - 0.1, 0.4), seed=50 + i)
        fr.line(hx, hy, CX + lx, cy + ly - 20 if ly < 0 else cy + ly - 40, DIM, 3, a)
        stext(fr, key.capitalize(), BD(58), WHITE, CX + lx, cy + ly + (0 if ly > 0 else -30), alpha=a)
    ktext(fr, "That's why the holes hide in", BD(66), WHITE, CX, 470, t, times=wtimes(11, "that's", 6), maxw=900)

def lamp(fr, cx, cy, t, alpha=1.0, on=1.0):
    glow_dot(fr, cx, cy, 70, (255, 255, 255), alpha=alpha * on, glow=0.35 * on, glow_r=60)
    fr.circle(cx, cy, 70, outline=WHITE, width=6, alpha=alpha)
    fr.rect(cx - 36, cy + 66, cx + 36, cy + 120, WHITE, alpha, radius=8)
    for k in range(10):
        ang = k * 36 + t * 10
        r0, r1 = 110, 150 + 10 * math.sin(t * 5 + k)
        fr.line(cx + r0 * math.cos(math.radians(ang)), cy + r0 * math.sin(math.radians(ang)),
                cx + r1 * math.cos(math.radians(ang)), cy + r1 * math.sin(math.radians(ang)), WHITE, 4, alpha * on * 0.7)

def s_lamp(fr, t, s0, s1):
    cy = 1050
    lamp(fr, CX, cy, t, ein(t, s0, 0.3))
    ang = t * 2.4
    mx, my = CX + 260 * math.cos(ang), cy + 120 * math.sin(ang)
    moth(fr, mx, my, 0.55, t * 1.5, 1.0)
    tp = W_(12, "probably")
    cross(fr, mx, my, 90, ein(t, tp, 0.5), ACC, 14)
    ktext(fr, "That moth fluttering around your lamp?", BD(66), WHITE, CX, 470, t, times=wtimes(12, "that", 6), maxw=900, lh=80)
    stext(fr, "Probably not one of them.", XB(72), WHITE, CX, 1500, alpha=ein(t, tp - 0.1, 0.3))

def s_hate(fr, t, s0, s1):
    tl = W_(13, "hate")
    off = ein(t, tl, 0.6)
    lamp(fr, CX, 1050, t, 1.0, on=1 - off)
    moth(fr, CX + 320 * ein(t, tl, 0.8) , 1050 + 500 * ein(t, tl, 0.8), 0.55, t, 1 - ein(t, tl + 0.4, 0.4))
    ktext(fr, "Clothes moths hate light.", XB(90), WHITE, CX, 520, t, times=wtimes(13, "clothes", 4), maxw=900, lh=104)

def s_dark(fr, t, s0, s1):
    # closet: two doors, wool sweater hanging inside
    a = ein(t, s0, 0.3)
    x0, x1, y0, y1 = 200, 880, 800, 1660
    fr.rrect_outline(x0, y0, x1, y1, 12, WHITE, 6, a)
    fr.line(x0 + 40, y0 + 80, x1 - 40, y0 + 80, DIM, 5, a)
    tw = W_(13, "wool")
    sweater(fr, CX, 1200, 0.95, alpha=ein(t, tw - 0.15, 0.35))
    for i, (x, y, ph) in enumerate([(CX - 120, 1260, 0), (CX + 100, 1330, 2)]):
        larva(fr, x, y, 0.6, t * 2 + ph, ein(t, tw + 0.1 + i * 0.1, 0.3))
    ktext(fr, "They hide in the dark, right where your wool lives.", BD(66), WHITE, CX, 520, t,
          times=wtimes(13, "they", 10), maxw=900, lh=80)

def s_loop(fr, t, s0, s1):
    moth(fr, CX, 1150, 1.0, t, 0.5 * ein(t, s0, 0.4))
    ktext(fr, "So next time you blame the moth,", XB(84), WHITE, CX, 640, t, times=wtimes(14, "so", 7), maxw=900, lh=98)
    pr = eback(t, W_(14, "remember") - 0.05, 0.4)
    stext(fr, "remember:", XB(110), ACC, CX, 1500, alpha=ein(t, W_(14, "remember") - 0.05, 0.25), dy=(1 - clamp(pr)) * 30)

def s_follow(fr, t, s0, s1):
    ktext(fr, "Follow. Tomorrow's fact crawls out of somewhere worse.", XB(86), WHITE, CX, 720, t,
          times=wtimes(15, "follow", 8), maxw=900, lh=100)
    tf = W_(15, "follow")
    p = clamp(eback(t, tf - 0.05, 0.5))
    a = ein(t, tf - 0.05, 0.3)
    pw, ph = 420 * (0.8 + 0.2 * p), 130 * (0.8 + 0.2 * p)
    sc = hold_pulse(t, 1.4, 0.97, 1.03) if t > tf + 0.6 else 1.0
    pw *= sc; ph *= sc
    cy = 1300
    fr.rrect_outline(CX - pw / 2, cy - ph / 2, CX + pw / 2, cy + ph / 2, ph / 2, WHITE, 6, a)
    px = CX - pw / 2 + 80 * sc
    fr.line(px - 24, cy, px + 24, cy, WHITE, 8, a)
    fr.line(px, cy - 24, px, cy + 24, WHITE, 8, a)
    stext(fr, "FOLLOW", XB(int(60 * sc)), WHITE, CX + 40 * sc, cy, alpha=a)

def mid(c1, w1):
    return W_(c1, w1) - 0.12

SC = [
    (s_hook, 0.0),
    (s_mouth, boundary(1)),
    (s_life, boundary(2)),
    (s_hatch, boundary(3)),
    (s_chew, mid(3, "and")),
    (s_insane, boundary(4)),
    (s_protein, boundary(5)),
    (s_locked, boundary(6)),
    (s_nothing, mid(6, "almost")),
    (s_can, boundary(7)),
    (s_ph, mid(7, "their")),
    (s_snap, mid(7, "and")),
    (s_unsure, boundary(8)),
    (s_worse, boundary(9)),
    (s_attract, W_(10, "sweat") - 0.12),
    (s_dirty, mid(10, "so")),
    (s_where, boundary(11)),
    (s_lamp, boundary(12)),
    (s_hate, boundary(13)),
    (s_dark, mid(13, "they")),
    (s_loop, boundary(14)),
    (s_follow, boundary(15)),
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
    f = clamp((s1 - t) / 0.2) if i < len(SC) - 1 else 1.0   # final follow card held to the last frame
    return fr.render(f)

