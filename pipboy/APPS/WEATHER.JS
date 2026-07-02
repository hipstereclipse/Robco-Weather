(function() {
  var G = (typeof h !== "undefined") ? h : (typeof g !== "undefined") ? g : null;
  var P = (typeof Pip !== "undefined") ? Pip : null;
  var PATHS = ["USER/WEATHER.JSON", "WEATHER.JSON", "USER/WEATHER.json"];
  var MAX_DATA = 5600;
  var STALE_HOURS = 12;
  var TABS = ["ATMOS", "5-DAY", "SOLAR"];
  var CORN = 56; // horizontal inset for the top/bottom rows so the rounded
                 // display corners do not clip the header/footer text. Bump
                 // this higher still if a unit's glass is even more rounded.
  var TOP = 10;
  var FOOT = 26;
  var st = { d: null, e: null, l: 0, t: 0, m: 0, a: 0, f: 0, k: 0 };

  function gc() { try { if (global.gc) global.gc(); } catch (e) {} }
  function W() { return G.getWidth ? G.getWidth() : 480; }
  function H() { return G.getHeight ? G.getHeight() : 320; }
  function num(v) { return v === undefined || v === null ? "--" : Math.round(v) + ""; }
  function unit() { return st.d && st.d.units && st.d.units.temp || "F"; }
  function cut(s, n) {
    s = s === undefined || s === null ? "--" : "" + s;
    return s.length > n ? s.substr(0, n) : s;
  }
  function font(n) {
    try {
      if (n === 3) { G.setFont("Monofonto23", 2); return; }
      if (n === 2) { G.setFont("Monofonto23"); return; }
      G.setFont("6x8", n === 1 ? 2 : 1);
      return;
    } catch (e) {}
    try { G.setFontVector(n === 3 ? 54 : n === 2 ? 24 : n === 1 ? 16 : 8); return; } catch (e) {}
    G.setFont("6x8", n === 3 ? 6 : n === 2 ? 3 : n === 1 ? 2 : 1);
  }
  function text(s, x, y, ax, ay) {
    G.setFontAlign(ax === undefined ? 0 : ax, ay === undefined ? -1 : ay);
    G.drawString(s, x, y);
  }
  function rep(ch, n) {
    var s = "";
    while (n-- > 0) s += ch;
    return s;
  }
  function padHex(n) {
    var s = Math.max(0, n).toString(16).toUpperCase();
    return "0x" + rep("0", Math.max(0, 4 - s.length)) + s;
  }
  function locAddr() { return padHex(0xA100 + st.l * 0x23); }
  function box(x0, y0, x1, y1, label) {
    G.drawRect(x0, y0, x1, y1);
    if (label) {
      font(0);
      G.clearRect(x0 + 7, y0, x0 + 15 + label.length * 6, y0 + 8);
      text(" " + label + " ", x0 + 9, y0 - 1, -1, -1);
    }
  }
  function gauge(x, y, w, v, max) {
    var f;
    G.drawRect(x, y, x + w, y + 6);
    if (v === undefined || v === null || !isFinite(v)) return;
    f = Math.max(0, Math.min(w - 2, Math.round((w - 2) * v / max)));
    if (f > 0) G.fillRect(x + 1, y + 1, x + f, y + 5);
  }
  function scanMask() {
    var y, w = W(), h = H();
    for (y = 33; y < h - 32; y += 8) G.clearRect(8, y, w - 8, y);
  }
  function hr(y) { G.drawLine(12, y, W() - 12, y); }
  function stamp(s) {
    if (!s) return "";
    s = ("" + s).replace("T", " ");
    return s.length >= 16 ? s.substr(5, 11) : s;
  }
  function kpLabel(sp, i) {
    var s, m, h, ap;
    if (sp && sp.kpt && sp.kpt[i]) {
      s = "" + sp.kpt[i];
      m = s.match(/^(\d\d\/\d\d)[ T](\d\d)(?::\d\d)?Z?$/i);
      if (m) {
        h = +m[2];
        ap = h >= 12 ? "PM" : "AM";
        h = h % 12;
        if (h === 0) h = 12;
        return m[1] + " " + h + " " + ap + " UTC";
      }
      return s.replace(/Z$/i, " UTC").toUpperCase();
    }
    return "T+" + (i * 3) + "H";
  }
  function ageHours() {
    if (!st.d || !st.d.epoch) return null;
    var a = (Date.now() / 1000 - st.d.epoch) / 3600;
    return isFinite(a) && a >= 0 ? a : null;
  }
  function stale() {
    var a = ageHours();
    return a !== null && a > STALE_HOURS;
  }
  function ageLabel(a) {
    if (a === null) return "?";
    if (a < 1) return "<1H";
    return a < 48 ? Math.round(a) + "H" : Math.round(a / 24) + "D";
  }

  function load() {
    st.d = null;
    st.e = null;
    var fs, txt = null, i;
    try { fs = require("fs"); } catch (e) { st.e = "NO FS MODULE"; return; }
    for (i = 0; i < PATHS.length; i++) {
      try {
        txt = fs.readFileSync(PATHS[i]);
        if (txt) break;
      } catch (e) { txt = null; }
    }
    if (!txt) { st.e = "NO WEATHER DATA"; return; }
    try {
      if (typeof txt !== "string") txt = "" + txt;
      if (txt.length > MAX_DATA) {
        st.e = "DATA TOO LARGE";
        txt = null;
        gc();
        return;
      }
      var d = JSON.parse(txt);
      txt = null;
      gc();
      if (!d || !d.locations || !d.locations.length) { st.e = "EMPTY DATA FILE"; return; }
      st.d = d;
      if (st.l >= d.locations.length) st.l = 0;
    } catch (e) {
      txt = null;
      gc();
      st.e = "BAD DATA FORMAT";
    }
  }

  function itemCount(loc) {
    var n = 1, sp;
    if (st.t === 0) return 4;
    if (st.t === 1) {
      n = loc && loc.daily ? loc.daily.length : 0;
      return Math.max(1, Math.min(5, n));
    }
    sp = st.d && st.d.space;
    n = sp && sp.kpf ? sp.kpf.length : 0;
    return Math.max(1, Math.min(24, n));
  }
  function sel() {
    return st.t === 0 ? st.a : st.t === 1 ? st.f : st.k;
  }
  function setSel(v, loc) {
    var n = itemCount(loc);
    v = (v + n) % n;
    if (st.t === 0) st.a = v;
    else if (st.t === 1) st.f = v;
    else st.k = v;
  }
  function clampSel(loc) { setSel(sel(), loc); }
  function hilite(x0, y0, x1, y1, on) {
    if (on) G.drawRect(x0, y0, x1, y1);
  }
  function header() {
    var loc, n, p;
    font(0);
    if (st.d && stale()) text("! CACHE " + ageLabel(ageHours()) + " OLD - SYNC", CORN, TOP, -1, -1);
    else text("ROBCO INDUSTRIES (TM) TERMLINK", CORN, TOP, -1, -1);
    if (st.d) {
      loc = st.d.locations[st.l] || {};
      n = st.m ? itemCount(loc) : st.d.locations.length;
      p = st.m ? sel() + 1 : st.l + 1;
      text((st.m ? "ITEM" : "SITE") + " [" + p + "/" + n + "]", W() - CORN, TOP, 1, -1);
    }
    hr(24);
  }
  function footer() {
    var y = H() - FOOT;
    hr(y - 6);
    font(0);
    text(st.m ? "WHEEL:ITEM PUSH:SITE K2:VIEW" : "WHEEL:SITE PUSH:ITEM K2:VIEW", CORN, y, -1, -1);
    if (st.d && st.d.generated) text((stale() ? "! " : "UPD ") + stamp(st.d.generated), W() - CORN, y, 1, -1);
  }
  function title(loc) {
    font(1);
    text(cut((loc.name || "UNKNOWN").toUpperCase(), 24), CORN, 32, -1, -1);
    font(0);
    if (loc.region) text(cut((loc.region || "").toUpperCase(), 30), CORN, 51, -1, -1);
    text("SITE " + locAddr(), W() - CORN, 51, 1, -1);
  }
  function tabs() {
    var y = 66, bw = (W() - 24) / TABS.length, i, x, label;
    font(0);
    for (i = 0; i < TABS.length; i++) {
      x = 12 + i * bw;
      if (i === st.t) G.drawRect(x + 2, y, x + bw - 2, y + 15);
      label = (i === st.t ? "> " : "  ") + TABS[i];
      text(label, x + bw / 2, y + 8, 0, 0);
    }
    hr(85);
  }
  function msg(a, b) {
    font(2);
    text(a, W() / 2, H() / 2 - 18, 0, 0);
    font(1);
    if (b) text(b, W() / 2, H() / 2 + 20, 0, 0);
  }

  function degree(x, y) {
    G.drawCircle(x + 5, y + 4, 4);
    font(1);
    text(unit(), x + 14, y + 6, -1, 0);
  }
  function thick(x0, y0, x1, y1) {
    G.drawLine(x0, y0, x1, y1);
    G.drawLine(x0 + 1, y0, x1 + 1, y1);
  }
  function sun(cx, cy, r) {
    var d = r + 10, s = r + 3, q = r / 2;
    G.drawCircle(cx, cy, r);
    G.drawCircle(cx, cy, r - 3);
    thick(cx - d, cy, cx - s, cy);
    thick(cx + s, cy, cx + d, cy);
    thick(cx, cy - d, cx, cy - s);
    thick(cx, cy + s, cx, cy + d);
    thick(cx - q - 5, cy - q - 5, cx - q, cy - q);
    thick(cx + q, cy - q, cx + q + 5, cy - q - 5);
    thick(cx - q - 5, cy + q + 5, cx - q, cy + q);
    thick(cx + q, cy + q, cx + q + 5, cy + q + 5);
  }
  function cloud(cx, cy, r) {
    G.drawCircle(cx - r / 2, cy + 2, r / 2);
    G.drawCircle(cx + r / 2, cy + 2, r / 2);
    G.drawCircle(cx, cy - 4, r / 2 + 3);
    thick(cx - r, cy + r / 2 + 2, cx + r, cy + r / 2 + 2);
  }
  function wxIcon(code, cx, cy, r) {
    var i, x;
    code = code || 0;
    if (code === 0) sun(cx, cy, r);
    else if (code < 3) { sun(cx - r / 2, cy - r / 2, Math.max(5, r / 2)); cloud(cx + 4, cy + 3, r); }
    else cloud(cx, cy, r);
    if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) {
      for (i = -1; i <= 1; i++) {
        x = cx + i * 8;
        thick(x, cy + r, x - 4, cy + r + 12);
      }
    } else if ((code >= 71 && code <= 77) || (code >= 85 && code <= 86)) {
      for (i = -1; i <= 1; i++) {
        x = cx + i * 8;
        thick(x - 4, cy + r + 6, x + 4, cy + r + 6);
        thick(x, cy + r + 2, x, cy + r + 10);
      }
    } else if (code >= 95) {
      thick(cx, cy + r - 3, cx - 6, cy + r + 9);
      thick(cx - 6, cy + r + 9, cx + 2, cy + r + 5);
      thick(cx + 2, cy + r + 5, cx - 1, cy + r + 15);
    } else if (code === 45 || code === 48) {
      for (i = 0; i < 3; i++) thick(cx - r, cy + r + i * 6, cx + r, cy + r + i * 6);
    }
  }
  function rowAt(label, val, xL, xR, y) {
    font(0);
    text(label, xL, y, -1, 0);
    font(1);
    text(val, xR, y, 1, 0);
  }
  function metricAt(label, val, x, y) {
    font(0);
    text(label, x, y, 0, -1);
    font(1);
    text(val, x, y + 17, 0, 0);
  }
  function solarLine(loc) {
    var sp = st.d.space, au = loc.aurora, s;
    if (!sp) return "";
    s = "SOLAR " + (sp.flare || "QUIET");
    if (sp.g_scale && sp.g_scale !== "G0") s += " " + sp.g_scale;
    if (au && au.chance && au.chance !== "UNLIKELY") s += "  AURORA " + au.chance;
    return s;
  }
  function current(loc) {
    var c = loc.current || {}, d0 = (loc.daily && loc.daily[0]) || {}, detail;
    box(14, 96, 236, 246, "LOCAL ATMOS");
    box(248, 96, W() - 14, 246, "INSTRUMENTS");

    wxIcon(c.code, 70, 136, 24);
    font(3);
    G.setFontAlign(-1, 0);
    G.drawString(num(c.temp), 118, 144);
    degree(205, 124);

    font(0);
    text("> CONDITION", 24, 181, -1, -1);
    if (c.time) text("OBS " + stamp(c.time), 226, 181, 1, -1);
    font(1);
    text(cut((c.desc || "--").toUpperCase(), 18), 24, 199, -1, -1);
    metricAt("HI", num(d0.hi), 52, 216);
    metricAt("LO", num(d0.lo), 114, 216);
    metricAt("RAIN", (d0.pop === undefined ? "--" : Math.round(d0.pop)) + "%", 186, 216);

    hilite(254, 104, W() - 20, 127, st.t === 0 && st.a === 0);
    rowAt("FEELS", num(c.feels) + unit(), 262, W() - 26, 116);
    hilite(254, 134, W() - 20, 157, st.t === 0 && st.a === 1);
    rowAt("WIND", num(c.wind) + (c.dir ? " " + c.dir : ""), 262, W() - 26, 146);
    hilite(254, 164, W() - 20, 193, st.t === 0 && st.a === 2);
    rowAt("HUMID", num(c.humidity) + "%", 262, W() - 26, 176);
    gauge(262, 188, W() - 288, c.humidity, 100);
    hilite(254, 202, W() - 20, 233, st.t === 0 && st.a === 3);
    rowAt("RAD UV", num(c.uv), 262, W() - 26, 214);
    gauge(262, 226, W() - 288, c.uv, 11);

    if (st.a === 0) detail = "FEELS " + num(c.feels) + unit() + "  ACTUAL " + num(c.temp) + unit();
    else if (st.a === 1) detail = "WIND " + num(c.wind) + (c.dir ? " " + c.dir : "") + " " + ((st.d.units && st.d.units.wind) || "");
    else if (st.a === 2) detail = "HUMID " + num(c.humidity) + "%  RAIN " + (d0.pop === undefined ? "--" : Math.round(d0.pop)) + "%";
    else detail = "UV " + num(c.uv) + "  " + (solarLine(loc) || "SOLAR QUIET");
    box(14, 250, W() - 14, 282, "SELECTED TELEMETRY");
    font(1);
    text(cut(detail, 36), 24, 266, -1, 0);
  }

  function forecast(loc) {
    var days = loc.daily || [], n = Math.min(days.length, 5), cw = (W() - 24) / 5;
    var i, d, x, cx, hi, lo;
    if (st.f >= n && n > 0) st.f = n - 1;
    box(14, 96, W() - 14, 222, "FORECAST BUFFER");
    font(0);
    text("5 ENTRIES  //  SELECT DAY WITH WHEEL", 26, 111, -1, -1);
    for (i = 0; i < n; i++) {
      d = days[i] || {};
      x = 12 + i * cw;
      cx = x + cw / 2;
      if (i > 0) G.drawLine(x, 126, x, 216);
      hilite(x + 4, 122, x + cw - 4, 216, i === st.f);
      font(1);
      text(d.d || ("D" + (i + 1)), cx, 134, 0, -1);
      wxIcon(d.code, cx, 169, 10);
      font(0);
      text(cut((d.desc || "--").toUpperCase(), 9), cx, 192, 0, -1);
      hi = d.hi === undefined ? "--" : Math.round(d.hi);
      lo = d.lo === undefined ? "--" : Math.round(d.lo);
      text(hi + "/" + lo + " " + (d.pop === undefined ? "--" : Math.round(d.pop)) + "%", cx, 207, 0, -1);
    }
    d = days[st.f] || {};
    hi = d.hi === undefined ? "--" : Math.round(d.hi);
    lo = d.lo === undefined ? "--" : Math.round(d.lo);
    box(14, 232, W() - 14, 282, "ENTRY DETAIL");
    font(1);
    text(cut((d.date || d.d || ("D" + (st.f + 1))) + "  " +
      (d.desc || "--").toUpperCase(), 36), 24, 249, -1, -1);
    text("HI/LO " + hi + "/" + lo, 24, 272, -1, 0);
    text("RAIN " + (d.pop === undefined ? "--" : Math.round(d.pop)) + "%", W() - 24, 272, 1, 0);
  }

  function kpGraph(sp, loc, x0, y0, x1, y1) {
    var k = sp.kpf || [], base = y1, top = y0 + 5, span = y1 - top, need = 99;
    var i, bw, v, y, bx0, bx1, ty, dx, tk, tx;
    if (!k.length) return;
    if (loc.aurora && loc.aurora.needed !== undefined) need = loc.aurora.needed;
    font(0);
    text("KP", x0 - 18, y0 - 8, -1, -1);
    G.drawLine(x0, y0, x0, y1);
    G.drawLine(x0, y1, x1, y1);
    text("0", x0 - 4, base, 1, 0);
    for (v = 3; v <= 9; v += 3) {
      y = base - v / 9 * span;
      text("" + v, x0 - 4, y, 1, 0);
      G.drawLine(x0 - 2, y, x0 + 2, y);
    }
    bw = (x1 - x0) / k.length;
    for (i = 0; i < k.length; i++) {
      v = Math.max(0, Math.min(9, k[i]));
      y = base - v / 9 * span;
      bx0 = x0 + i * bw + 1;
      bx1 = x0 + (i + 1) * bw - 1;
      if (k[i] >= need || i === st.k) G.fillRect(bx0, y, bx1, base - 1);
      else G.drawRect(bx0, y, bx1, base - 1);
      if (i === st.k) {
        G.drawRect(bx0 - 3, y0 - 2, bx1 + 3, base + 2);
        G.drawRect(bx0 - 2, y0 - 1, bx1 + 2, base + 1);
      }
    }
    if (need <= 9) {
      ty = base - need / 9 * span;
      for (dx = x0; dx < x1; dx += 8) G.drawLine(dx, ty, dx + 4, ty);
    }
    for (i = 0; sp.kpf_ticks && i < sp.kpf_ticks.length; i++) {
      tk = sp.kpf_ticks[i];
      tx = x0 + tk.i * bw;
      G.drawLine(tx, base, tx, base + 3);
      text(cut(tk.d || "", 5), tx, base + 5, 0, -1);
    }
  }
  function space(loc) {
    var sp = st.d.space, au = loc.aurora || {}, kv, kt;
    if (!sp) { msg("NO SPACE DATA", "SYNC COMPANION"); return; }
    if (sp.kpf && st.k >= sp.kpf.length) st.k = sp.kpf.length - 1;
    if (st.k < 0) st.k = 0;
    box(14, 96, 238, 232, "ROBCO SOLAR RELAY");
    box(250, 96, W() - 14, 232, "KP BUFFER");
    font(0);
    rowAt("FLARE", sp.flare || "NONE", 26, 226, 118);
    rowAt("R/S/G", (sp.r_scale || "R0") + " " + (sp.s_scale || "S0") + " " + (sp.g_scale || "G0"), 26, 226, 152);
    rowAt("KP NOW/PK", (sp.kp_now === undefined ? "--" : sp.kp_now) + " / " + (sp.kp_peak === undefined ? "--" : sp.kp_peak), 26, 226, 186);
    font(0);
    text(cut((sp.g_text || "FIELD QUIET").toUpperCase(), 25), 26, 216, -1, -1);
    text("KP FORECAST UTC", 262, 114, -1, -1);
    kpGraph(sp, loc, 286, 132, W() - 26, 210);
    box(14, 242, W() - 14, 282, "AURORA ESTIMATE");
    font(0);
    text("AURORA @ " + cut((loc.name || "").toUpperCase(), 18), 24, 258, -1, 0);
    font(2);
    text(au.chance || "UNKNOWN", W() - 24, 258, 1, 0);
    font(1);
    kv = sp.kpf && sp.kpf.length ? sp.kpf[st.k] : "--";
    kt = kpLabel(sp, st.k);
    text(cut(kt + "  KP " + kv, 24), 24, 276, -1, 0);
    text("NEED " + (au.needed === undefined ? "?" : au.needed) + " PK " +
      (au.maxkp === undefined ? "?" : au.maxkp), W() - 24, 276, 1, 0);
  }

  function draw() {
    G.reset().clear();
    header();
    if (st.e || !st.d) {
      msg(st.e || "NO DATA", "RUN COMPANION SYNC");
      font(0);
      text("EXPECTED: USER/WEATHER.JSON", W() / 2, H() / 2 + 52, 0, -1);
      scanMask();
      return;
    }
    var loc = st.d.locations[st.l] || {};
    clampSel(loc);
    title(loc);
    tabs();
    if (st.t === 0) current(loc);
    else if (st.t === 1) forecast(loc);
    else space(loc);
    footer();
    scanMask();
  }
  function redraw() {
    try { draw(); }
    catch (e) {
      gc();
      try {
        G.reset().clear();
        msg("DISPLAY ERROR", "REBOOT OR RESYNC");
      } catch (ignore) {}
    }
  }
  function click() {
    try { if (P && P.knob1Click) P.knob1Click(0); } catch (e) {}
    try { if (P && P.audioBuiltin) P.audioBuiltin("CLICK"); } catch (e) {}
  }
  function knob1(dir) {
    if (!st.d) { if (dir === 0) load(); redraw(); return; }
    var loc = st.d.locations[st.l] || {};
    if (dir === 0) st.m = st.m ? 0 : 1;
    else if (st.m) setSel(sel() + dir, loc);
    else st.l = (st.l + dir + st.d.locations.length) % st.d.locations.length;
    click();
    redraw();
  }
  function knob2(dir) {
    var loc;
    st.t = (st.t + (dir || 1) + TABS.length) % TABS.length;
    if (st.d) {
      loc = st.d.locations[st.l] || {};
      clampSel(loc);
    }
    click();
    redraw();
  }

  if (P) {
    P.on("knob1", knob1);
    P.on("knob2", knob2);
  }
  load();
  redraw();

  return {
    id: "WEATHER",
    notDefault: true,
    fullscreen: true,
    remove: function() {
      if (!P) return;
      P.removeListener("knob1", knob1);
      P.removeListener("knob2", knob2);
    }
  };
})
