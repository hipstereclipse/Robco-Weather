#!/usr/bin/env python3
# ============================================================================
#  PIP-BOY 3000 WEATHER COMPANION
#  Fetches current conditions + a 5-day forecast for any locations on Earth
#  and writes a compact WEATHER.JSON to your Pip-Boy's SD card. The on-device
#  app then displays this cached data with no network required.
#
#  Data source: Open-Meteo (https://open-meteo.com) - free, no API key.
#  Dependencies: NONE. Pure Python 3 standard library (works on desktop and
#  on phones via apps like Pythonista / Pydroid).
#
#  USAGE
#    Interactive menu:   python pipboy_weather.py
#    Just sync saved:    python pipboy_weather.py --fetch
#    Add a location:     python pipboy_weather.py --add "Goodsprings, NV"
#    Set SD output dir:  python pipboy_weather.py --sd E:\        (--fetch too)
#    Use Celsius:        python pipboy_weather.py --units C --fetch
#
#  The Pip-Boy app reads:  <SD>/USER/WEATHER.JSON
# ============================================================================

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# NOAA Space Weather Prediction Center (free, no API key)
SWPC_KP_NOW = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
SWPC_KP_FCST = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
SWPC_SCALES = "https://services.swpc.noaa.gov/products/noaa-scales.json"
SWPC_FLARE = "https://services.swpc.noaa.gov/json/goes/primary/xray-flares-latest.json"

# Approx. geographic latitude at which aurora is overhead for each Kp (0..9).
# (Real visibility uses geomagnetic latitude; this is a good-enough estimate.)
KP_AURORA_LAT = [66.5, 64.5, 62.4, 60.4, 58.3, 56.3, 54.2, 52.2, 50.1, 48.1]

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "weather_config.json")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEVICE_JSON_LIMIT = 7000

# Each device app file: where it lives inside an app-source tree (parts under
# the source root) and where it must land on the SD card (parts under <SD>).
APP_FILES = [
    (("pipboy", "APPS", "WEATHER.JS"),       ("APPS", "WEATHER.JS")),
    (("pipboy", "APPINFO", "WEATHER.info"),  ("APPINFO", "WEATHER.info")),
    (("pipboy", "APPINFO", "WEATHER.IMG"),   ("APPINFO", "WEATHER.IMG")),
]

# Where "install latest" pulls the app files from. The slug is auto-detected
# from this checkout's git remote when possible, with this as the fallback.
GITHUB_DEFAULT_SLUG = "hipstereclipse/Robco-Weather"
GITHUB_BRANCH = "main"

# SD-relative paths an install can leave behind, used when cleaning up /
# uninstalling: the app files plus every WEATHER.JSON variant the device app
# looks for (see PATHS in pipboy/APPS/WEATHER.JS).
APP_FILE_REL = [os.path.join(*sd_parts) for _, sd_parts in APP_FILES]
DATA_FILE_REL = [os.path.join("USER", "WEATHER.JSON"),
                 "WEATHER.JSON",
                 os.path.join("USER", "WEATHER.json")]

# WMO weather interpretation codes -> short description
WMO = {
    0: "Clear skies", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Violent showers",
    85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Storm w/ hail", 99: "Storm w/ hail",
}

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# Sensible Fallout-flavored defaults so the very first run produces data.
DEFAULT_LOCATIONS = [
    {"name": "GOODSPRINGS", "region": "MOJAVE WASTELAND",
     "lat": 35.8341, "lon": -115.4319},
    {"name": "NEW VEGAS", "region": "MOJAVE WASTELAND",
     "lat": 36.1699, "lon": -115.1398},
    {"name": "CAPITAL WASTELAND", "region": "WASHINGTON D.C.",
     "lat": 38.8951, "lon": -77.0364},
    {"name": "THE COMMONWEALTH", "region": "BOSTON, MASS.",
     "lat": 42.3601, "lon": -71.0589},
]


# ----------------------------------------------------------------- helpers ---
def http_get_json(url, params):
    qs = urllib.parse.urlencode(params)
    full = url + "?" + qs
    req = urllib.request.Request(full, headers={"User-Agent": "PipBoyWeather/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def deg_to_compass(deg):
    if deg is None:
        return ""
    return COMPASS[int((deg / 45.0) + 0.5) % 8]


def weekday_label(date_str):
    try:
        d = datetime.date.fromisoformat(date_str)
        return d.strftime("%a").upper()
    except Exception:
        return date_str


# ------------------------------------------------------------- config I/O ----
def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    else:
        cfg = {}
    cfg.setdefault("locations", list(DEFAULT_LOCATIONS))
    cfg.setdefault("units", "F")            # F or C
    cfg.setdefault("sd_path", "")           # SD card root, e.g. E:\ or /Volumes/PIPBOY
    cfg.setdefault("app_source", "local")   # "local" folder or "github" latest
    cfg.setdefault("app_source_dir", "")    # local app build folder ("" = bundled)
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print("  > config saved to %s" % CONFIG_PATH)


# --------------------------------------------------------------- geocoding ---
def geocode_search(query, count=8):
    # The Open-Meteo geocoder matches a single place name, not "City, ST".
    # Try the full string first, then retry on just the leading token.
    data = http_get_json(GEOCODE_URL, {
        "name": query, "count": count, "language": "en", "format": "json"})
    if not (data.get("results")) and "," in query:
        head = query.split(",")[0].strip()
        if head:
            data = http_get_json(GEOCODE_URL, {
                "name": head, "count": count, "language": "en", "format": "json"})
    results = []
    for r in data.get("results", []) or []:
        bits = [r.get("name")]
        if r.get("admin1"):
            bits.append(r["admin1"])
        if r.get("country"):
            bits.append(r["country"])
        results.append({
            "label": ", ".join([b for b in bits if b]),
            "name": (r.get("name") or "").upper(),
            "region": (r.get("admin1") or r.get("country") or "").upper(),
            "lat": r.get("latitude"),
            "lon": r.get("longitude"),
        })
    return results


# --------------------------------------------------------------- forecast ----
def fetch_location(loc, units):
    temp_unit = "fahrenheit" if units == "F" else "celsius"
    wind_unit = "mph" if units == "F" else "kmh"
    params = {
        "latitude": loc["lat"],
        "longitude": loc["lon"],
        "current": ",".join([
            "temperature_2m", "relative_humidity_2m", "apparent_temperature",
            "weather_code", "wind_speed_10m", "wind_direction_10m", "is_day",
        ]),
        "daily": ",".join([
            "weather_code", "temperature_2m_max", "temperature_2m_min",
            "precipitation_probability_max", "uv_index_max",
        ]),
        "temperature_unit": temp_unit,
        "wind_speed_unit": wind_unit,
        "timezone": "auto",
        "forecast_days": 5,
    }
    data = http_get_json(FORECAST_URL, params)
    cur = data.get("current", {}) or {}
    code = int(cur.get("weather_code", 0) or 0)

    out = {
        "name": loc.get("name") or "UNKNOWN",
        "region": loc.get("region") or "",
        "lat": round(loc["lat"], 4),
        "lon": round(loc["lon"], 4),
        "current": {
            "temp": cur.get("temperature_2m"),
            "feels": cur.get("apparent_temperature"),
            "code": code,
            "desc": WMO.get(code, "Unknown"),
            "wind": cur.get("wind_speed_10m"),
            "dir": deg_to_compass(cur.get("wind_direction_10m")),
            "humidity": cur.get("relative_humidity_2m"),
            "uv": (data.get("daily", {}).get("uv_index_max", [None]) or [None])[0],
            "is_day": int(cur.get("is_day", 1) or 0),
            "time": (cur.get("time") or "").replace("T", " "),
        },
        "daily": [],
    }

    d = data.get("daily", {}) or {}
    times = d.get("time", []) or []
    for i, date_str in enumerate(times):
        dcode = int((d.get("weather_code") or [0])[i] or 0)
        out["daily"].append({
            "d": weekday_label(date_str),
            "date": date_str,
            "hi": (d.get("temperature_2m_max") or [None])[i],
            "lo": (d.get("temperature_2m_min") or [None])[i],
            "code": dcode,
            "desc": WMO.get(dcode, "Unknown"),
            "pop": (d.get("precipitation_probability_max") or [None])[i],
        })
    return out


# ------------------------------------------------------------ space weather --
def _http_get_any(url):
    req = urllib.request.Request(url, headers={"User-Agent": "PipBoyWeather/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_space():
    """Pull solar-flare + geomagnetic activity from NOAA SWPC.

    Returns a dict (or None on failure) plus the forecast Kp peak used for
    aurora estimates.
    """
    space = {}
    kp_forecast_peak = 0.0

    # Current planetary Kp (list of dicts; last entry is most recent)
    try:
        rows = _http_get_any(SWPC_KP_NOW)
        space["kp_now"] = round(float(rows[-1]["Kp"]), 1)
    except Exception as e:
        print("    ! Kp now failed: %s" % e)

    # Kp forecast -> peak + a 3-day (3-hourly) predicted series for the graph
    try:
        rows = _http_get_any(SWPC_KP_FCST)
        series = []
        for r in rows:
            if str(r.get("observed", "")).lower() == "predicted":
                try:
                    series.append((r.get("time_tag", ""), float(r["kp"])))
                except Exception:
                    pass
        series = series[:24]                 # ~3 days at 3-hour spacing
        if series:
            kps = [k for _, k in series]
            kp_forecast_peak = max(kps)
            space["kp_peak"] = round(kp_forecast_peak, 1)
            space["kpf"] = [round(k, 1) for _, k in series]
            ticks = []
            for i, (t, _) in enumerate(series):
                if "T00:00" in t:            # midnight -> day boundary tick
                    try:
                        ticks.append({"i": i,
                                      "d": datetime.date.fromisoformat(
                                          t[:10]).strftime("%a").upper()})
                    except Exception:
                        pass
            space["kpf_ticks"] = ticks
    except Exception as e:
        print("    ! Kp forecast failed: %s" % e)

    # NOAA R/S/G scales for "today" (key "0")
    #   R = radio blackout (flares)  S = radiation storm  G = geomagnetic storm
    try:
        scales = _http_get_any(SWPC_SCALES)
        today = scales.get("0", {}) or {}
        r = today.get("R", {}) or {}
        s = today.get("S", {}) or {}
        g = today.get("G", {}) or {}
        space["r_scale"] = "R" + str(r.get("Scale") or 0)
        space["r_text"] = r.get("Text") or "None"
        space["s_scale"] = "S" + str(s.get("Scale") or 0)
        space["s_text"] = s.get("Text") or "None"
        space["g_scale"] = "G" + str(g.get("Scale") or 0)
        space["g_text"] = g.get("Text") or "None"
    except Exception as e:
        print("    ! scales failed: %s" % e)

    # Latest solar flare class (e.g. C3.2 / M1.0 / X2.1)
    try:
        fl = _http_get_any(SWPC_FLARE)
        if isinstance(fl, list) and fl:
            fl = fl[0]
        cls = fl.get("max_class") or fl.get("current_class")
        space["flare"] = cls or "None"
        t = fl.get("max_time") or fl.get("begin_time") or ""
        if t:
            space["flare_time"] = t.replace("T", " ")[:16]
    except Exception as e:
        print("    ! flare failed: %s" % e)

    if not space:
        return None, 0.0
    space["updated"] = datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    return space, max(kp_forecast_peak, space.get("kp_now", 0) or 0)


def aurora_for(lat, kp_peak):
    """Estimate aurora visibility at a latitude given the forecast Kp peak."""
    alat = abs(lat)
    # smallest Kp whose overhead-aurora latitude reaches this location
    needed = 10
    for kp in range(10):
        if KP_AURORA_LAT[kp] <= alat:
            needed = kp
            break
    if needed >= 10:
        chance = "UNLIKELY"          # too close to the equator at any Kp
    elif kp_peak >= needed:
        chance = "LIKELY"            # overhead at the forecast peak
    elif kp_peak >= needed - 2:
        chance = "POSSIBLE"          # within horizon reach
    else:
        chance = "UNLIKELY"
    return {
        "chance": chance,
        "needed": needed if needed < 10 else 9,
        "maxkp": round(kp_peak, 1),
    }


def build_payload(cfg):
    units = cfg["units"]
    now = datetime.datetime.now(datetime.timezone.utc)

    print("  > fetching NOAA SWPC space weather ...")
    space, kp_peak = fetch_space()

    locations = []
    for loc in cfg["locations"]:
        print("  > fetching %s ..." % loc.get("name"))
        try:
            entry = fetch_location(loc, units)
            entry["aurora"] = aurora_for(loc["lat"], kp_peak)
            locations.append(entry)
        except Exception as e:
            print("    ! failed: %s" % e)

    payload = {
        "v": 1,
        "generated": now.strftime("%Y-%m-%d %H:%M"),
        "epoch": int(now.timestamp()),       # UTC seconds, for stale detection
        "units": {"temp": units, "wind": "mph" if units == "F" else "kmh"},
        "locations": locations,
    }
    if space:
        payload["space"] = space
    return payload


def resolve_output(cfg):
    sd = (cfg.get("sd_path") or "").strip()
    if sd:
        return os.path.join(sd, "USER", "WEATHER.JSON")
    # fall back to a local file next to the script
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "WEATHER.JSON")


def write_payload(cfg, payload):
    out_path = resolve_output(cfg)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    size = os.path.getsize(out_path)
    print("\n  > wrote %d location(s), %d bytes -> %s"
          % (len(payload["locations"]), size, out_path))
    if size > DEVICE_JSON_LIMIT:
        print("    ! cache is large for the Pip-Boy app; remove locations and sync again")
    if not (cfg.get("sd_path") or "").strip():
        print("    (no SD path set - copy this file to <SD>/USER/WEATHER.JSON,")
        print("     or set one with menu option [5] / --sd)")


def repo_slug():
    """Best-effort 'owner/repo' from this checkout's git remote, else default."""
    try:
        with open(os.path.join(PROJECT_ROOT, ".git", "config"), "r",
                  encoding="utf-8") as f:
            m = re.search(r"github\.com[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?\s", f.read())
        if m:
            return m.group(1)
    except Exception:
        pass
    return GITHUB_DEFAULT_SLUG


def github_raw_base(branch=GITHUB_BRANCH):
    return "https://raw.githubusercontent.com/%s/%s" % (repo_slug(), branch)


def find_app_files(source_dir):
    """Locate the device app files inside a local folder.

    Accepts the project layout (<root>/pipboy/APPS/WEATHER.JS), the on-SD app
    layout (<root>/APPS/WEATHER.JS), or the files sitting directly in <root>.
    Returns [(abs_src, sd_rel_path)]; raises if any file is missing.
    """
    root = os.path.abspath(os.path.expanduser((source_dir or "").strip()))
    if not os.path.isdir(root):
        raise FileNotFoundError("App source folder not found: %s" % root)
    found, missing = [], []
    for repo_parts, sd_parts in APP_FILES:
        name = repo_parts[-1]
        candidates = [os.path.join(root, *repo_parts),
                      os.path.join(root, *sd_parts),
                      os.path.join(root, name)]
        src = next((c for c in candidates if os.path.isfile(c)), None)
        if src:
            found.append((src, os.path.join(*sd_parts)))
        else:
            missing.append(name)
    if missing:
        raise FileNotFoundError(
            "App source folder %s is missing: %s" % (root, ", ".join(missing)))
    return found


def download_app_files(branch=GITHUB_BRANCH):
    """Download the latest device app files from GitHub into a temp folder.

    Returns (files, tmpdir) where files is [(abs_src, sd_rel_path)]. The caller
    must remove tmpdir once the files have been installed.
    """
    base = github_raw_base(branch)
    tmp = tempfile.mkdtemp(prefix="pipboy_app_")
    print("  > source: latest from github.com/%s (%s)" % (repo_slug(), branch))
    files = []
    for repo_parts, sd_parts in APP_FILES:
        url = base + "/" + "/".join(repo_parts)
        dest = os.path.join(tmp, *sd_parts)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "PipBoyWeather/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        with open(dest, "wb") as f:
            f.write(data)
        print("  > downloaded %s (%d bytes)" % (repo_parts[-1], len(data)))
        files.append((dest, os.path.join(*sd_parts)))
    return files, tmp


def install_app_files(sd_path, files=None):
    """Copy device app files onto the SD card.

    `files` is [(abs_src, sd_rel_path)] from find_app_files / download_app_files;
    when omitted the bundled checkout is used. Returns
    [(dest, sd_rel, status, size)] where status is new / updated / unchanged.
    """
    sd = (sd_path or "").strip()
    if not sd:
        raise ValueError("Set the SD card root before installing app files.")
    sd = os.path.abspath(os.path.expanduser(sd))
    if not os.path.isdir(sd):
        raise FileNotFoundError("SD card root not found: %s" % sd)
    if files is None:
        files = find_app_files(PROJECT_ROOT)

    results = []
    for src, rel in files:
        with open(src, "rb") as f:
            data = f.read()
        dest = os.path.join(sd, rel)
        status = "new"
        if os.path.isfile(dest):
            try:
                with open(dest, "rb") as f:
                    status = "unchanged" if f.read() == data else "updated"
            except Exception:
                status = "updated"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        results.append((dest, rel, status, len(data)))
    return results


def uninstall_app_files(sd_path, remove_data=True):
    """Remove a previous install's files from the SD card.

    Deletes the app files and, when `remove_data` is set, every cached
    WEATHER.JSON variant the device app looks for. Shared folders
    (APPS/APPINFO/USER) are left in place since other apps may use them.
    Returns [(path, status)] where status is removed / absent / "error: ...".
    """
    sd = (sd_path or "").strip()
    if not sd:
        raise ValueError("Set the SD card root before cleaning up.")
    sd = os.path.abspath(os.path.expanduser(sd))
    if not os.path.isdir(sd):
        raise FileNotFoundError("SD card root not found: %s" % sd)

    rels = list(APP_FILE_REL)
    if remove_data:
        rels += DATA_FILE_REL

    results, seen = [], set()
    for rel in rels:
        dest = os.path.join(sd, rel)
        key = os.path.normcase(os.path.abspath(dest))  # dedupe FAT case-variants
        if key in seen:
            continue
        seen.add(key)
        if os.path.isfile(dest):
            try:
                os.remove(dest)
                results.append((dest, "removed"))
            except OSError as e:
                results.append((dest, "error: %s" % e))
        else:
            results.append((dest, "absent"))
    return results


def do_fetch(cfg):
    if not cfg["locations"]:
        print("  ! no locations configured. Add some first.")
        return
    payload = build_payload(cfg)
    if not payload["locations"]:
        print("  ! nothing fetched (check your connection).")
        return
    write_payload(cfg, payload)


# ------------------------------------------------------------ interactive ----
def print_locations(cfg):
    if not cfg["locations"]:
        print("  (none)")
        return
    for i, l in enumerate(cfg["locations"]):
        print("   %2d. %-22s %-20s (%.3f, %.3f)"
              % (i + 1, l.get("name", "?"), l.get("region", ""),
                 l.get("lat", 0), l.get("lon", 0)))


def menu_add(cfg):
    q = input("  Search location (city/place name): ").strip()
    if not q:
        return
    try:
        results = geocode_search(q)
    except Exception as e:
        print("  ! search failed: %s" % e)
        return
    if not results:
        print("  ! no matches.")
        return
    for i, r in enumerate(results):
        print("   %2d. %s  (%.3f, %.3f)" % (i + 1, r["label"], r["lat"], r["lon"]))
    sel = input("  Pick #: ").strip()
    if not sel.isdigit() or not (1 <= int(sel) <= len(results)):
        print("  ! cancelled.")
        return
    r = results[int(sel) - 1]
    name = input("  Display name [%s]: " % r["name"]).strip() or r["name"]
    region = input("  Region label [%s]: " % r["region"]).strip() or r["region"]
    cfg["locations"].append({
        "name": name.upper(), "region": region.upper(),
        "lat": r["lat"], "lon": r["lon"]})
    save_config(cfg)
    print("  > added %s" % name)


def menu_remove(cfg):
    print_locations(cfg)
    sel = input("  Remove #: ").strip()
    if sel.isdigit() and 1 <= int(sel) <= len(cfg["locations"]):
        removed = cfg["locations"].pop(int(sel) - 1)
        save_config(cfg)
        print("  > removed %s" % removed.get("name"))
    else:
        print("  ! cancelled.")


def menu_units(cfg):
    u = input("  Units [F/C] (current %s): " % cfg["units"]).strip().upper()
    if u in ("F", "C"):
        cfg["units"] = u
        save_config(cfg)


def menu_sd(cfg):
    print("  Set the SD card ROOT (e.g. E:\\ on Windows, /Volumes/PIPBOY on Mac).")
    print("  Leave blank to write WEATHER.JSON locally next to this script.")
    p = input("  SD path [%s]: " % (cfg.get("sd_path") or "")).strip()
    cfg["sd_path"] = p
    save_config(cfg)
    print("  > output will be: %s" % resolve_output(cfg))


def interactive(cfg):
    while True:
        print("\n==== PIP-BOY WEATHER COMPANION ====")
        print(" Locations (%d), units=%s" % (len(cfg["locations"]), cfg["units"]))
        print_locations(cfg)
        print(" Output: %s" % resolve_output(cfg))
        print("-----------------------------------")
        print("  [1] Fetch + write to SD")
        print("  [2] Add location")
        print("  [3] Remove location")
        print("  [4] Toggle units (F/C)")
        print("  [5] Set SD card path")
        print("  [q] Quit")
        choice = input(" > ").strip().lower()
        if choice == "1":
            do_fetch(cfg)
        elif choice == "2":
            menu_add(cfg)
        elif choice == "3":
            menu_remove(cfg)
        elif choice == "4":
            menu_units(cfg)
        elif choice == "5":
            menu_sd(cfg)
        elif choice in ("q", "quit", "exit"):
            break
        else:
            print("  ? unknown option")


# ------------------------------------------------------------------- main ----
def main():
    ap = argparse.ArgumentParser(description="Pip-Boy 3000 weather companion.")
    ap.add_argument("--fetch", action="store_true", help="fetch + write, no menu")
    ap.add_argument("--add", metavar="QUERY", help="add first geocode match for QUERY")
    ap.add_argument("--sd", metavar="PATH", help="set SD card root path")
    ap.add_argument("--units", choices=["F", "C"], help="temperature units")
    args = ap.parse_args()

    cfg = load_config()
    changed = False

    if args.sd is not None:
        cfg["sd_path"] = args.sd
        changed = True
    if args.units:
        cfg["units"] = args.units
        changed = True
    if args.add:
        try:
            res = geocode_search(args.add, count=1)
            if res:
                r = res[0]
                cfg["locations"].append({"name": r["name"], "region": r["region"],
                                         "lat": r["lat"], "lon": r["lon"]})
                changed = True
                print("  > added %s" % r["label"])
            else:
                print("  ! no match for %r" % args.add)
        except Exception as e:
            print("  ! add failed: %s" % e)

    if changed:
        save_config(cfg)

    if args.fetch:
        do_fetch(cfg)
        return
    if args.add or args.sd is not None or args.units:
        # config-only invocation; don't drop into the menu
        return

    interactive(cfg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  > aborted")
        sys.exit(1)
