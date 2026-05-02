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
    try:
        i2c.writeto(ADDR, bytes([b]))
    except:
        pass # Ignore I2C errors during boot stabilization

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
    time.sleep_ms(5)

ROW_OFFSETS = [0x00, 0x40, 0x14, 0x54]
def set_cursor(col, row):
    col = max(0, min(19, col))
    row = max(0, min(3, row))
    cmd(0x80 | (ROW_OFFSETS[row] + col))

def putstr(s):
    for c in s:
        ch(c)

def init_lcd():
    # Wait for LCD controller to power up fully
    time.sleep_ms(200) 
    write4(0x03); time.sleep_ms(5)
    write4(0x03); time.sleep_ms(5)
    write4(0x03); time.sleep_ms(5)
    write4(0x02); time.sleep_ms(5)
    cmd(0x28) # 4-bit, 2-line, 5x8
    cmd(0x0C) # Display on, cursor off
    cmd(0x06) # Entry mode
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
    
    if not wlan.isconnected():
        write_row(2, "Connecting WiFi...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        
        # 15-second connection attempt loop
        for _ in range(15):
            if wlan.isconnected():
                return True
            time.sleep(1)
            
    return wlan.isconnected()


# ---------------- Formatting ----------------
def parse_route_mins(line):
    if not line or line == "--":
        return None, None
    parts = str(line).strip().split()
    if len(parts) < 2:
        return None, None
    route = parts[0]
    try:
        mins = int(parts[1])
    except:
        return None, None
    return route, mins

def format_board_line(route, mins, width=20):
    if route is None or mins is None:
        return "--"
    if mins < 0: mins = 0
    
    right = "<NOW BOARDING>" if mins <= 1 else f"{mins} MIN"
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


# ---------------- Main Execution ----------------

# 1. Hardware Init
init_lcd()
write_row(0, TITLE)
write_row(1, "System Booting...")

# 2. Persistent WiFi Connection
while True:
    if wifi_connect():
        break
    write_row(2, "WiFi Failed. Retry...")
    time.sleep(5)

wlan = network.WLAN(network.STA_IF)
write_row(1, "WiFi Connected")
write_row(2, f"IP: {wlan.ifconfig()[0]}")
time.sleep(2)

# 3. App Loop
ticker_frames = marquee_frames("Fetching data...")
last_fetch = 0

while True:
    now = time.time()

    # Network Fetch
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
            # If network fails, wait a bit before trying again
            time.sleep(5) 

        last_fetch = now

    # Update Marquee
    try:
        write_row(3, next(ticker_frames))
    except StopIteration:
        ticker_frames = marquee_frames("No alerts")
        
    time.sleep(SCROLL_DELAY_SEC)

