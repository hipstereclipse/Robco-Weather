# Troubleshooting

Use this guide when the app does not appear, data does not load, syncing fails,
or the display looks wrong.

## App Does Not Appear in ITEMS > MISC

Likely causes:

- `APPINFO/WEATHER.info` is missing or in the wrong folder.
- `APPS/WEATHER.JS` is missing or in the wrong folder.
- The Pip-Boy has not been rebooted since copying the files.
- The SD card was not safely ejected and the file copy did not finish.

Fix:

1. Confirm the SD card contains:

   ```text
   APPS/WEATHER.JS
   APPINFO/WEATHER.info
   APPINFO/WEATHER.IMG
   ```

2. Reboot the Pip-Boy.
3. If it still does not appear, restore from backup and copy the files again.

## App Opens but Shows NO WEATHER DATA

The app files are installed, but no cache file was found.

Fix:

1. Run the companion and sync to the SD card.
2. Confirm this file exists:

   ```text
   USER/WEATHER.JSON
   ```

3. If you used manual copy, make sure the file is not named
   `WEATHER.JSON.txt`.

The app also checks `WEATHER.JSON` at the SD root and `USER/WEATHER.json`, but
`USER/WEATHER.JSON` is the normal path.

## App Shows BAD DATA FORMAT

The cache file exists but could not be parsed.

Fix:

1. Re-run the companion and sync again.
2. If editing by hand, validate the file:

   ```bash
   python -m json.tool path/to/WEATHER.JSON
   ```

3. Make sure the top-level object has a non-empty `locations` array.

## Pip-Boy Shows ERROR Errors: CALLBACK, LOW_MEMORY, MEMORY

The device ran out of Espruino runtime memory while loading or drawing the app.

Fix:

1. Install the current `APPS/WEATHER.JS`; it is sized to avoid the heavier
   renderer path that triggered this error.
2. Re-run the companion and sync again.
3. If the app shows `DATA TOO LARGE`, remove saved locations and sync again.
   The companion prints the generated cache size after each sync and warns when
   it is too large for the on-device app.

## App Shows EMPTY DATA FILE

The JSON parsed, but it had no usable locations.

Fix:

1. Open the companion.
2. Add at least one location.
3. Fetch and sync again.

## Stale Warning Will Not Go Away

The app shows a stale warning when the cache is older than `STALE_HOURS`,
currently 12 hours.

Fix:

1. Re-run the companion.
2. Confirm the sync wrote a new `USER/WEATHER.JSON`.
3. Reopen the app.

If the warning persists, the Pip-Boy clock may be wrong. The app compares the
cache `epoch` value against the device clock.

## Companion Cannot Search Locations

Likely causes:

- No internet connection on the companion device.
- Open-Meteo endpoint is temporarily unavailable.
- Query is too specific for the geocoder.

Fix:

- Try a simpler query such as `Boston` instead of `Boston, MA, USA`.
- Try the CLI and GUI to confirm the issue is not UI-specific.
- Wait and retry if the endpoint is unavailable.

## Companion Fetch Fails for One Location

The companion logs the failed location and continues. A location can fail if
the API returns incomplete data or the network drops during that request.

Fix:

1. Remove and re-add the location.
2. Run fetch again.
3. If other locations succeed, the app can still use the generated cache.

## GUI Does Not Start

Likely causes:

- Tkinter is missing from the Python install.
- The script is being run from an environment without display support.

Fix:

- Use the CLI:

  ```bash
  python companion/pipboy_weather.py
  ```

- Install a Python distribution that includes Tkinter if you want the GUI.

## Preview Renderer Fails

`companion/render_preview.py` requires Pillow.

Fix:

```bash
python -m pip install pillow
python companion/render_preview.py
```

The companion itself does not require Pillow.

## Text Looks Wrong on the Pip-Boy

Firmware builds can expose different graphics objects or font names.

Fix:

1. Open `pipboy/APPS/WEATHER.JS`.
2. Check the graphics resolution near the top:

   ```javascript
   var G = (typeof h !== "undefined") ? h
         : (typeof g !== "undefined") ? g
         : null;
   ```

3. Adjust `fontBig`, `fontHead`, `fontSmall`, and `fontTiny` for your firmware.

## App Layout Is Cropped

The layout is tuned for landscape, roughly 480 by 320 pixels. If your firmware
reports a different usable size, some text may need adjustment.

Fix:

- Confirm the app is running in landscape mode.
- Shorten location names and region labels.
- Adjust layout constants in `WEATHER.JS` if your firmware reports different
  dimensions.

## Aurora Looks Too Optimistic or Too Conservative

Aurora estimates use geographic latitude and forecast Kp. Real visibility
depends on geomagnetic latitude, cloud cover, moonlight, local light pollution,
and the direction of the auroral oval.

Treat `LIKELY`, `POSSIBLE`, and `UNLIKELY` as an in-universe helper rather than
a precise forecast.

## SD Path Is Wrong

The companion expects the SD card root, not the `USER` folder.

Use:

```text
E:\
/Volumes/PIPBOY
```

Do not use:

```text
E:\USER
/Volumes/PIPBOY/USER
```

The companion adds `USER/WEATHER.JSON` automatically.
