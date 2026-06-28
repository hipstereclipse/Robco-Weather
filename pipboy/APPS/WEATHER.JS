(function() {
  var G = (typeof h !== "undefined") ? h : (typeof g !== "undefined") ? g : null;
  var P = (typeof Pip !== "undefined") ? Pip : null;
  var PATHS = ["USER/WEATHER.JSON", "WEATHER.JSON", "USER/WEATHER.json"];
  var MAX_DATA = 7000;
  var STALE_HOURS = 12;
  var TABS = ["ATMOS", "5-DAY", "SOLAR"];
  var CORN = 28; // horizontal inset for the top/bottom rows so the rounded
                 // display corners do not clip the header/footer text.
  var st = { d: null, e: null, l: 0, t: 0 };

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
    for (y = 31; y < h - 26; y += 8) G.clearRect(8, y, w - 8, y);
    G.drawRect(3, 3, w - 4, h - 4);
  }
  function hr(y) { G.drawLine(12, y, W() - 12, y); }
  function stamp(s) {
    if (!s) return "";
    s = ("" + s).replace("T", " ");
    return s.length >= 16 ? s.substr(5, 11) : s;
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

  function header() {
    font(0);
    if (st.d && stale()) text("! CACHE " + ageLabel(ageHours()) + " OLD - SYNC", CORN, 6, -1, -1);
    else text("ROBCO INDUSTRIES (TM) TERMLINK", CORN, 6, -1, -1);
    if (st.d) text("ATMOS [" + (st.l + 1) + "/" + st.d.locations.length + "]", W() - CORN, 6, 1, -1);
    hr(18);
  }
  function footer() {
    var y = H() - 16;
    hr(y - 4);
    font(0);
    text("WHEEL:SITE  THUMB:PAGE  ITEMS:EXIT", CORN, y, -1, -1);
    if (st.d && st.d.generated) text((stale() ? "! " : "UPD ") + stamp(st.d.generated), W() - CORN, y, 1, -1);
  }
  function title(loc) {
    font(1);
    text(cut((loc.name || "UNKNOWN").toUpperCase(), 24), CORN, 24, -1, -1);
    font(0);
    if (loc.region) text(cut((loc.region || "").toUpperCase(), 30), CORN, 43, -1, -1);
    text("SITE " + locAddr(), W() - CORN, 43, 1, -1);
  }
  function tabs() {
    var y = 58, bw = (W() - 24) / TABS.length, i, x, label;
    font(0);
    for (i = 0; i < TABS.length; i++) {
      x = 12 + i * bw;
      if (i === st.t) G.drawRect(x + 2, y, x + bw - 2, y + 15);
      label = (i === st.t ? "> " : "  ") + TABS[i];
      text(label, x + bw / 2, y + 8, 0, 0);
    }
    hr(77);
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
  function sun(cx, cy, r) {
    var i, a;
    G.drawCircle(cx, cy, r);
    for (i = 0; i < 8; i++) {
      a = i * Math.PI / 4;
      G.drawLine(cx + Math.cos(a) * (r + 4), cy + Math.sin(a) * (r + 4),
        cx + Math.cos(a) * (r + 11), cy + Math.sin(a) * (r + 11));
    }
  }
  function cloud(cx, cy, r) {
    G.drawCircle(cx - r / 2, cy + 2, r / 2);
    G.drawCircle(cx + r / 2, cy + 2, r / 2);
    G.drawCircle(cx, cy - 4, r / 2 + 3);
    G.drawLine(cx - r, cy + r / 2, cx + r, cy + r / 2);
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
        G.drawLine(x, cy + r, x - 4, cy + r + 12);
      }
    } else if ((code >= 71 && code <= 77) || (code >= 85 && code <= 86)) {
      for (i = -1; i <= 1; i++) {
        x = cx + i * 8;
        G.drawLine(x - 4, cy + r + 6, x + 4, cy + r + 6);
        G.drawLine(x, cy + r + 2, x, cy + r + 10);
      }
    } else if (code >= 95) {
      G.drawLine(cx, cy + r - 3, cx - 8, cy + r + 15);
      G.drawLine(cx - 8, cy + r + 15, cx + 3, cy + r + 8);
      G.drawLine(cx + 3, cy + r + 8, cx - 2, cy + r + 23);
    } else if (code === 45 || code === 48) {
      for (i = 0; i < 3; i++) G.drawLine(cx - r, cy + r + i * 6, cx + r, cy + r + i * 6);
    }
  }
  function rowAt(label, val, xL, xR, y) {
    font(0);
    text(label, xL, y, -1, 0);
    font(1);
    text(val, xR, y, 1, 0);
  }
  function row(label, val, y) {
    rowAt(label, val, 258, W() - 14, y);
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
    var c = loc.current || {}, d0 = (loc.daily && loc.daily[0]) || {};
    box(14, 88, 236, 255, "LOCAL ATMOS");
    box(248, 88, W() - 14, 255, "INSTRUMENTS");

    wxIcon(c.code, 70, 135, 24);
    font(3);
    G.setFontAlign(-1, 0);
    G.drawString(num(c.temp), 118, 145);
    degree(205, 124);

    font(0);
    text("> CONDITION", 24, 184, -1, -1);
    font(1);
    text(cut((c.desc || "--").toUpperCase(), 18), 24, 203, -1, -1);
    font(0);
    text("HI/LO " + (d0.hi === undefined ? "--" : Math.round(d0.hi)) + "/" +
      (d0.lo === undefined ? "--" : Math.round(d0.lo)) + "  RAIN " +
      (d0.pop === undefined ? "--" : Math.round(d0.pop)) + "%", 24, 228, -1, -1);
    if (c.time) text("OBS " + stamp(c.time), 24, 243, -1, -1);

    rowAt("FEELS", num(c.feels) + unit(), 260, W() - 26, 112);
    rowAt("WIND", num(c.wind) + (c.dir ? " " + c.dir : ""), 260, W() - 26, 146);
    rowAt("HUMID", num(c.humidity) + "%", 260, W() - 26, 180);
    gauge(260, 192, W() - 286, c.humidity, 100);
    rowAt("RAD UV", num(c.uv), 260, W() - 26, 220);
    gauge(260, 232, W() - 286, c.uv, 11);

    box(14, 262, W() - 14, 286, "RELAY");
    font(0);
    text(cut(solarLine(loc) || "SOLAR RELAY UNAVAILABLE", 58), 24, 274, -1, 0);
  }

  function forecast(loc) {
    var days = loc.daily || [], n = Math.min(days.length, 5), cw = (W() - 24) / 5;
    var i, d, x, cx, hi, lo;
    box(14, 88, W() - 14, 286, "FORECAST BUFFER");
    font(0);
    text("5 ENTRIES  //  HI/LO  //  PRECIP CHANCE", 26, 103, -1, -1);
    for (i = 0; i < n; i++) {
      d = days[i] || {};
      x = 12 + i * cw;
      cx = x + cw / 2;
      if (i > 0) G.drawLine(x, 126, x, 274);
      font(0);
      text(padHex(0xB000 + i * 0x10), cx, 119, 0, -1);
      font(1);
      text(d.d || ("D" + (i + 1)), cx, 138, 0, -1);
      wxIcon(d.code, cx, 166, 17);
      font(0);
      text(cut((d.desc || "--").toUpperCase(), 10), cx, 198, 0, -1);
      hi = d.hi === undefined ? "--" : Math.round(d.hi);
      lo = d.lo === undefined ? "--" : Math.round(d.lo);
      font(1);
      text(hi + "/" + lo, cx, 218, 0, -1);
      font(0);
      text((d.pop === undefined ? "--" : Math.round(d.pop)) + "%", cx, 246, 0, -1);
      gauge(x + 13, 263, cw - 26, d.pop, 100);
    }
  }

  function kpGraph(sp, loc, x0, y0, x1, y1) {
    var k = sp.kpf || [], base = y1, span = y1 - y0, need = 99;
    var i, bw, v, y, bx0, bx1, ty, dx;
    if (!k.length) return;
    if (loc.aurora && loc.aurora.needed !== undefined) need = loc.aurora.needed;
    G.drawLine(x0, y0, x0, y1);
    G.drawLine(x0, y1, x1, y1);
    bw = (x1 - x0) / k.length;
    for (i = 0; i < k.length; i++) {
      v = Math.max(0, Math.min(9, k[i]));
      y = base - v / 9 * span;
      bx0 = x0 + i * bw + 1;
      bx1 = x0 + (i + 1) * bw - 1;
      if (k[i] >= need) G.fillRect(bx0, y, bx1, base - 1);
      else G.drawRect(bx0, y, bx1, base - 1);
    }
    if (need <= 9) {
      ty = base - need / 9 * span;
      for (dx = x0; dx < x1; dx += 8) G.drawLine(dx, ty, dx + 4, ty);
    }
  }
  function space(loc) {
    var sp = st.d.space, au = loc.aurora || {};
    if (!sp) { msg("NO SPACE DATA", "SYNC COMPANION"); return; }
    box(14, 88, 238, 240, "ROBCO SOLAR RELAY");
    box(250, 88, W() - 14, 240, "KP BUFFER");
    font(0);
    rowAt("FLARE", sp.flare || "NONE", 26, 226, 114);
    rowAt("R/S/G", (sp.r_scale || "R0") + " " + (sp.s_scale || "S0") + " " + (sp.g_scale || "G0"), 26, 226, 150);
    rowAt("KP NOW/PK", (sp.kp_now === undefined ? "--" : sp.kp_now) + " / " + (sp.kp_peak === undefined ? "--" : sp.kp_peak), 26, 226, 186);
    font(0);
    text(cut((sp.g_text || "FIELD QUIET").toUpperCase(), 25), 26, 220, -1, -1);
    text("3-DAY PLANETARY K-INDEX", 262, 106, -1, -1);
    kpGraph(sp, loc, 286, 124, W() - 26, 222);
    box(14, 250, W() - 14, 294, "AURORA ESTIMATE");
    font(0);
    text("AURORA @ " + cut((loc.name || "").toUpperCase(), 18), 24, 268, -1, 0);
    font(2);
    text(au.chance || "UNKNOWN", W() - 24, 268, 1, 0);
    font(0);
    if (au.needed !== undefined) text("NEEDS KP " + au.needed + "  PEAK KP " + (au.maxkp === undefined ? "?" : au.maxkp), 24, 280, -1, -1);
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
    if (dir === 0) st.t = (st.t + 1) % TABS.length;
    else st.l = (st.l + dir + st.d.locations.length) % st.d.locations.length;
    click();
    redraw();
  }
  function knob2(dir) {
    if (dir === 0) return;
    st.t = (st.t + dir + TABS.length) % TABS.length;
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
