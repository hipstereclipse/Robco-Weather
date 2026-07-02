#!/usr/bin/env python3
# ============================================================================
#  PIP-BOY 3000 WEATHER COMPANION - graphical interface
#  A modern, Pip-Boy-themed desktop UI over the same engine as the CLI.
#  Pure standard library (Tkinter) - no packages to install.
#
#  Two tabs:
#    RELAY CONTROL  - manage locations, settings, fetch + install to the device
#    DEVICE PREVIEW - shows EXACTLY what the on-device app (WEATHER.JS) will
#                     display for the synced data: the ATMOS / 5-DAY / SOLAR
#                     screens, redrawn on a Tk canvas (no Pillow needed).
#
#  The window clamps itself to the available screen and the control tab
#  scrolls, so nothing gets clipped on small or scaled displays.
#
#  Run:  python pipboy_weather_gui.py
#  (The CLI still works: python pipboy_weather.py)
# ============================================================================

import json
import math
import os
import re
import shutil
import sys
import time
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import pipboy_weather as core
try:
    import pipboy_serial as pbserial          # USB transfer helper (optional)
except ImportError:                           # pyserial/module absent -> button explains
    pbserial = None

# --- Pip-Boy palette (companion chrome) -------------------------------------
BG     = "#06120a"   # screen black-green
PANEL  = "#0b2014"   # panel fill
EDGE   = "#1d5c33"   # borders
GREEN  = "#46ff78"   # primary phosphor green
DIM    = "#2f9d54"   # dimmed green
AMBER  = "#ffb642"   # accent / warnings
SEL    = "#103b22"   # selection fill

# --- device screen palette (mirrors render_preview.py colours) --------------
DBG  = "#04140a"     # device screen background
DFG  = "#1aff80"     # device phosphor green
DHOT = "#a6ffcd"     # device highlight (bright)
DDIM = "#277947"     # device dim green
DAMB = "#ffb642"     # device amber
SCAN = "#0b2414"     # faint scanline

FT    = ("Consolas", 10)
FTB   = ("Consolas", 10, "bold")
FTSM  = ("Consolas", 9)
FTBIG = ("Consolas", 17, "bold")   # header wordmark
FTACT = ("Consolas", 11, "bold")   # compact action-bar buttons

PAD = 14   # outer margin from the window edge for top-level rows, so edge text
           # clears the rounded window corners instead of being clipped
LOCATION_OK_MAX = 4
LOCATION_WARN_MAX = 5

FETCH_LABEL = "FETCH DATA ONLY"
FETCH_BUSY_LABEL = "FETCHING DATA ..."
INSTALL_LABEL = "INSTALL SD + DATA"
INSTALL_BUSY_LABEL = "INSTALLING SD ..."
USB_LABEL = "USB DATA ONLY"
USB_BUSY_LABEL = "SENDING USB DATA ..."
USB_INSTALL_LABEL = "USB INSTALL + DATA"
USB_INSTALL_BUSY_LABEL = "INSTALLING VIA USB ..."

# --- device logical screen (the Pip-Boy 3000 runs LANDSCAPE ~480x320) -------
DEV_W, DEV_H = 480, 320
CORN = 40                      # horizontal inset matching WEATHER.JS' CORN
STALE_HOURS = 12
TABS = ["ATMOS", "5-DAY", "SOLAR"]
F_BIG, F_HEAD, F_SMALL, F_TINY = 56, 24, 16, 12   # logical font tiers

_ANCHOR = {
    (-1, -1): "nw", (0, -1): "n", (1, -1): "ne",
    (-1,  0): "w",  (0,  0): "center", (1,  0): "e",
    (-1,  1): "sw", (0,  1): "s", (1,  1): "se",
}


# ----------------------------------------------------------- solar helpers ---
def _flare_level(cls):
    return {"X": 3, "M": 2, "C": 1}.get(str(cls)[:1].upper(), 0) if cls else 0


def _scale_num(s):
    s = str(s or "")
    digits = "".join(ch for ch in s if ch.isdigit())
    return int(digits) if digits else 0


def solar_active(sp):
    return bool(sp) and (_flare_level(sp.get("flare")) >= 2
                         or _scale_num(sp.get("g_scale")) >= 1
                         or _scale_num(sp.get("s_scale")) >= 1
                         or _scale_num(sp.get("r_scale")) >= 1)


def solar_line(data, loc):
    sp = data.get("space")
    if not sp:
        return None
    if solar_active(sp):
        s = "SOLAR " + (sp.get("flare") or "ACTIVE")
        if _scale_num(sp.get("g_scale")) >= 1:
            s += " / " + sp["g_scale"]
        elif _scale_num(sp.get("s_scale")) >= 1:
            s += " / " + sp["s_scale"]
    else:
        s = "SOLAR QUIET"
    au = loc.get("aurora")
    if au and au.get("chance") and au["chance"] != "UNLIKELY":
        s += "   AURORA " + au["chance"]
    return s


def pad_hex(n):
    return "0x%04X" % max(0, int(n))


def stamp(s):
    if not s:
        return ""
    s = str(s).replace("T", " ")
    return s[5:16] if len(s) >= 16 else s


def rd(v):
    """Round for display, mirroring the device's num(): '--' when missing."""
    return "--" if v is None else str(int(round(v)))


def kp_label(sp, i):
    labels = (sp or {}).get("kpt") or []
    if 0 <= i < len(labels) and labels[i]:
        s = str(labels[i])
        m = re.match(r"^(\d\d/\d\d)[ T](\d\d)(?::\d\d)?Z?$", s, re.I)
        if m:
            h = int(m.group(2))
            return "%s %d %s UTC" % (
                m.group(1), h % 12 or 12, "PM" if h >= 12 else "AM")
        return re.sub(r"Z$", " UTC", s, flags=re.I).upper()
    return "T+%dH" % (i * 3)


# ============================================================================
#  DEVICE PREVIEW CANVAS
#  Re-implements the WEATHER.JS layout against the same WEATHER.JSON so the
#  companion shows what the Pip-Boy will display. Scales to fit its widget.
# ============================================================================
class DeviceCanvas(tk.Canvas):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG, highlightthickness=0, bd=0, **kw)
        self.payload = None
        self.loc = 0
        self.tab = 0
        self.item = 0
        self.scale = 1.0
        self.ox = 0.0
        self.oy = 0.0
        self.bind("<Configure>", lambda e: self.redraw())

    # --- public API --------------------------------------------------------
    def set_payload(self, payload):
        self.payload = payload
        locs = (payload or {}).get("locations") or []
        if self.loc >= len(locs):
            self.loc = 0
        self._clamp_item()
        self.redraw()

    def set_tab(self, i):
        self.tab = i % len(TABS)
        self._clamp_item()
        self.redraw()

    def step_loc(self, delta):
        locs = (self.payload or {}).get("locations") or []
        if locs:
            self.loc = (self.loc + delta) % len(locs)
            self._clamp_item()
            self.redraw()

    def step_item(self, delta):
        n = self.item_count()
        self.item = (self.item + delta + n) % n
        self.redraw()

    def item_count(self):
        d = self.payload
        locs = (d or {}).get("locations") or []
        if not locs:
            return 1
        loc = locs[min(self.loc, len(locs) - 1)]
        if self.tab == 0:
            return 4
        if self.tab == 1:
            return max(1, min(5, len(loc.get("daily") or [])))
        return max(1, min(24, len(((d or {}).get("space") or {}).get("kpf") or [])))

    def _clamp_item(self):
        n = self.item_count()
        if self.item >= n:
            self.item = n - 1
        if self.item < 0:
            self.item = 0

    def status_text(self):
        d = self.payload
        if not d or not d.get("locations"):
            return "NO DATA - run a fetch to preview the device screen"
        loc = d["locations"][self.loc]
        n = len(d["locations"])
        ic = self.item_count()
        when = d.get("generated", "?")
        flag = "  [STALE]" if self.stale() else ""
        return "SITE %d/%d  ITEM %d/%d  %s   synced %s%s" % (
            self.loc + 1, n, self.item + 1, ic, loc.get("name", "?"), when, flag)

    # --- scaled drawing primitives ----------------------------------------
    def _x(self, x):
        return self.ox + x * self.scale

    def _y(self, y):
        return self.oy + y * self.scale

    def _lw(self, w):
        return max(1, int(round(w * self.scale)))

    def _font(self, size, bold=False):
        px = max(7, int(round(size * self.scale)))
        return ("Consolas", -px, "bold") if bold else ("Consolas", -px)

    def line(self, x0, y0, x1, y1, fill=DFG, w=1):
        self.create_line(self._x(x0), self._y(y0), self._x(x1), self._y(y1),
                         fill=fill, width=self._lw(w))

    def rect(self, x0, y0, x1, y1, fill=DFG, w=1):
        self.create_rectangle(self._x(x0), self._y(y0), self._x(x1), self._y(y1),
                              outline=fill, width=self._lw(w))

    def frect(self, x0, y0, x1, y1, fill=DFG):
        self.create_rectangle(self._x(x0), self._y(y0), self._x(x1), self._y(y1),
                              fill=fill, outline="")

    def circle(self, cx, cy, r, fill=DFG, w=1):
        self.create_oval(self._x(cx - r), self._y(cy - r),
                         self._x(cx + r), self._y(cy + r), outline=fill, width=self._lw(w))

    def disc(self, cx, cy, r, fill=DFG):
        self.create_oval(self._x(cx - r), self._y(cy - r),
                         self._x(cx + r), self._y(cy + r), fill=fill, outline="")

    def poly(self, pts, fill=DFG):
        coords = []
        for i in range(0, len(pts), 2):
            coords.append(self._x(pts[i]))
            coords.append(self._y(pts[i + 1]))
        self.create_polygon(coords, fill=fill, outline="")

    def text(self, s, x, y, size, ax=-1, ay=-1, fill=DFG, bold=False):
        self.create_text(self._x(x), self._y(y), text=str(s),
                         anchor=_ANCHOR[(ax, ay)], fill=fill,
                         font=self._font(size, bold))

    # --- staleness ---------------------------------------------------------
    def _age_hours(self):
        ep = (self.payload or {}).get("epoch")
        if not ep:
            return None
        a = (time.time() - ep) / 3600.0
        return a if a >= 0 else None

    def stale(self):
        a = self._age_hours()
        return a is not None and a > STALE_HOURS

    def _age_label(self):
        a = self._age_hours()
        if a is None:
            return "?"
        if a < 1:
            return "<1H"
        return ("%dH" % round(a)) if a < 48 else ("%dD" % round(a / 24))

    # --- chrome ------------------------------------------------------------
    def hr(self, y):
        self.line(12, y, DEV_W - 12, y)

    def box(self, x0, y0, x1, y1, label):
        self.rect(x0, y0, x1, y1)
        if label:
            self.frect(x0 + 7, y0 - 1, x0 + 19 + len(label) * 7, y0 + 8, fill=DBG)
            self.text(" " + label + " ", x0 + 9, y0 - 1, F_TINY, fill=DFG)

    def gauge(self, x, y, w, value, maxv):
        self.rect(x, y, x + w, y + 6, fill=DDIM)
        try:
            fill = max(0, min(w - 2, round((w - 2) * float(value) / maxv)))
        except (TypeError, ValueError, ZeroDivisionError):
            return
        if fill > 0:
            self.frect(x + 1, y + 1, x + fill, y + 5, fill=DFG)

    def stat_row(self, label, value, xL, xR, y):
        self.text(label, xL, y, F_TINY, ax=-1, ay=0, fill=DDIM)
        self.text(value, xR, y, F_SMALL, ax=1, ay=0)

    def metric(self, label, value, x, y):
        self.text(label, x, y, F_TINY, ax=0, fill=DDIM)
        self.text(value, x, y + 17, F_SMALL, ax=0, ay=0)

    def msg(self, a, b=None):
        self.text(a, DEV_W / 2, DEV_H / 2 - 18, F_HEAD, ax=0, ay=0)
        if b:
            self.text(b, DEV_W / 2, DEV_H / 2 + 20, F_SMALL, ax=0, ay=0, fill=DDIM)

    def header(self):
        d = self.payload
        n = len(d["locations"])
        if self.stale():
            self.text("! CACHE %s OLD - SYNC" % self._age_label(), CORN, 6,
                      F_TINY, fill=DHOT)
        else:
            self.text("ROBCO INDUSTRIES (TM) TERMLINK", CORN, 6, F_TINY)
        self.text("%s [%d/%d]" % (TABS[self.tab], self.loc + 1, n), DEV_W - CORN, 6,
                  F_TINY, ax=1)
        self.hr(18)

    def footer(self):
        y = DEV_H - 16
        self.hr(y - 4)
        self.text("WHEEL:SITE  THUMB:PAGE  ITEMS:EXIT", CORN, y, F_TINY)
        gen = self.payload.get("generated", "")
        st = self.stale()
        self.text(("! " if st else "UPD ") + stamp(gen), DEV_W - CORN, y,
                  F_TINY, ax=1, fill=DHOT if st else DFG)

    def title(self, loc):
        self.text((loc.get("name") or "UNKNOWN").upper()[:24], CORN, 24,
                  F_SMALL, ax=-1, bold=True)
        if loc.get("region"):
            self.text(loc["region"].upper()[:30], CORN, 43, F_TINY, ax=-1, fill=DDIM)
        self.text("SITE " + pad_hex(0xA100 + self.loc * 0x23), DEV_W - CORN, 43,
                  F_TINY, ax=1, fill=DDIM)

    def tabs(self):
        y = 58
        bw = (DEV_W - 24) / len(TABS)
        for i, t in enumerate(TABS):
            x0 = 12 + i * bw
            col = DHOT if i == self.tab else DDIM
            if i == self.tab:
                self.rect(x0 + 3, y, x0 + bw - 3, y + 15, fill=DHOT)
            self.text(("> " if i == self.tab else "  ") + t, x0 + bw / 2,
                      y + 8, F_TINY, ax=0, ay=0, fill=col)
        self.hr(77)

    # --- weather icon ------------------------------------------------------
    def draw_icon(self, code, cx, cy, r, is_day=True):
        night = not is_day

        def sun(cx, cy, r):
            if night:
                self.disc(cx, cy, r * 0.65)
                self.disc(cx + r * 0.35, cy - r * 0.25, r * 0.6, fill=DBG)
                return
            self.disc(cx, cy, r * 0.55)
            for a in range(8):
                ang = a * math.pi / 4
                self.line(cx + math.cos(ang) * r * 0.85, cy + math.sin(ang) * r * 0.85,
                          cx + math.cos(ang) * r * 1.25, cy + math.sin(ang) * r * 1.25)

        def cloud(cx, cy, r):
            self.disc(cx - r * 0.55, cy + r * 0.15, r * 0.5)
            self.disc(cx + r * 0.55, cy + r * 0.15, r * 0.5)
            self.disc(cx, cy - r * 0.2, r * 0.6)
            self.frect(cx - r * 0.95, cy + r * 0.15, cx + r * 0.95, cy + r * 0.6)

        def rain(cx, cy, r):
            cloud(cx, cy - r * 0.25, r * 0.85)
            for i in (-1, 0, 1):
                x = cx + i * r * 0.5
                self.line(x, cy + r * 0.55, x - r * 0.18, cy + r * 1.05, w=2)

        def snow(cx, cy, r):
            cloud(cx, cy - r * 0.25, r * 0.85)
            for i in (-1, 0, 1):
                x, y = cx + i * r * 0.5, cy + r * 0.8
                self.line(x - 5, y, x + 5, y)
                self.line(x, y - 5, x, y + 5)

        def storm(cx, cy, r):
            cloud(cx, cy - r * 0.25, r * 0.85)
            self.poly([cx, cy + r * 0.4, cx - r * 0.3, cy + r * 0.4, cx, cy + r * 0.95,
                       cx + r * 0.1, cy + r * 0.6, cx + r * 0.35, cy + r * 0.6])

        def fog(cx, cy, r):
            for i in range(4):
                y = cy - r * 0.6 + i * r * 0.45
                self.line(cx - r * (0.7 if i % 2 else 1), y,
                          cx + r * (1 if i % 2 else 0.7), y, w=2)

        def partly(cx, cy, r):
            sun(cx - r * 0.45, cy - r * 0.4, r * 0.65)
            cloud(cx + r * 0.15, cy + r * 0.2, r * 0.8)

        code = code or 0
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

    # --- views -------------------------------------------------------------
    def view_current(self, loc):
        d = self.payload
        c = loc.get("current", {}) or {}
        unit = d.get("units", {}).get("temp", "F")
        d0 = (loc.get("daily") or [{}])[0]
        item = min(self.item, 3)
        self.box(14, 88, 236, 255, "LOCAL ATMOS")
        self.box(248, 88, DEV_W - 14, 255, "INSTRUMENTS")

        self.draw_icon(c.get("code", 0), 70, 135, 24, c.get("is_day", 1))
        self.text(rd(c.get("temp")), 118, 145, F_BIG, ax=-1, ay=0, bold=True)
        self.circle(205 + 5, 124 + 4, 4)
        self.text(unit, 205 + 14, 124 + 6, F_TINY, ax=-1, ay=0)

        self.text("> CONDITION", 24, 184, F_TINY, fill=DDIM)
        if c.get("time"):
            self.text("OBS " + stamp(c["time"]), 226, 184, F_TINY, ax=1, fill=DDIM)
        self.text((c.get("desc") or "--").upper()[:18], 24, 203, F_SMALL)
        self.metric("HI", rd(d0.get("hi")), 52, 224)
        self.metric("LO", rd(d0.get("lo")), 114, 224)
        self.metric("RAIN", rd(d0.get("pop")) + "%", 186, 224)

        xL, xR = 260, DEV_W - 26
        rows = [(104, 126), (138, 160), (172, 200), (212, 240)]
        y0, y1 = rows[item]
        self.rect(254, y0, DEV_W - 20, y1, fill=DHOT)
        self.stat_row("FEELS", rd(c.get("feels")) + unit, xL, xR, 112)
        self.stat_row("WIND", rd(c.get("wind")) + (" " + c["dir"] if c.get("dir") else ""),
                      xL, xR, 146)
        self.stat_row("HUMID", rd(c.get("humidity")) + "%", xL, xR, 180)
        self.gauge(xL, 192, DEV_W - 286, c.get("humidity"), 100)
        self.stat_row("RAD UV", rd(c.get("uv")), xL, xR, 220)
        self.gauge(xL, 232, DEV_W - 286, c.get("uv"), 11)

        if item == 0:
            detail = "FEELS %s%s  ACTUAL %s%s" % (rd(c.get("feels")), unit,
                                                   rd(c.get("temp")), unit)
        elif item == 1:
            detail = "WIND %s%s %s" % (rd(c.get("wind")),
                                       (" " + c["dir"] if c.get("dir") else ""),
                                       d.get("units", {}).get("wind", ""))
        elif item == 2:
            detail = "HUMID %s%%  RAIN %s%%" % (rd(c.get("humidity")), rd(d0.get("pop")))
        else:
            detail = "UV %s  %s" % (rd(c.get("uv")),
                                    solar_line(d, loc) or "SOLAR QUIET")
        self.box(14, 262, DEV_W - 14, 286, "SELECTED TELEMETRY")
        hot = item == 3 and solar_active(d.get("space"))
        self.text(detail[:36], 24, 274, F_SMALL, ay=0, fill=DHOT if hot else DFG)

    def view_forecast(self, loc):
        days = (loc.get("daily") or [])[:5]
        item = min(self.item, max(0, len(days) - 1))
        self.box(14, 88, DEV_W - 14, 222, "FORECAST BUFFER")
        self.text("5 ENTRIES  //  HI/LO  //  PRECIP CHANCE", 26, 103, F_TINY, fill=DDIM)
        colW = (DEV_W - 24) / 5
        for i, dday in enumerate(days):
            x = 12 + colW * i
            cx = x + colW / 2
            if i > 0:
                self.line(x, 126, x, 216, fill=DDIM)
            if i == item:
                self.rect(x + 4, 122, x + colW - 4, 216, fill=DHOT)
            self.text(dday.get("d", "?"), cx, 134, F_SMALL, ax=0)
            self.draw_icon(dday.get("code", 0), cx, 164, 13, True)
            self.text((dday.get("desc") or "--").upper()[:9], cx, 192, F_TINY, ax=0, fill=DDIM)
            self.text("%s/%s %s%%" % (rd(dday.get("hi")), rd(dday.get("lo")),
                      rd(dday.get("pop"))), cx, 207, F_TINY, ax=0)

        dday = days[item] if days else {}
        self.box(14, 232, DEV_W - 14, 286, "ENTRY DETAIL")
        self.text(("%s  %s" % (dday.get("date", dday.get("d", "?")),
                  (dday.get("desc") or "--").upper()))[:36],
                  24, 251, F_SMALL)
        self.text("HI/LO %s/%s" % (rd(dday.get("hi")), rd(dday.get("lo"))),
                  24, 276, F_SMALL, ax=-1, ay=0)
        self.text("RAIN %s%%" % rd(dday.get("pop")), DEV_W - 24, 276,
                  F_SMALL, ax=1, ay=0)

    def kp_graph(self, sp, loc, x0, y0, x1, y1, selected=0):
        kpf = sp.get("kpf", []) or []
        base, span = y1, y1 - (y0 + 5)

        def ky(kp):
            return base - (max(0, min(9, kp)) / 9.0) * span

        self.text("KP", x0 - 18, y0 - 8, F_TINY)
        self.line(x0, y0, x0, y1)
        self.line(x0, y1, x1, y1)
        self.text("0", x0 - 4, base, F_TINY, ax=1, ay=0, fill=DDIM)
        for v in (3, 6, 9):
            self.text(str(v), x0 - 2, ky(v), F_TINY, ax=1, ay=0, fill=DDIM)
            self.line(x0 - 2, ky(v), x0 + 2, ky(v), fill=DDIM)
        needed = (loc.get("aurora") or {}).get("needed", 99)
        n = len(kpf) or 1
        bw = (x1 - x0) / n
        for i, kp in enumerate(kpf):
            bx0, bx1 = x0 + i * bw + 1, x0 + (i + 1) * bw - 1
            by = ky(kp)
            if kp >= needed or i == selected:
                self.frect(bx0, by, bx1, base - 1, fill=DHOT if i == selected else DFG)
            else:
                self.rect(bx0, by, bx1, base - 1, fill=DDIM)
            if i == selected:
                self.rect(bx0 - 3, y0 - 2, bx1 + 3, base + 2, fill=DHOT, w=2)
                self.rect(bx0 - 5, y0 - 4, bx1 + 5, base + 4, fill=DHOT)
        if needed <= 9:
            ty = ky(needed)
            dx = x0
            while dx < x1:
                self.line(dx, ty, dx + 3, ty, fill=DHOT)
                dx += 6
        for tk_ in sp.get("kpf_ticks", []) or []:
            tx = x0 + tk_["i"] * bw
            self.line(tx, base, tx, base + 3)
            self.text(str(tk_.get("d", ""))[:5], tx, base + 4, F_TINY, ax=0)

    def view_space(self, loc):
        sp = self.payload.get("space")
        if not sp:
            self.msg("NO SPACE WX DATA", "SYNC COMPANION")
            return
        self.box(14, 88, 238, 240, "ROBCO SOLAR RELAY")
        self.box(250, 88, DEV_W - 14, 240, "KP BUFFER")
        self.stat_row("FLARE", sp.get("flare", "NONE"), 26, 226, 114)
        self.stat_row("R/S/G", "%s %s %s" % (sp.get("r_scale", "R0"),
                      sp.get("s_scale", "S0"), sp.get("g_scale", "G0")), 26, 226, 150)
        self.stat_row("KP NOW/PK", "%s / %s" % (sp.get("kp_now", "--"),
                      sp.get("kp_peak", "--")), 26, 226, 186)
        self.text((sp.get("g_text") or "FIELD QUIET").upper()[:25], 26, 220, F_TINY, fill=DDIM)
        selected = min(self.item, max(0, len(sp.get("kpf") or []) - 1))
        self.text("KP FORECAST UTC", 262, 106, F_TINY, fill=DDIM)
        self.kp_graph(sp, loc, 286, 124, DEV_W - 26, 218, selected)

        self.box(14, 250, DEV_W - 14, 294, "AURORA ESTIMATE")
        au = loc.get("aurora", {}) or {}
        self.text("AURORA @ " + (loc.get("name") or "").upper()[:18], 24, 268,
                  F_TINY, ax=-1, ay=0)
        chance = au.get("chance", "UNKNOWN")
        self.text(chance, DEV_W - 24, 268, F_HEAD, ax=1, ay=0, bold=True,
                  fill=DHOT if chance in ("LIKELY", "POSSIBLE") else DFG)
        kpf = sp.get("kpf") or []
        kv = kpf[selected] if kpf else "--"
        self.text(("%s  KP %s" % (kp_label(sp, selected), kv))[:24],
                  24, 286, F_SMALL, ax=-1, ay=0)
        self.text("NEED %s PK %s" % (au.get("needed", "?"), au.get("maxkp", "?")),
                  DEV_W - 24, 286, F_SMALL, ax=1, ay=0)

    # --- compositing -------------------------------------------------------
    def _scanlines(self):
        y = 6
        while y < DEV_H - 4:
            self.line(6, y, DEV_W - 6, y, fill=SCAN, w=1)
            y += 4

    def redraw(self):
        self.delete("all")
        cw, ch = self.winfo_width(), self.winfo_height()
        if cw < 12 or ch < 12:
            return
        self.scale = min(cw / DEV_W, ch / DEV_H)
        self.ox = (cw - DEV_W * self.scale) / 2
        self.oy = (ch - DEV_H * self.scale) / 2

        self.frect(0, 0, DEV_W, DEV_H, fill=DBG)
        self._scanlines()

        d = self.payload
        if not d or not d.get("locations"):
            self.msg("NO WEATHER DATA", "RUN A FETCH TO PREVIEW")
            return
        if self.loc >= len(d["locations"]):
            self.loc = 0
        self._clamp_item()
        loc = d["locations"][self.loc]
        self.header()
        self.title(loc)
        self.tabs()
        if self.tab == 0:
            self.view_current(loc)
        elif self.tab == 1:
            self.view_forecast(loc)
        else:
            self.view_space(loc)
        self.footer()


# ============================================================================
#  COMPANION APP
# ============================================================================
class App:
    def __init__(self, root):
        self.root = root
        self.cfg = core.load_config()
        self.search_results = []
        self.q = queue.Queue()
        self.fetching = False
        self.installing = False
        self.usb_busy = False
        self.tab_btns = []

        root.title("ROBCO TERMLINK // WEATHER COMPANION")
        root.configure(bg=BG)
        self._fit_to_screen()
        self._style_notebook()

        self._build()
        self.refresh_locations()
        self.update_output_label()
        self.update_source_state()
        self._load_initial_preview()
        self.log("ROBCO WEATHER RELAY ONLINE.")
        self.log("Sync includes Open-Meteo weather + NOAA SWPC space weather.")
        self.log("DEVICE PREVIEW tab mirrors the on-device screen.")
        self.root.after(80, self._poll)

    # ----------------------------------------------------------- window fit
    def _fit_to_screen(self):
        """Clamp the window to the available screen so nothing is off-screen."""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = max(640, min(980, sw - 80))
        h = max(480, min(720, sh - 100))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2 - 20)
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.root.minsize(min(680, w), min(480, h))

    def _style_notebook(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")          # 'clam' honours colour overrides
        except tk.TclError:
            pass
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(6, 4, 6, 0))
        style.configure("TNotebook.Tab", background=PANEL, foreground=DIM,
                        padding=(16, 6), font=FTB, borderwidth=1)
        style.map("TNotebook.Tab",
                  background=[("selected", SEL)],
                  foreground=[("selected", GREEN)])

    # ---------------------------------------------------------------- styling
    def _btn(self, parent, text, cmd, accent=False):
        c = AMBER if accent else GREEN
        b = tk.Button(parent, text=text, command=cmd, font=FTB,
                      bg=PANEL, fg=c, activebackground=SEL, activeforeground=c,
                      bd=1, relief="solid", highlightbackground=EDGE,
                      cursor="hand2", padx=10, pady=4)
        return b

    def _frame(self, parent, title):
        outer = tk.LabelFrame(parent, text=" " + title + " ", font=FTSM,
                              bg=BG, fg=DIM, bd=1, relief="solid",
                              labelanchor="nw", padx=8, pady=8,
                              highlightbackground=EDGE)
        return outer

    def _scrollable(self, parent):
        """A vertically scrollable container; returns the inner frame to fill."""
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        vsb = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas(e):
            canvas.itemconfigure(win, width=e.width)

        inner.bind("<Configure>", _on_inner)
        canvas.bind("<Configure>", _on_canvas)

        def _wheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return inner

    # -------------------------------------------------------------- build UI
    def _build(self):
        # header ------------------------------------------------------------
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=PAD, pady=(10, 4))
        tk.Label(head, text="ROBCO WEATHER RELAY", font=FTBIG,
                 bg=BG, fg=GREEN).pack(side="left")
        tk.Label(head, text="ROBCO INDUSTRIES (TM) TERMLINK PROTOCOL",
                 font=FTSM, bg=BG, fg=DIM).pack(side="right", pady=(8, 0))
        tk.Frame(self.root, bg=EDGE, height=2).pack(fill="x", padx=PAD)

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=PAD, pady=(8, 4))

        self.control_tab = tk.Frame(self.nb, bg=BG)
        self.preview_tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(self.control_tab, text="RELAY CONTROL")
        self.nb.add(self.preview_tab, text="DEVICE PREVIEW")

        self._build_control_tab(self.control_tab)
        self._build_preview_tab(self.preview_tab)

        # shared action bar - compact, side by side, reachable from BOTH tabs
        # so you can fetch while watching the device preview update in place.
        act = tk.Frame(self.root, bg=BG)
        act.pack(fill="x", padx=PAD, pady=(2, 4))
        act.columnconfigure(0, weight=1, uniform="act")
        act.columnconfigure(1, weight=1, uniform="act")
        act.columnconfigure(2, weight=1, uniform="act")
        act.columnconfigure(3, weight=1, uniform="act")
        self.fetch_btn = self._btn(act, FETCH_LABEL, self.fetch, accent=True)
        self.fetch_btn.configure(font=FTACT, padx=8, pady=5)
        self.fetch_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.install_btn = self._btn(act, INSTALL_LABEL, self.install_app)
        self.install_btn.configure(font=FTACT, padx=8, pady=5)
        self.install_btn.grid(row=0, column=1, sticky="ew", padx=3)
        self.usb_btn = self._btn(act, USB_LABEL, self.usb_sync)
        self.usb_btn.configure(font=FTACT, padx=8, pady=5)
        self.usb_btn.grid(row=0, column=2, sticky="ew", padx=3)
        self.usb_install_btn = self._btn(act, USB_INSTALL_LABEL, self.usb_install)
        self.usb_install_btn.configure(font=FTACT, padx=8, pady=5)
        self.usb_install_btn.grid(row=0, column=3, sticky="ew", padx=(3, 0))

        # terminal log (shared, always visible under the tabs) --------------
        logf = self._frame(self.root, "TERMINAL")
        logf.pack(fill="both", expand=False, padx=PAD, pady=(2, 10))
        self.log_txt = tk.Text(logf, font=FTSM, bg=BG, fg=GREEN, bd=0,
                               highlightthickness=0, height=5, wrap="word")
        self.log_txt.pack(fill="both", expand=True)
        self.log_txt.configure(state="disabled")

    def _build_control_tab(self, parent):
        inner = self._scrollable(parent)

        # locations (saved + add) ------------------------------------------
        body = tk.Frame(inner, bg=BG)
        body.pack(fill="x", padx=2, pady=(6, 0))
        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")

        left = self._frame(body, "SAVED LOCATIONS")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.loc_list = tk.Listbox(left, font=FT, bg=BG, fg=GREEN, height=7,
                                   selectbackground=SEL, selectforeground=AMBER,
                                   bd=0, highlightthickness=0, activestyle="none")
        self.loc_list.pack(fill="both", expand=True)
        self.loc_capacity_lbl = tk.Label(left, text="", font=FTSM, bg=BG,
                                         fg=DIM, anchor="w")
        self.loc_capacity_lbl.pack(fill="x", pady=(6, 0))
        lb = tk.Frame(left, bg=BG)
        lb.pack(fill="x", pady=(8, 0))
        self._btn(lb, "UP", lambda: self.move(-1)).pack(side="left")
        self._btn(lb, "DN", lambda: self.move(1)).pack(side="left", padx=4)
        self._btn(lb, "REMOVE", self.remove_location, accent=True).pack(side="right")
        self._btn(lb, "RESET DEFAULTS", self.reset_locations).pack(side="right", padx=4)

        right = self._frame(body, "ADD LOCATION  (search anywhere on Earth)")
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        sr = tk.Frame(right, bg=BG)
        sr.pack(fill="x")
        self.search_var = tk.StringVar()
        e = tk.Entry(sr, textvariable=self.search_var, font=FT, bg=BG, fg=GREEN,
                     insertbackground=GREEN, bd=1, relief="solid",
                     highlightbackground=EDGE)
        e.pack(side="left", fill="x", expand=True, ipady=3)
        e.bind("<Return>", lambda ev: self.search())
        self._btn(sr, "SEARCH", self.search).pack(side="left", padx=(6, 0))
        self.result_list = tk.Listbox(right, font=FTSM, bg=BG, fg=DIM, height=6,
                                      selectbackground=SEL, selectforeground=GREEN,
                                      bd=0, highlightthickness=0, activestyle="none")
        self.result_list.pack(fill="both", expand=True, pady=(8, 0))
        self.result_list.bind("<Double-Button-1>", lambda ev: self.add_location())
        self._btn(right, "ADD SELECTED <-", self.add_location).pack(
            anchor="e", pady=(8, 0))

        # settings ----------------------------------------------------------
        setf = self._frame(inner, "SETTINGS")
        setf.pack(fill="x", padx=2, pady=(10, 0))
        row = tk.Frame(setf, bg=BG)
        row.pack(fill="x")
        tk.Label(row, text="UNITS", font=FTSM, bg=BG, fg=DIM).pack(side="left")
        self.units_var = tk.StringVar(value=self.cfg.get("units", "F"))
        for u, lbl in (("F", "DEG F"), ("C", "DEG C")):
            tk.Radiobutton(row, text=lbl, value=u, variable=self.units_var,
                           command=self.on_units, font=FT, bg=BG, fg=GREEN,
                           selectcolor=BG, activebackground=BG,
                           activeforeground=AMBER).pack(side="left", padx=2)
        tk.Label(row, text="   SD CARD ROOT", font=FTSM, bg=BG,
                 fg=DIM).pack(side="left")
        self.sd_var = tk.StringVar(value=self.cfg.get("sd_path", ""))
        tk.Entry(row, textvariable=self.sd_var, font=FT, bg=BG, fg=GREEN,
                 insertbackground=GREEN, bd=1, relief="solid",
                 highlightbackground=EDGE, width=18).pack(
            side="left", padx=6, ipady=2)
        self._btn(row, "BROWSE...", self.browse_sd).pack(side="left")

        # app-file source: latest from git, or a local build folder ----------
        srow = tk.Frame(setf, bg=BG)
        srow.pack(fill="x", pady=(6, 0))
        tk.Label(srow, text="APP SOURCE", font=FTSM, bg=BG, fg=DIM).pack(side="left")
        self.source_var = tk.StringVar(value=self.cfg.get("app_source", "local"))
        tk.Radiobutton(srow, text="LATEST (GIT)", value="github",
                       variable=self.source_var, command=self.on_source, font=FTSM,
                       bg=BG, fg=GREEN, selectcolor=BG, activebackground=BG,
                       activeforeground=AMBER).pack(side="left", padx=(6, 0))
        tk.Radiobutton(srow, text="LOCAL FOLDER", value="local",
                       variable=self.source_var, command=self.on_source, font=FTSM,
                       bg=BG, fg=GREEN, selectcolor=BG, activebackground=BG,
                       activeforeground=AMBER).pack(side="left", padx=2)
        self.appdir_var = tk.StringVar(value=self.cfg.get("app_source_dir", ""))
        self.appdir_var.trace_add("write", lambda *a: self.update_source_state())
        self.appdir_entry = tk.Entry(srow, textvariable=self.appdir_var, font=FT,
                                     bg=BG, fg=GREEN, insertbackground=GREEN, bd=1,
                                     relief="solid", highlightbackground=EDGE, width=18)
        self.appdir_entry.pack(side="left", padx=6, ipady=2)
        self.appdir_entry.bind("<FocusOut>", lambda ev: self.on_source())
        self.appdir_btn = self._btn(srow, "BROWSE...", self.browse_appdir)
        self.appdir_btn.pack(side="left")
        self.src_lbl = tk.Label(setf, text="", font=FTSM, bg=BG, fg=DIM, anchor="w")
        self.src_lbl.pack(fill="x", pady=(6, 0))

        self.out_lbl = tk.Label(setf, text="", font=FTSM, bg=BG, fg=DIM, anchor="w")
        self.out_lbl.pack(fill="x", pady=(6, 0))
        tk.Label(setf, text="SYNC INCLUDES: OPEN-METEO WEATHER + NOAA SWPC SPACE WX",
                 font=FTSM, bg=BG, fg=DIM, anchor="w").pack(fill="x")
        tk.Label(setf, text="USE THE FETCH / INSTALL BAR BELOW TO SYNC.",
                 font=FTSM, bg=BG, fg=DIM, anchor="w").pack(fill="x")

    def _build_preview_tab(self, parent):
        # top strip: site navigation + page tabs + status
        strip = tk.Frame(parent, bg=BG)
        strip.pack(fill="x", padx=8, pady=(8, 4))

        nav = tk.Frame(strip, bg=BG)
        nav.pack(side="left")
        self._btn(nav, "< SITE", lambda: self._preview_loc(-1)).pack(side="left")
        self._btn(nav, "SITE >", lambda: self._preview_loc(1)).pack(side="left", padx=(4, 0))
        self._btn(nav, "< ITEM", lambda: self._preview_item(-1)).pack(side="left", padx=(12, 0))
        self._btn(nav, "ITEM >", lambda: self._preview_item(1)).pack(side="left", padx=(4, 0))

        tabrow = tk.Frame(strip, bg=BG)
        tabrow.pack(side="right")
        self.tab_btns = []
        for i, label in enumerate(TABS):
            b = self._btn(tabrow, label, lambda i=i: self._preview_tab(i))
            b.pack(side="left", padx=2)
            self.tab_btns.append(b)

        self.preview = DeviceCanvas(parent, height=330)
        self.preview.pack(fill="both", expand=True, padx=8, pady=4)

        self.preview_status = tk.Label(parent, text="", font=FTSM, bg=BG, fg=DIM,
                                       anchor="w")
        self.preview_status.pack(fill="x", padx=10, pady=(0, 8))
        self._refresh_tab_btns()
        self._refresh_preview_status()

    def _preview_loc(self, delta):
        self.preview.step_loc(delta)
        self._refresh_preview_status()

    def _preview_item(self, delta):
        self.preview.step_item(delta)
        self._refresh_preview_status()

    def _preview_tab(self, i):
        self.preview.set_tab(i)
        self._refresh_tab_btns()
        self._refresh_preview_status()

    def _refresh_tab_btns(self):
        for i, b in enumerate(self.tab_btns):
            active = i == self.preview.tab
            b.configure(fg=AMBER if active else GREEN,
                        bg=SEL if active else PANEL,
                        relief="sunken" if active else "solid")

    def _refresh_preview_status(self):
        self.preview_status.configure(text=self.preview.status_text())

    def _load_initial_preview(self):
        """Show the most recently synced data (if any) the moment we open."""
        candidates = [core.resolve_output(self.cfg),
                      os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "WEATHER.JSON")]
        for path in candidates:
            try:
                if path and os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("locations"):
                        self.preview.set_payload(data)
                        self._refresh_preview_status()
                        return
            except Exception:
                continue

    # ----------------------------------------------------------------- data
    def refresh_locations(self):
        self.loc_list.delete(0, "end")
        for l in self.cfg["locations"]:
            self.loc_list.insert("end", " %-22s %s"
                                 % (l.get("name", "?"), l.get("region", "")))
        self._refresh_location_capacity()

    def _refresh_location_capacity(self):
        n = len(self.cfg.get("locations") or [])
        if n == 0:
            text, color = "NO LOCATIONS SAVED", AMBER
        elif n <= LOCATION_OK_MAX:
            text, color = "%d SAVED - LIKELY OK FOR DEVICE CACHE" % n, DIM
        elif n <= LOCATION_WARN_MAX:
            text, color = "%d SAVED - NEAR THE %d-BYTE DEVICE CACHE LIMIT" % (
                n, core.DEVICE_JSON_LIMIT), AMBER
        else:
            text, color = "%d SAVED - LIKELY TOO MANY; REMOVE SOME BEFORE SYNC" % n, AMBER
        try:
            self.loc_capacity_lbl.configure(text=text, fg=color)
        except AttributeError:
            pass

    def update_output_label(self):
        self.out_lbl.configure(text="OUTPUT  ->  " + core.resolve_output(self.cfg))

    def _sel(self, listbox):
        s = listbox.curselection()
        return s[0] if s else None

    def move(self, delta):
        i = self._sel(self.loc_list)
        if i is None:
            return
        j = i + delta
        locs = self.cfg["locations"]
        if 0 <= j < len(locs):
            locs[i], locs[j] = locs[j], locs[i]
            core.save_config(self.cfg)
            self.refresh_locations()
            self.loc_list.selection_set(j)

    def remove_location(self):
        i = self._sel(self.loc_list)
        if i is None:
            return
        removed = self.cfg["locations"].pop(i)
        core.save_config(self.cfg)
        self.refresh_locations()
        self.log("Removed %s." % removed.get("name"))

    def reset_locations(self):
        ok = messagebox.askyesno(
            "Reset saved locations",
            "Replace the saved location list with the original defaults?",
            parent=self.root)
        if not ok:
            return
        self.cfg["locations"] = [dict(loc) for loc in core.DEFAULT_LOCATIONS]
        core.save_config(self.cfg)
        self.refresh_locations()
        self.log("Restored original default locations.")

    def search(self):
        q = self.search_var.get().strip()
        if not q:
            return
        self.result_list.delete(0, "end")
        self.result_list.insert("end", "  searching ...")
        threading.Thread(target=self._search_worker, args=(q,), daemon=True).start()

    def _search_worker(self, q):
        try:
            res = core.geocode_search(q)
        except Exception as e:
            self.q.put(("__search__", []))
            self.q.put(("log", "Search failed: %s" % e))
            return
        self.q.put(("__search__", res))

    def add_location(self):
        i = self._sel(self.result_list)
        if i is None or i >= len(self.search_results):
            return
        r = self.search_results[i]
        self.cfg["locations"].append({"name": r["name"], "region": r["region"],
                                      "lat": r["lat"], "lon": r["lon"]})
        core.save_config(self.cfg)
        self.refresh_locations()
        self.log("Added %s." % r["label"])

    def on_units(self):
        self.cfg["units"] = self.units_var.get()
        core.save_config(self.cfg)
        self.update_output_label()

    def choose_sd(self, title):
        opts = {"title": title}
        initial = self.sd_var.get().strip()
        if initial and os.path.isdir(initial):
            opts["initialdir"] = initial
        d = filedialog.askdirectory(**opts)
        if not d:
            return ""
        self.sd_var.set(d)
        self.cfg["sd_path"] = d
        core.save_config(self.cfg)
        self.update_output_label()
        return d

    def browse_sd(self):
        self.choose_sd("Select Pip-Boy SD card root")

    # ----------------------------------------------------------- app source
    def on_source(self):
        self.cfg["app_source"] = self.source_var.get()
        self.cfg["app_source_dir"] = self.appdir_var.get().strip()
        core.save_config(self.cfg)
        self.update_source_state()

    def browse_appdir(self):
        init = self.appdir_var.get().strip() or core.PROJECT_ROOT
        opts = {"title": "Select local app build folder"}
        if os.path.isdir(init):
            opts["initialdir"] = init
        d = filedialog.askdirectory(**opts)
        if not d:
            return
        self.source_var.set("local")
        self.appdir_var.set(d)
        self.on_source()

    def update_source_state(self):
        """Enable/disable the folder field and show the effective app source."""
        local = self.source_var.get() != "github"
        state = "normal" if local else "disabled"
        try:
            self.appdir_entry.configure(state=state)
            self.appdir_btn.configure(state=state)
        except (AttributeError, tk.TclError):
            return
        if not local:
            self.src_lbl.configure(
                text="APP FILES  <-  latest from github.com/%s (%s)"
                     % (core.repo_slug(), core.GITHUB_BRANCH))
        else:
            d = self.appdir_var.get().strip()
            self.src_lbl.configure(
                text="APP FILES  <-  "
                     + (d if d else "%s  (bundled)" % core.PROJECT_ROOT))

    def prompt_latest_install(self, target, missing):
        names = "\n".join("  - " + m.replace("\\", "/") for m in missing)
        return messagebox.askyesno(
            "Weather app not found",
            "The Weather app files were not found on %s.\n\n%s\n\n"
            "Install the latest Weather app with this sync?" % (target, names),
            parent=self.root)

    # --------------------------------------------------------------- install
    def install_app(self):
        if self.fetching or self.installing or self.usb_busy:
            return
        if not self.cfg["locations"]:
            self.log("No locations configured - add some first.")
            return
        self.on_source()  # persist the current app-source selection
        sd = self.choose_sd("Select Pip-Boy SD card root for install/update")
        if not sd:
            return
        cfg = dict(self.cfg)
        cfg["locations"] = list(self.cfg.get("locations", []))
        cfg["sd_path"] = sd
        cfg["app_source"] = self.source_var.get()
        cfg["app_source_dir"] = self.appdir_var.get().strip()
        self.installing = True
        self.install_btn.configure(state="disabled", text=INSTALL_BUSY_LABEL)
        self.fetch_btn.configure(state="disabled")
        self.usb_btn.configure(state="disabled")
        self.usb_install_btn.configure(state="disabled")
        threading.Thread(target=self._install_worker, args=(cfg,), daemon=True).start()

    def _install_worker(self, cfg):
        old = sys.stdout
        sys.stdout = _QWriter(self.q)
        tmp = None
        try:
            print("==== DEVICE INSTALL / UPDATE ====")
            print("  > SD card root: %s" % cfg["sd_path"])

            # 1. resolve the app files from the chosen source
            files, tmp = core.app_files_from_config(cfg)

            # 2. copy them onto the card, reporting what actually changed
            print("  > installing %d app file(s) ..." % len(files))
            results = core.install_app_files(cfg["sd_path"], files)
            core.print_install_results(results)

            # 3. sync the latest weather payload alongside the app
            print("  > fetching weather + NOAA SWPC space weather ...")
            payload = core.build_payload(cfg)
            if payload["locations"]:
                core.write_payload(cfg, payload)
                self.q.put(("__payload__", payload))
                print("DEVICE UPDATE COMPLETE - app files plus %d location(s) cached."
                      % len(payload["locations"]))
                if not payload.get("space"):
                    print("Space-weather endpoints were unavailable; weather data was still written.")
                print("Reboot the Pip-Boy after installing or updating.")
            else:
                print("APP FILES INSTALLED, BUT WEATHER DATA WAS NOT UPDATED.")
                print("Check your connection and run fetch again.")
        except Exception as e:
            print("INSTALL ERROR: %s" % e)
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            sys.stdout = old
            self.q.put(("__install_done__", None))

    # ---------------------------------------------------------------- fetch
    def fetch(self):
        if self.fetching or self.installing or self.usb_busy:
            return
        if not self.cfg["locations"]:
            self.log("No locations configured - add some first.")
            return
        self.cfg["sd_path"] = self.sd_var.get().strip()
        core.save_config(self.cfg)
        self.update_output_label()
        install_latest = False
        if self.cfg["sd_path"]:
            try:
                missing = core.missing_sd_app_files(self.cfg["sd_path"])
            except Exception as e:
                self.log("Could not scan for Weather app files: %s" % e)
                missing = []
            if missing:
                install_latest = self.prompt_latest_install("the selected SD card", missing)
        self.fetching = True
        self.install_btn.configure(state="disabled")
        self.fetch_btn.configure(state="disabled", text=FETCH_BUSY_LABEL)
        self.usb_btn.configure(state="disabled")
        self.usb_install_btn.configure(state="disabled")
        threading.Thread(target=self._fetch_worker, args=(install_latest,),
                         daemon=True).start()

    def _fetch_worker(self, install_latest=False):
        old = sys.stdout
        sys.stdout = _QWriter(self.q)
        tmp_app = None
        try:
            if install_latest:
                print("==== INSTALL LATEST + DATA SYNC ====")
                files, tmp_app = core.app_files_from_config(self.cfg, latest=True)
                print("  > installing %d app file(s) ..." % len(files))
                core.print_install_results(
                    core.install_app_files(self.cfg["sd_path"], files))
            payload = core.build_payload(self.cfg)
            if payload["locations"]:
                core.write_payload(self.cfg, payload)
                self.q.put(("__payload__", payload))
                if install_latest:
                    print("INSTALL + SYNC COMPLETE - app files plus %d location(s) cached."
                          % len(payload["locations"]))
                else:
                    print("SYNC COMPLETE - %d location(s) cached."
                          % len(payload["locations"]))
            else:
                print("Nothing fetched - check your connection.")
        except Exception as e:
            print("ERROR: %s" % e)
        finally:
            if tmp_app:
                shutil.rmtree(tmp_app, ignore_errors=True)
            sys.stdout = old
            self.q.put(("__done__", None))

    # ------------------------------------------------------------ USB sync
    def usb_install(self):
        self.usb_sync(install=True)

    def ask_latest_install_from_worker(self, target, missing):
        reply = queue.Queue(maxsize=1)
        self.q.put(("__ask_install_latest__", {
            "target": target,
            "missing": missing,
            "reply": reply,
        }))
        return bool(reply.get())

    def usb_sync(self, install=False):
        if self.fetching or self.installing or self.usb_busy:
            return
        if not self.cfg["locations"]:
            self.log("No locations configured - add some first.")
            return
        if pbserial is None:
            self.log("USB transfer needs pipboy_serial.py beside this app "
                     "and the pyserial package (pip install pyserial).")
            return
        self.on_source()
        cfg = dict(self.cfg)
        cfg["locations"] = list(self.cfg.get("locations", []))
        cfg["app_source"] = self.source_var.get()
        cfg["app_source_dir"] = self.appdir_var.get().strip()
        self.usb_busy = True
        if install:
            self.usb_install_btn.configure(state="disabled", text=USB_INSTALL_BUSY_LABEL)
            self.usb_btn.configure(state="disabled")
        else:
            self.usb_btn.configure(state="disabled", text=USB_BUSY_LABEL)
            self.usb_install_btn.configure(state="disabled")
        self.fetch_btn.configure(state="disabled")
        self.install_btn.configure(state="disabled")
        threading.Thread(target=self._usb_worker, args=(cfg, install),
                         daemon=True).start()

    def _usb_worker(self, cfg, install=False):
        old = sys.stdout
        sys.stdout = _QWriter(self.q)
        tmp = None
        tmp_app = None
        port = None
        install_latest = False
        try:
            print("==== USB INSTALL / UPDATE ====" if install else "==== USB DATA SYNC ====")
            if install:
                print("  > checking USB port before fetching weather ...")
                port = pbserial.find_pipboy()
                print("  > USB device found on %s." % port)
            else:
                print("  > scanning USB device for Weather app files ...")
                scan = pbserial.scan_files(core.usb_app_file_paths())
                port = scan["port"]
                if scan["missing"]:
                    print("  ! Weather app files are missing on the Pip-Boy:")
                    for rel in scan["missing"]:
                        print("    - %s" % rel)
                    install_latest = self.ask_latest_install_from_worker(
                        "the USB-connected Pip-Boy", scan["missing"])
                    if install_latest:
                        print("  > latest app files will be sent with this sync.")
                    else:
                        print("  > continuing with weather data only.")
                else:
                    print("  > Weather app found on %s (%s)."
                          % (scan["port"], scan["board"]))

            payload = core.build_payload(cfg)
            if not payload["locations"]:
                print("Nothing fetched - check your connection.")
                return
            self.q.put(("__payload__", payload))
            tmp, size = core.write_temp_payload(payload)
            print("  > payload: %d location(s), %d bytes"
                  % (len(payload["locations"]), size))
            if size > core.DEVICE_JSON_LIMIT:
                print("  ! cache is large for the Pip-Boy app; remove locations and sync again")

            pairs = []
            if install or install_latest:
                try:
                    files, tmp_app = core.app_files_from_config(cfg, latest=install_latest)
                    pairs.extend((src, rel.replace("\\", "/")) for src, rel in files)
                except Exception as e:
                    if install:
                        raise
                    print("  ! latest app install unavailable: %s" % e)
                    print("  > sending weather data only.")
            pairs.append((tmp, "USER/WEATHER.JSON"))
            print("  > looking for a USB-connected Pip-Boy ...")

            last = {}
            def prog(name, done, total):
                pct = 100 * done // total if total else 100
                prev = last.get(name, -1)
                if pct >= prev + 20 or pct >= 100:
                    last[name] = pct
                    self.q.put(("log", "  > sending %s ... %d%%" % (name, pct)))

            res = pbserial.transfer_files(pairs, port=port, progress=prog)
            print("  > device: %s on %s" % (res["board"], res["port"]))
            for r in res["files"]:
                state = ("verified" if r["verified"] else
                         "written (unverified)" if r["verified"] is False else "written")
                print("    %s  %d bytes  %s" % (r["path"], r["bytes"], state))
            if not payload.get("space"):
                print("  (space-weather endpoints were unavailable; weather data was still sent)")
            if install or install_latest:
                print("USB INSTALL COMPLETE - reboot the Pip-Boy, then open Weather.")
            else:
                print("USB TRANSFER COMPLETE - open (or reopen) Weather on the Pip-Boy.")
        except (pbserial.SerialUnavailable, pbserial.PipBoyNotFound,
                pbserial.TransferError) as e:
            print("USB TRANSFER FAILED: %s" % e)
        except Exception as e:
            print("USB ERROR: %s" % e)
        finally:
            if tmp:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            if tmp_app:
                shutil.rmtree(tmp_app, ignore_errors=True)
            sys.stdout = old
            self.q.put(("__usb_done__", None))

    # ------------------------------------------------------------ ui pump
    def log(self, msg):
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", msg.rstrip() + "\n")
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "__done__":
                    self.fetching = False
                    self.fetch_btn.configure(state="normal", text=FETCH_LABEL)
                    self.install_btn.configure(state="normal", text=INSTALL_LABEL)
                    self.usb_btn.configure(state="normal", text=USB_LABEL)
                    self.usb_install_btn.configure(state="normal", text=USB_INSTALL_LABEL)
                elif kind == "__install_done__":
                    self.installing = False
                    self.install_btn.configure(state="normal", text=INSTALL_LABEL)
                    self.fetch_btn.configure(state="normal", text=FETCH_LABEL)
                    self.usb_btn.configure(state="normal", text=USB_LABEL)
                    self.usb_install_btn.configure(state="normal", text=USB_INSTALL_LABEL)
                elif kind == "__usb_done__":
                    self.usb_busy = False
                    self.usb_btn.configure(state="normal", text=USB_LABEL)
                    self.usb_install_btn.configure(state="normal", text=USB_INSTALL_LABEL)
                    self.fetch_btn.configure(state="normal", text=FETCH_LABEL)
                    self.install_btn.configure(state="normal", text=INSTALL_LABEL)
                elif kind == "__payload__":
                    self.preview.set_payload(payload)
                    self._refresh_preview_status()
                    self.nb.select(self.preview_tab)
                elif kind == "__ask_install_latest__":
                    answer = self.prompt_latest_install(payload["target"],
                                                        payload["missing"])
                    payload["reply"].put(answer)
                elif kind == "__search__":
                    self.search_results = payload
                    self.result_list.delete(0, "end")
                    if not payload:
                        self.result_list.insert("end", "  no matches")
                    for r in payload:
                        self.result_list.insert("end", "  " + r["label"])
                elif kind == "log":
                    self.log(payload)
                else:
                    self.log(str(payload))
        except queue.Empty:
            pass
        self.root.after(80, self._poll)


class _QWriter:
    """Redirects core's print() output into the UI log queue."""
    def __init__(self, q):
        self.q = q
        self.buf = ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.q.put(("log", line))

    def flush(self):
        pass


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
