# Companion App

The companion is responsible for all network access. It fetches weather data,
fetches NOAA space-weather data, estimates aurora visibility for each location,
and writes a compact `WEATHER.JSON` cache that the Pip-Boy can read offline.

The companion has two front ends over the same engine:

- `companion/pipboy_weather_gui.py`: Tkinter GUI, recommended for normal use.
- `companion/pipboy_weather.py`: interactive and scriptable CLI.

## Runtime Requirements

- Python 3.
- Tkinter for the GUI. If Tkinter is unavailable, use the CLI.
- Internet access during `fetch`.
- No runtime package installs are required for fetching and syncing.

The preview renderer is separate and requires Pillow. The main companion does
not.

## Graphical Workflow

Run:

```bash
python companion/pipboy_weather_gui.py
```

The GUI lets you:

- Search for locations through Open-Meteo geocoding.
- Add selected search results to the saved list.
- Reorder saved locations.
- Remove saved locations.
- Switch units between `F` and `C`.
- Choose the SD card root with a folder picker.
- Install or update the Pip-Boy app files and write fresh weather data to a
  selected SD card.
- Fetch Open-Meteo weather plus NOAA SWPC space weather and sync the cache to
  the configured SD card.
- Watch progress in the built-in terminal pane.

The GUI writes settings through the same config file as the CLI, so you can
move between them freely.

## Interactive CLI

Run:

```bash
python companion/pipboy_weather.py
```

The menu supports:

- Fetch and write to the configured output path.
- Add a location by search.
- Remove a location.
- Toggle units.
- Set the SD card root.

Use the CLI when running from a terminal-only machine, a phone Python
environment, or a desktop Python install without Tkinter.

## Scripted CLI

The CLI can also be used non-interactively:

```bash
python companion/pipboy_weather.py --sd E:\ --fetch
python companion/pipboy_weather.py --sd /Volumes/PIPBOY --fetch
python companion/pipboy_weather.py --add "Goodsprings, NV"
python companion/pipboy_weather.py --units C --fetch
```

Options can be combined. For example, this sets the SD path, switches to
Celsius, and writes a fresh cache:

```bash
python companion/pipboy_weather.py --sd E:\ --units C --fetch
```

## Configuration

The companion stores local settings in:

```text
companion/weather_config.json
```

That file is intentionally ignored by git because it is machine-specific. It
contains:

- `locations`: saved locations, including display name, region, latitude, and
  longitude.
- `units`: `F` or `C`.
- `sd_path`: SD card root, or an empty string for local output.

On first run, the companion supplies Fallout-flavored defaults:

- `GOODSPRINGS`
- `NEW VEGAS`
- `CAPITAL WASTELAND`
- `THE COMMONWEALTH`

These defaults make it possible to fetch immediately, even before adding your
own locations.

## Output Path

When `sd_path` is set, output goes to:

```text
<sd_path>/USER/WEATHER.JSON
```

When `sd_path` is blank, output goes to:

```text
companion/WEATHER.JSON
```

The local fallback lets you copy the cache manually to the SD card later.

## Device Install

In the GUI, press `INSTALL / UPDATE DEVICE` and select the Pip-Boy SD card
root. The installer copies the packaged Pip-Boy app files to:

```text
<sd_path>/APPS/WEATHER.JS
<sd_path>/APPINFO/WEATHER.info
<sd_path>/APPINFO/WEATHER.IMG
```

It then fetches Open-Meteo weather plus NOAA SWPC space weather and writes:

```text
<sd_path>/USER/WEATHER.JSON
```

Use `FETCH WEATHER + SPACE WX` later when the app is already installed and
only the cached data needs to be refreshed.

## Data Sources

The companion uses free public endpoints and no API keys:

- Open-Meteo geocoding API for place search.
- Open-Meteo forecast API for current conditions, daily forecast, humidity,
  wind, apparent temperature, and UV index.
- NOAA Space Weather Prediction Center for current Kp, Kp forecast, R/S/G
  scales, and latest flare class.

If one space-weather endpoint fails, the companion keeps any space data it can
fetch. If a location fails, it logs the failure and continues with the remaining
locations.

## Location Handling

The geocoder searches the full query first. If a comma-separated query returns
no results, the companion retries using the leading place name. This helps with
inputs such as:

```text
Goodsprings, NV
Boston, MA
Washington, DC
```

Saved display names and region labels are stored uppercase so they fit the
Pip-Boy UI style.

## Units

`F` uses:

- Fahrenheit temperatures.
- Miles per hour wind.

`C` uses:

- Celsius temperatures.
- Kilometers per hour wind.

The unit choice is stored in the generated JSON so the Pip-Boy app does not
need to infer it.

## Phone Use

The engine uses the Python standard library, so it can run in many phone Python
environments. The GUI requires Tkinter and is usually desktop-only. On phones,
use the CLI or script commands and then transfer `WEATHER.JSON` to the SD card.
