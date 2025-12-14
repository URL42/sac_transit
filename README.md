# Sac Transit Pico W Display

FastAPI service plus a MicroPython client that shows Sacramento RT departures on a Pico W with a 20x4 I2C LCD. The server pulls static GTFS and GTFS-RT feeds, formats the next arrivals for a stop, and includes service alerts in a scrolling ticker.

## Inspiration
- Built after seeing Fil Bot's real-time BART display project: https://filbot.com/real-time-bart-display/

## Repo layout
- `transit_server.py` – FastAPI app that caches SacRT GTFS static data and GTFS-RT trip/alert feeds and exposes `/api/display`.
- `pico_w.py` – MicroPython code for the Pico W; writes to the LCD and polls the server on an interval.
- `secrets.py` – Fill this out and copy to the Pico W alongside `pico_w.py` (as `secrets.py`).

## Prerequisites
- Python 3.11+ on the machine running the API
- Recommended: create a venv (`python -m venv .venv` then `source .venv/bin/activate`)
- Install deps: `pip install -r requirements.txt`
- A Pico W flashed with MicroPython, wired to a PCF8574-based 20x4 I2C LCD (address `0x27`)

## Hardware
- Microcontroller: Raspberry Pi Pico W
- Display: 20x4 character LCD with I2C backpack (PCF8574) like this one: https://www.aliexpress.us/item/3256807136212215.html
- Backpack: PCF8574 backpack to simplify wiring: https://www.aliexpress.us/item/2251801620804933.html
- Notes: adjust the contrast dial on the backpack so the characters are visible; LCD address expected at `0x27`.

## License
Non-Commercial License (see `LICENSE`):
- Free to use, copy, modify, merge, publish, and distribute for personal, educational, or research purposes.
- Commercial use is prohibited without prior written permission.
- Include copyright and attribution in copies/derivatives.
- Provided “as is” without warranty.

## Run the API locally
Start the FastAPI server on a LAN-accessible IP so the Pico can reach it:
```bash
python -m uvicorn transit_server:app --host 0.0.0.0 --port 8088 --http h11
```

## API
- `GET /api/display?stop_id=STOP_ID&title=TITLE&route=ROUTE`  
  Returns JSON with the stop title, three lines of `"<route> <mins>"` strings (or `--`), and a ticker built from GTFS alerts. Optional `route` can be a route short name (e.g., `6`) or `route_id` to filter alerts to that route only.

Example response:
```json
{
  "title": "39th St WB",
  "lines": ["39th St WB", "6 3", "38 14", "102 22"],
  "ticker": "Bus stop closed at 39th..."
}
```

## Pico W setup
1) Flash MicroPython to the Pico W.  
2) Copy `pico_w.py` to the board as `main.py`.  
3) Copy `secrets.py`, update `WIFI_SSID/PASSWORD`, `SERVER_BASE` (use your machine's LAN IP and port), `STOP_ID` (from SacRT GTFS `stop_id`), and `TITLE`.  
   - Optional: set `ROUTE` to a route short name or `route_id` to filter alerts to that line.  
4) Power the Pico; it will connect to Wi‑Fi, poll `/api/display`, and render two departure lines plus the scrolling alert ticker.

## How it works
- Static GTFS is refreshed daily; GTFS-RT trips and alerts refresh every ~15 seconds.
- Arrivals are filtered to active `service_id`s for the current day when calendar data exists.
- LCD formatting rules: `<=1` minute shows `<NOW BOARDING>`, otherwise shows `"<mins> MIN"` right-aligned, with the route name on the left.
