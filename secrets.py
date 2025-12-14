# Save this file on your pico as secrets.py

# secrets.py
# -------------------------
# WiFi
# -------------------------

WIFI_SSID = "SSID"
WIFI_PASSWORD = "PASSWORD"


# -------------------------
# Transit display config
# -------------------------

# MUST be your Mac/server LAN IP (not localhost)
SERVER_BASE = "http://192.168.1.XXX:8088"

STOP_ID = "1111"
TITLE = "Whatever stop name or title you want"
# Optional: limit alerts to a specific SacRT route (short name or route_id)
ROUTE = None

# -------------------------
# Timing (seconds)
# -------------------------
FETCH_EVERY_SEC = 20
SCROLL_DELAY_SEC = 0.20
