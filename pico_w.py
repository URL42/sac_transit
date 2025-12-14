#Save this file on your pico w as main.py

import time
import network
import urequests
from machine import Pin, I2C

try:
    from secrets import (
        WIFI_SSID, WIFI_PASSWORD,
        SERVER_BASE, STOP_ID, TITLE,
        FETCH_EVERY_SEC, SCROLL_DELAY_SEC,
        ROUTE,
    )
except Exception as e:
    raise RuntimeError("Missing/invalid secrets.py") from e


# ---------------- LCD (PCF8574 @ 0x27) ----------------
i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=400000)
ADDR = 0x27

MASK_RS = 0x01
MASK_E  = 0x04
MASK_BL = 0x08

def i2c_write(b):
    i2c.writeto(ADDR, bytes([b]))

def pulse_enable(data):
    i2c_write(data | MASK_E)
    time.sleep_us(1)
    i2c_write(data & ~MASK_E)
    time.sleep_us(50)

def write4(nibble, rs=0, backlight=True):
    data = (nibble & 0x0F) << 4
    if rs:
        data |= MASK_RS
    if backlight:
        data |= MASK_BL
    i2c_write(data)
    pulse_enable(data)

def send(value, rs=0):
    write4((value >> 4) & 0x0F, rs=rs)
    write4(value & 0x0F, rs=rs)

def cmd(c):
    send(c, rs=0)

def ch(c):
    send(ord(c), rs=1)

def clear():
    cmd(0x01)
    time.sleep_ms(2)

ROW_OFFSETS = [0x00, 0x40, 0x14, 0x54]
def set_cursor(col, row):
    col = max(0, min(19, col))
    row = max(0, min(3, row))
    cmd(0x80 | (ROW_OFFSETS[row] + col))

def putstr(s):
    for c in s:
        ch(c)

def init_lcd():
    time.sleep_ms(50)
    write4(0x03); time.sleep_ms(5)
    write4(0x03); time.sleep_us(150)
    write4(0x03); time.sleep_us(150)
    write4(0x02); time.sleep_us(150)
    cmd(0x28)
    cmd(0x0C)
    cmd(0x06)
    clear()

def pad_right(s, width):
    s = "" if s is None else str(s)
    return s[:width] + (" " * max(0, width - len(s)))

def write_row(row, text):
    set_cursor(0, row)
    putstr(pad_right(text, 20))

def marquee_frames(text, width=20, pad="    "):
    base = "No alerts" if text is None else str(text)
    s = base + pad
    if len(s) <= width:
        fixed = pad_right(s, width)
        while True:
            yield fixed
    loop = s + s[:width]
    while True:
        for i in range(len(s)):
            yield loop[i:i+width]


# ---------------- WiFi ----------------
def wifi_connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    for _ in range(80):
        if wlan.isconnected():
            break
        time.sleep(0.25)
    return wlan


# ---------------- Formatting ----------------
def parse_route_mins(line):
    """
    Expecting 'Gold 9' from server.
    Returns (route, mins_int) or (None, None).
    """
    if not line or line == "--":
        return None, None

    parts = str(line).strip().split()
    if len(parts) < 2:
        return None, None

    route = parts[0]
    try:
        mins = int(parts[1])
    except Exception:
        return None, None

    return route, mins

def format_board_line(route, mins, width=20):
    """
    Route on left. Right-aligned status/mins on right.

    Rule:
      mins <= 1  => '<NOW BOARDING>'
      else       => '9 MIN'
    """
    if route is None or mins is None:
        return "--"

    # clamp weird negatives
    if mins < 0:
        mins = 0

    if mins <= 1:
        right = "<NOW BOARDING>"
    else:
        right = f"{mins} MIN"

    left_width = max(0, width - len(right))
    left = pad_right(route, left_width)
    return (left + right)[:width]


# ---------------- HTTP ----------------
def fetch_payload():
    route_q = f"&route={ROUTE}" if ROUTE else ""
    url = f"{SERVER_BASE}/api/display?stop_id={STOP_ID}{route_q}"
    r = urequests.get(url)
    try:
        return r.json()
    finally:
        r.close()


# ---------------- Main loop ----------------
init_lcd()

write_row(0, TITLE)
write_row(1, "Booting...")
write_row(2, "WiFi...")
write_row(3, "Booting...")

wlan = wifi_connect()
if wlan.isconnected():
    write_row(2, f"IP {wlan.ifconfig()[0]}")
else:
    write_row(2, "WiFi FAILED")

ticker_frames = marquee_frames("Booting...")
last_fetch = 0

while True:
    now = time.time()

    if (now - last_fetch) >= FETCH_EVERY_SEC:
        try:
            payload = fetch_payload()
            lines = payload.get("lines", [TITLE, "--", "--", "--"])
            ticker = payload.get("ticker", "No alerts")

            write_row(0, TITLE)

            r1, m1 = parse_route_mins(lines[1])
            r2, m2 = parse_route_mins(lines[2])

            write_row(1, format_board_line(r1, m1))
            write_row(2, format_board_line(r2, m2))

            ticker_frames = marquee_frames(ticker)

        except Exception as e:
            write_row(1, "Fetch error")
            write_row(2, str(e)[:20])

        last_fetch = now

    write_row(3, next(ticker_frames))
    time.sleep(SCROLL_DELAY_SEC)
