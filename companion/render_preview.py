#!/usr/bin/env python3
# ============================================================================
#  PREVIEW RENDERER
#  Renders PNG mock-ups of how the Pip-Boy Weather app looks on-device, plus
#  the companion GUI, so you can see it before installing anything.
#
#  It re-implements the WEATHER.JS layout against the same WEATHER.JSON, in
#  the Pip-Boy green-phosphor aesthetic (scanlines + bezel). It is a visual
#  approximation - exact fonts/metrics on real hardware will differ.
#
#  Run:  python render_preview.py [path/to/WEATHER.JSON]
#  Out:  ../previews/*.png
#
#  Requires Pillow:  pip install pillow
# ============================================================================

import json
import math
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "..", "previews")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "sample", "WEATHER.JSON")

# logical screen - the Pip-Boy 3000 app runs LANDSCAPE (~480x320 usable)
LW, LH = 480, 320
S = 2  # supersample factor
CORN = 28      # horizontal inset for the top/bottom rows so the rounded
               # display corners do not clip the header/footer text
R_SCREEN = 22  # screen corner radius in logical px (the rounded glass)

BG    = (1, 16, 7)
FG    = (26, 255, 128)
HOT   = (166, 255, 205)
DIM   = (39, 121, 71)
AMBER = (255, 182, 66)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]
FONT_BOLD_CANDIDATES = [
    "C:/Windows/Fonts/consolab.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]


def _find(cands):
    for c in cands:
        if os.path.exists(c):
            return c
    return None


_FONT = _find(FONT_CANDIDATES)
_FONTB = _find(FONT_BOLD_CANDIDATES) or _FONT
_font_cache = {}


def font(size, bold=False):
    key = (int(size), bold)
    if key not in _font_cache:
        path = _FONTB if bold else _FONT
        if path:
            _font_cache[key] = ImageFont.truetype(path, int(size))
        else:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


# font sizes (logical px), mirroring the app's font tiers
F_BIG, F_HEAD, F_SMALL, F_TINY = 56, 24, 16, 12


class Screen:
    """Tiny Graphics-like wrapper so the port reads like the JS app."""
    def __init__(self):
        self.img = Image.new("RGB", (LW * S, LH * S), BG)
        self.d = ImageDraw.Draw(self.img)

    def line(self, x0, y0, x1, y1, fill=FG, w=1):
        self.d.line([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill, width=max(1, int(w * S)))

    def rect(self, x0, y0, x1, y1, fill=FG, w=1):
        self.d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], outline=fill, width=max(1, int(w * S)))

    def frect(self, x0, y0, x1, y1, fill=FG):
        self.d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill)

    def circle(self, cx, cy, r, fill=FG, w=1):
        self.d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S],
                       outline=fill, width=max(1, int(w * S)))

    def disc(self, cx, cy, r, fill=FG):
        self.d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=fill)

    def poly(self, pts, fill=FG):
        self.d.polygon([p * S for p in pts], fill=fill)

    def text(self, txt, x, y, size, ax=-1, ay=-1, fill=FG, bold=False):
        anchor = ({-1: "l", 0: "m", 1: "r"}[ax]) + ({-1: "a", 0: "m", 1: "d"}[ay])
        self.d.text((x * S, y * S), str(txt), font=font(size * S, bold),
                    fill=fill, anchor=anchor)

    def strwidth(self, txt, size, bold=False):
        b = self.d.textbbox((0, 0), str(txt), font=font(size * S, bold))
        return (b[2] - b[0]) / S


# --------------------------------------------------------------- weather icons
def draw_icon(g, code, cx, cy, r, is_day=True):
    night = not is_day

    def sun(cx, cy, r):
        if night:
            g.disc(cx, cy, r * 0.65)
            g.d.ellipse([(cx + r * 0.35 - r * 0.6) * S, (cy - r * 0.25 - r * 0.6) * S,
                         (cx + r * 0.35 + r * 0.6) * S, (cy - r * 0.25 + r * 0.6) * S], fill=BG)
            return
        g.disc(cx, cy, r * 0.55)
        for a in range(8):
            ang = a * math.pi / 4
            g.line(cx + math.cos(ang) * r * 0.85, cy + math.sin(ang) * r * 0.85,
                   cx + math.cos(ang) * r * 1.25, cy + math.sin(ang) * r * 1.25)

    def cloud(cx, cy, r):
        g.disc(cx - r * 0.55, cy + r * 0.15, r * 0.5)
        g.disc(cx + r * 0.55, cy + r * 0.15, r * 0.5)
        g.disc(cx, cy - r * 0.2, r * 0.6)
        g.frect(cx - r * 0.95, cy + r * 0.15, cx + r * 0.95, cy + r * 0.6)

    def rain(cx, cy, r):
        cloud(cx, cy - r * 0.25, r * 0.85)
        for i in (-1, 0, 1):
            x = cx + i * r * 0.5
            g.line(x, cy + r * 0.55, x - r * 0.18, cy + r * 1.05, w=2)

    def snow(cx, cy, r):
        cloud(cx, cy - r * 0.25, r * 0.85)
        for i in (-1, 0, 1):
            x, y = cx + i * r * 0.5, cy + r * 0.8
            g.line(x - 5, y, x + 5, y)
            g.line(x, y - 5, x, y + 5)

    def storm(cx, cy, r):
        cloud(cx, cy - r * 0.25, r * 0.85)
        g.poly([cx, cy + r * 0.4, cx - r * 0.3, cy + r * 0.4, cx, cy + r * 0.95,
                cx + r * 0.1, cy + r * 0.6, cx + r * 0.35, cy + r * 0.6])

    def fog(cx, cy, r):
        for i in range(4):
            y = cy - r * 0.6 + i * r * 0.45
            g.line(cx - r * (0.7 if i % 2 else 1), y, cx + r * (1 if i % 2 else 0.7), y, w=2)

    def partly(cx, cy, r):
        sun(cx - r * 0.45, cy - r * 0.4, r * 0.65)
        cloud(cx + r * 0.15, cy + r * 0.2, r * 0.8)

    if code == 0:
        sun(cx, cy, r)
    elif code in (1, 2):
        partly(cx, cy, r)
    elif code == 3:
        cloud(cx, cy, r)
    elif code in (45, 48):
        fog(cx, cy, r)
    elif 51 <= code <= 67 or 80 <= code <= 82:
        rain(cx, cy, r)
    elif 71 <= code <= 77 or 85 <= code <= 86:
        snow(cx, cy, r)
    elif code >= 95:
        storm(cx, cy, r)
    else:
        cloud(cx, cy, r)


# --------------------------------------------------------------- app chrome
def hr(g, y):
    g.line(12, y, LW - 12, y)


def pad_hex(n):
    return "0x%04X" % max(0, int(n))


def box(g, x0, y0, x1, y1, label):
    g.rect(x0, y0, x1, y1)
    if label:
        g.frect(x0 + 7, y0 - 1, x0 + 19 + len(label) * 7, y0 + 8, fill=BG)
        g.text(" " + label + " ", x0 + 9, y0 - 1, F_TINY, fill=FG)


def gauge(g, x, y, w, value, max_value):
    g.rect(x, y, x + w, y + 6, fill=DIM)
    try:
        fill = max(0, min(w - 2, round((w - 2) * float(value) / max_value)))
    except (TypeError, ValueError, ZeroDivisionError):
        return
    if fill > 0:
        g.frect(x + 1, y + 1, x + fill, y + 5, fill=FG)


def header(g, data, loc_i, stale=False, age="27H"):
    n = len(data["locations"])
    if stale:
        g.text("! CACHE %s OLD - SYNC" % age, CORN, 6, F_TINY, fill=HOT)
    else:
        g.text("ROBCO INDUSTRIES (TM) TERMLINK", CORN, 6, F_TINY)
    g.text("ATMOS [%d/%d]" % (loc_i + 1, n), LW - CORN, 6, F_TINY, ax=1)
    hr(g, 18)


def footer(g, data, stale=False):
    y = LH - 16
    hr(g, y - 4)
    g.text("WHEEL:SITE  THUMB:PAGE  ITEMS:EXIT", CORN, y, F_TINY)
    stamp = data.get("generated", "")[5:]
    g.text(("! " if stale else "UPD ") + stamp, LW - CORN, y, F_TINY,
           ax=1, fill=HOT if stale else FG)


def title(g, loc, loc_i=0):
    g.text(loc.get("name", "?").upper(), CORN, 24, F_SMALL, ax=-1, bold=True)
    if loc.get("region"):
        g.text(loc["region"].upper(), CORN, 43, F_TINY, ax=-1, fill=DIM)
    g.text("SITE " + pad_hex(0xA100 + loc_i * 0x23), LW - CORN, 43, F_TINY,
           ax=1, fill=DIM)


TABS = ["ATMOS", "5-DAY", "SOLAR"]


def tabs(g, active):
    y = 58
    bw = (LW - 24) / len(TABS)
    for i, t in enumerate(TABS):
        x0 = 12 + i * bw
        col = HOT if i == active else DIM
        if i == active:
            g.rect(x0 + 3, y, x0 + bw - 3, y + 15, fill=HOT)
        g.text(("> " if i == active else "  ") + t, x0 + bw / 2, y + 8,
               F_TINY, ax=0, ay=0, fill=col)
    hr(g, 77)


def stat(g, label, value, x, y, w):
    g.text(label, x + w / 2, y, F_TINY, ax=0, fill=DIM)
    g.text(value, x + w / 2, y + 12, F_SMALL, ax=0)


def stat_row(g, label, value, xL, xR, y):
    g.text(label, xL, y, F_TINY, ax=-1, ay=0, fill=DIM)
    g.text(value, xR, y, F_SMALL, ax=1, ay=0)


def flare_level(cls):
    return {"X": 3, "M": 2, "C": 1}.get(str(cls)[:1].upper(), 0) if cls else 0


def scale_num(s):
    m = re.search(r"\d+", str(s or ""))
    return int(m.group()) if m else 0


def solar_active(sp):
    return sp and (flare_level(sp.get("flare")) >= 2 or scale_num(sp.get("g_scale")) >= 1
                   or scale_num(sp.get("s_scale")) >= 1 or scale_num(sp.get("r_scale")) >= 1)


def solar_line(data, loc):
    sp = data.get("space")
    if not sp:
        return None
    if solar_active(sp):
        s = "SOLAR " + (sp.get("flare") or "ACTIVE")
        if scale_num(sp.get("g_scale")) >= 1:
            s += " / " + sp["g_scale"]
        elif scale_num(sp.get("s_scale")) >= 1:
            s += " / " + sp["s_scale"]
    else:
        s = "SOLAR QUIET"
    au = loc.get("aurora")
    if au and au.get("chance") and au["chance"] != "UNLIKELY":
        s += "   AURORA " + au["chance"]
    return s


# --------------------------------------------------------------- views
def view_current(g, data, loc):
    c = loc.get("current", {})
    unit = data.get("units", {}).get("temp", "F")
    d0 = (loc.get("daily") or [{}])[0]
    box(g, 14, 88, 236, 255, "LOCAL ATMOS")
    box(g, 248, 88, LW - 14, 255, "INSTRUMENTS")

    draw_icon(g, c.get("code", 0), 70, 135, 24, c.get("is_day", 1))
    temp = str(round(c.get("temp", 0)))
    g.text(temp, 118, 145, F_BIG, ax=-1, ay=0, bold=True)
    g.circle(205 + 5, 124 + 4, 4)
    g.text(unit, 205 + 14, 124 + 6, F_TINY, ax=-1, ay=0)

    g.text("> CONDITION", 24, 184, F_TINY, fill=DIM)
    g.text(c.get("desc", "--").upper()[:18], 24, 203, F_SMALL)
    g.text("HI/LO %s/%s  RAIN %s%%" % (round(d0.get("hi", 0)),
           round(d0.get("lo", 0)), round(d0.get("pop", 0))), 24, 228,
           F_TINY, fill=FG)
    if c.get("time"):
        g.text("OBS " + c["time"][5:], 24, 243, F_TINY, fill=DIM)

    xL, xR = 260, LW - 26
    stat_row(g, "FEELS", str(round(c.get("feels", 0))) + unit, xL, xR, 112)
    stat_row(g, "WIND", str(round(c.get("wind", 0))) + " " + c.get("dir", ""), xL, xR, 146)
    stat_row(g, "HUMID", str(round(c.get("humidity", 0))) + "%", xL, xR, 180)
    gauge(g, xL, 192, LW - 286, c.get("humidity"), 100)
    stat_row(g, "RAD UV", str(round(c.get("uv", 0))), xL, xR, 220)
    gauge(g, xL, 232, LW - 286, c.get("uv"), 11)

    box(g, 14, 262, LW - 14, 286, "RELAY")
    sl = solar_line(data, loc)
    g.text((sl or "SOLAR RELAY UNAVAILABLE")[:58], 24, 274, F_TINY, ay=0,
           fill=HOT if sl and ("AURORA" in sl or solar_active(data.get("space"))) else FG)


def view_forecast(g, data, loc):
    days = loc.get("daily", [])[:5]
    box(g, 14, 88, LW - 14, 286, "FORECAST BUFFER")
    g.text("5 ENTRIES  //  HI/LO  //  PRECIP CHANCE", 26, 103, F_TINY, fill=DIM)
    colW = (LW - 24) / 5
    for i, dday in enumerate(days):
        cx = 12 + colW * i + colW / 2
        if i > 0:
            g.line(12 + colW * i, 126, 12 + colW * i, 274, fill=DIM)
        g.text(pad_hex(0xB000 + i * 0x10), cx, 119, F_TINY, ax=0, fill=DIM)
        g.text(dday.get("d", "?"), cx, 138, F_SMALL, ax=0)
        draw_icon(g, dday.get("code", 0), cx, 166, 17, True)
        g.text(dday.get("desc", "--").upper()[:10], cx, 198, F_TINY, ax=0, fill=DIM)
        g.text("%s/%s" % (round(dday.get("hi", 0)), round(dday.get("lo", 0))),
               cx, 218, F_SMALL, ax=0)
        g.text(str(round(dday.get("pop", 0))) + "%", cx, 246, F_TINY, ax=0)
        gauge(g, 12 + colW * i + 13, 263, colW - 26, dday.get("pop"), 100)


def kp_graph(g, sp, loc, x0, y0, x1, y1):
    kpf = sp.get("kpf", [])
    base, span = y1, y1 - y0

    def ky(kp):
        return base - (max(0, min(9, kp)) / 9) * span

    g.line(x0, y0, x0, y1)
    g.line(x0, y1, x1, y1)
    for v in (3, 6, 9):
        g.text(str(v), x0 - 2, ky(v), F_TINY, ax=1, ay=0, fill=DIM)
    needed = (loc.get("aurora") or {}).get("needed", 99)
    n = len(kpf) or 1
    bw = (x1 - x0) / n
    for i, kp in enumerate(kpf):
        bx0, bx1 = x0 + i * bw + 1, x0 + (i + 1) * bw - 1
        by = ky(kp)
        if kp >= needed:
            g.frect(bx0, by, bx1, base - 1)
        else:
            g.rect(bx0, by, bx1, base - 1, fill=DIM)
    if needed <= 9:
        ty = ky(needed)
        dx = x0
        while dx < x1:
            g.line(dx, ty, dx + 3, ty, fill=HOT)
            dx += 6
        g.text("AURORA Kp%d" % needed, x0 + 3, y0 - 1, F_TINY, fill=HOT)
    for tk in sp.get("kpf_ticks", []):
        tx = x0 + tk["i"] * bw
        g.line(tx, base, tx, base + 3)
        g.text(tk["d"], tx, base + 4, F_TINY, ax=0)


def view_space(g, data, loc):
    sp = data.get("space")
    if not sp:
        g.text("NO SPACE WX DATA", LW / 2, LH / 2, F_SMALL, ax=0, ay=0)
        return
    box(g, 14, 88, 238, 240, "ROBCO SOLAR RELAY")
    box(g, 250, 88, LW - 14, 240, "KP BUFFER")
    stat_row(g, "FLARE", sp.get("flare", "NONE"), 26, 226, 114)
    stat_row(g, "R/S/G", "%s %s %s" % (sp.get("r_scale", "R0"),
             sp.get("s_scale", "S0"), sp.get("g_scale", "G0")), 26, 226, 150)
    stat_row(g, "KP NOW/PK", "%s / %s" % (sp.get("kp_now", "--"),
             sp.get("kp_peak", "--")), 26, 226, 186)
    g.text((sp.get("g_text") or "FIELD QUIET").upper()[:25], 26, 220, F_TINY, fill=DIM)
    g.text("3-DAY PLANETARY K-INDEX", 262, 106, F_TINY, fill=DIM)
    kp_graph(g, sp, loc, 286, 124, LW - 26, 222)

    box(g, 14, 250, LW - 14, 294, "AURORA ESTIMATE")
    au = loc.get("aurora", {})
    g.text("AURORA @ " + loc.get("name", "").upper()[:18], 24, 268, F_TINY,
           ax=-1, ay=0)
    chance = au.get("chance", "UNKNOWN")
    g.text(chance, LW - 24, 268, F_HEAD, ax=1, ay=0, bold=True,
           fill=HOT if chance in ("LIKELY", "POSSIBLE") else FG)
    if "needed" in au:
        g.text("NEEDS Kp %s   PEAK Kp %s" % (au["needed"], au.get("maxkp", "?")),
               24, 280, F_TINY, fill=FG)


# --------------------------------------------------------------- compositing
def scanlines(img):
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for y in range(0, img.size[1], 3):
        d.line([(0, y), (img.size[0], y)], fill=(0, 0, 0, 60))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def vignette(img):
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    w, h = img.size
    steps = 32
    for i in range(steps):
        alpha = int(((steps - i) / steps) ** 2 * 90)
        d.rectangle([i, i, w - 1 - i, h - 1 - i], outline=(0, 0, 0, alpha))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def crt_effect(img):
    glow = img.filter(ImageFilter.GaussianBlur(2.2))
    img = Image.blend(img, glow, 0.18)
    img = scanlines(img)
    return vignette(img)


def bezel(screen_img, caption):
    m = 26 * S
    top = 50 * S
    W = screen_img.size[0] + m * 2
    H = screen_img.size[1] + top + m
    out = Image.new("RGB", (W, H), (8, 12, 9))
    d = ImageDraw.Draw(out)
    d.rounded_rectangle([6, 6, W - 6, H - 6], radius=18 * S, outline=DIM, width=2 * S)
    d.text((m, 18 * S), caption, font=font(F_HEAD * S, True), fill=FG)
    d.text((W - m, 24 * S), "PIP-BOY 3000", font=font(F_TINY * S, False),
           fill=DIM, anchor="ra")
    # inner screen recess
    d.rectangle([m - 4 * S, top - 4 * S, W - m + 4 * S, H - m + 4 * S], outline=DIM, width=S)
    # round the screen corners so the preview matches the real rounded glass;
    # corner pixels fall back to the bezel so clipped text is obvious
    mask = Image.new("L", screen_img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, screen_img.size[0] - 1, screen_img.size[1] - 1],
        radius=R_SCREEN * S, fill=255)
    out.paste(screen_img, (m, top), mask)
    return out


def render_device(data, loc_i, view, caption, stale=False):
    g = Screen()
    loc = data["locations"][loc_i]
    header(g, data, loc_i, stale=stale)
    title(g, loc, loc_i)
    tabs(g, {"current": 0, "forecast": 1, "space": 2}[view])
    {"current": view_current, "forecast": view_forecast, "space": view_space}[view](g, data, loc)
    footer(g, data, stale=stale)
    img = crt_effect(g.img)
    return bezel(img, caption)


# --------------------------------------------------------------- GUI mockup
def render_gui():
    s = 2
    W, H = 860 * s, 620 * s
    BGc, PANEL, EDGE, GREEN, DIMc, AMB, SELc = ((6, 18, 10), (11, 32, 20), (29, 92, 51),
        (70, 255, 120), (47, 157, 84), (255, 182, 66), (16, 59, 34))
    img = Image.new("RGB", (W, H), BGc)
    d = ImageDraw.Draw(img)

    def t(txt, x, y, size, fill=GREEN, bold=False, anchor="la"):
        d.text((x * s, y * s), txt, font=font(size * s, bold), fill=fill, anchor=anchor)

    def panel(x0, y0, x1, y1, label):
        d.rectangle([x0 * s, y0 * s, x1 * s, y1 * s], outline=EDGE, width=s)
        d.rectangle([(x0 + 6) * s, (y0 - 7) * s, (x0 + 18 + len(label) * 7) * s, (y0 + 4) * s], fill=BGc)
        t(" " + label + " ", x0 + 8, y0 - 11, 9, fill=DIMc)

    # header
    t("ROBCO WEATHER RELAY", 14, 12, 22, bold=True)
    t("ROBCO INDUSTRIES (TM) TERMLINK PROTOCOL", W / s - 14, 24, 9,
      fill=DIMc, anchor="ra")
    d.rectangle([14 * s, 46 * s, (W / s - 14) * s, 48 * s], fill=EDGE)

    # saved locations panel
    panel(14, 70, 420, 330, "SAVED LOCATIONS")
    locs = ["GOODSPRINGS            MOJAVE WASTELAND",
            "CAPITAL WASTELAND      WASHINGTON D.C.",
            "THE COMMONWEALTH       BOSTON, MASS.",
            "NORTHERN OUTPOST       ALASKA TERRITORY"]
    for i, l in enumerate(locs):
        yy = 84 + i * 22
        if i == 3:
            d.rectangle([18 * s, (yy - 2) * s, 414 * s, (yy + 16) * s], fill=SELc)
        t(" " + l, 20, yy, 11, fill=(AMB if i == 3 else GREEN))
    for bx, lbl, col in [(18, "UP", GREEN), (58, "DN", GREEN), (360, "REMOVE", AMB)]:
        d.rectangle([bx * s, 300 * s, (bx + (60 if lbl == "REMOVE" else 28)) * s, 320 * s],
                    outline=EDGE, width=s)
        t(lbl, bx + 6, 304, 10, fill=col, bold=True)

    # add location panel
    panel(440, 70, 846, 330, "ADD LOCATION  (search anywhere on Earth)")
    d.rectangle([446 * s, 84 * s, 760 * s, 106 * s], outline=EDGE, width=s)
    t("goodsprings", 452, 88, 11)
    d.rectangle([770 * s, 84 * s, 840 * s, 106 * s], outline=EDGE, width=s)
    t("SEARCH", 778, 88, 10, bold=True)
    results = ["Goodsprings, Nevada, United States",
               "Goodsprings, Alabama, United States",
               "Springs, Gauteng, South Africa"]
    for i, r in enumerate(results):
        yy = 120 + i * 20
        if i == 0:
            d.rectangle([446 * s, (yy - 2) * s, 840 * s, (yy + 15) * s], fill=SELc)
        t("  " + r, 448, yy, 10, fill=(GREEN if i == 0 else DIMc))
    d.rectangle([720 * s, 300 * s, 840 * s, 320 * s], outline=EDGE, width=s)
    t("ADD SELECTED <-", 728, 304, 10, bold=True)

    # settings
    panel(14, 356, 846, 430, "SETTINGS")
    t("UNITS", 24, 372, 9, fill=DIMc)
    t("(X) DEG F   ( ) DEG C", 70, 370, 11)
    t("SD CARD ROOT", 230, 372, 9, fill=DIMc)
    d.rectangle([330 * s, 368 * s, 600 * s, 390 * s], outline=EDGE, width=s)
    t("E:\\", 338, 372, 11)
    d.rectangle([610 * s, 368 * s, 700 * s, 390 * s], outline=EDGE, width=s)
    t("BROWSE...", 618, 372, 10, bold=True)
    t("OUTPUT  ->  E:\\USER\\WEATHER.JSON", 24, 402, 9, fill=DIMc)

    # fetch button
    d.rectangle([14 * s, 444 * s, 846 * s, 486 * s], outline=AMB, width=2 * s)
    t("FETCH WEATHER + SPACE WX", W / (2 * s), 465, 22, fill=AMB, bold=True,
      anchor="mm")

    # terminal log
    panel(14, 500, 846, 600, "TERMINAL")
    log = ["ROBCO WEATHER RELAY ONLINE.",
           "Data: Open-Meteo (weather) + NOAA SWPC (space weather).",
           "  > fetching space weather ...",
           "  > fetching NORTHERN OUTPOST ...",
           "  > wrote 4 location(s) -> E:\\USER\\WEATHER.JSON",
           "SYNC COMPLETE - 4 location(s) cached."]
    for i, line in enumerate(log):
        t(line, 22, 512 + i * 14, 9, fill=GREEN)

    return scanlines(img)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(DATA, "r", encoding="utf-8") as f:
        data = json.load(f)

    # find a high-latitude location for the aurora demo, else use 0
    north = next((i for i, l in enumerate(data["locations"])
                  if (l.get("aurora") or {}).get("chance") == "LIKELY"), 0)

    jobs = [
        (render_device(data, 0, "current", "CURRENT CONDITIONS"), "01_current.png"),
        (render_device(data, 0, "forecast", "5-DAY FORECAST"), "02_forecast.png"),
        (render_device(data, north, "space", "SPACE WEATHER"), "03_space_weather.png"),
        (render_device(data, north, "current", "CURRENT + SOLAR TIE-IN"), "04_current_solar.png"),
        (render_device(data, 0, "current", "STALE-DATA WARNING", stale=True), "05_stale_warning.png"),
        (render_gui(), "06_companion_gui.png"),
    ]
    for img, name in jobs:
        path = os.path.join(OUT_DIR, name)
        img.save(path)
        print("wrote", os.path.normpath(path))


if __name__ == "__main__":
    main()
