import io
import zipfile
import time
from dataclasses import dataclass
from typing import List, Optional, Set
from datetime import datetime, date

import httpx
import pandas as pd
import pytz
from fastapi import FastAPI, Query
from google.transit import gtfs_realtime_pb2

app = FastAPI(title="Sac Transit Display Server")

PACIFIC = pytz.timezone("America/Los_Angeles")

# -------------------------
# Feeds
# -------------------------
GTFS_ZIP_URL = "https://iportal.sacrt.com/gtfs/srtd/google_transit.zip"
GTFSRT_TRIPS_URL = "https://bustime.sacrt.com/gtfsrt/trips"
GTFSRT_ALERTS_URL = "https://bustime.sacrt.com/gtfsrt/alerts"

GTFS_REFRESH_SECONDS = 24 * 3600
RT_REFRESH_SECONDS = 15


# -------------------------
# Cache
# -------------------------
@dataclass
class Cache:
    gtfs_loaded_at: float = 0
    stops: Optional[pd.DataFrame] = None
    stop_times: Optional[pd.DataFrame] = None
    trips: Optional[pd.DataFrame] = None
    routes: Optional[pd.DataFrame] = None
    calendar: Optional[pd.DataFrame] = None
    calendar_dates: Optional[pd.DataFrame] = None

    rt_loaded_at: float = 0
    trip_updates: Optional[gtfs_realtime_pb2.FeedMessage] = None
    alerts: Optional[gtfs_realtime_pb2.FeedMessage] = None


cache = Cache()


# -------------------------
# Helpers
# -------------------------
async def fetch_bytes(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


async def ensure_gtfs_loaded():
    now = time.time()
    if cache.stops is not None and (now - cache.gtfs_loaded_at) < GTFS_REFRESH_SECONDS:
        return

    print("Loading static GTFS…")
    zbytes = await fetch_bytes(GTFS_ZIP_URL)
    z = zipfile.ZipFile(io.BytesIO(zbytes))

    def read_csv(name: str) -> Optional[pd.DataFrame]:
        try:
            with z.open(name) as f:
                return pd.read_csv(f)
        except KeyError:
            return None

    cache.stops = read_csv("stops.txt")
    cache.stop_times = read_csv("stop_times.txt")
    cache.trips = read_csv("trips.txt")
    cache.routes = read_csv("routes.txt")
    cache.calendar = read_csv("calendar.txt")
    cache.calendar_dates = read_csv("calendar_dates.txt")

    cache.gtfs_loaded_at = now
    print("GTFS loaded")


async def ensure_rt_loaded():
    now = time.time()
    if cache.alerts is not None and (now - cache.rt_loaded_at) < RT_REFRESH_SECONDS:
        return

    print("Loading GTFS-RT (alerts + trips)…")
    trips_bin = await fetch_bytes(GTFSRT_TRIPS_URL)
    alerts_bin = await fetch_bytes(GTFSRT_ALERTS_URL)

    tu = gtfs_realtime_pb2.FeedMessage()
    tu.ParseFromString(trips_bin)

    al = gtfs_realtime_pb2.FeedMessage()
    al.ParseFromString(alerts_bin)

    cache.trip_updates = tu
    cache.alerts = al
    cache.rt_loaded_at = now

    print(f"GTFS-RT loaded: trips={len(tu.entity)}, alerts={len(al.entity)}")


def _weekday_col(d: date) -> str:
    return [
        "monday", "tuesday", "wednesday",
        "thursday", "friday", "saturday", "sunday"
    ][d.weekday()]


def active_service_ids_for_today() -> Set[str]:
    today = datetime.now(PACIFIC).date()
    today_int = int(today.strftime("%Y%m%d"))
    active: Set[str] = set()

    cal = cache.calendar
    cald = cache.calendar_dates

    # calendar.txt
    if cal is not None and not cal.empty:
        wdcol = _weekday_col(today)
        c = cal.copy()

        c["start_date"] = pd.to_numeric(c["start_date"], errors="coerce").fillna(0).astype(int)
        c["end_date"] = pd.to_numeric(c["end_date"], errors="coerce").fillna(0).astype(int)

        in_range = c[(c["start_date"] <= today_int) & (c["end_date"] >= today_int)]

        if wdcol in in_range.columns:
            in_range[wdcol] = pd.to_numeric(in_range[wdcol], errors="coerce").fillna(0).astype(int)
            in_range = in_range[in_range[wdcol] == 1]

        active |= set(in_range["service_id"].astype(str).tolist())

    # calendar_dates.txt
    if cald is not None and not cald.empty:
        cd = cald.copy()
        cd["date"] = pd.to_numeric(cd["date"], errors="coerce").fillna(0).astype(int)
        cd["exception_type"] = pd.to_numeric(cd["exception_type"], errors="coerce").fillna(0).astype(int)

        today_rows = cd[cd["date"] == today_int]

        for _, r in today_rows.iterrows():
            sid = str(r["service_id"])
            et = int(r["exception_type"])
            if et == 1:
                active.add(sid)
            elif et == 2:
                active.discard(sid)

    return active


def _gtfs_time_to_seconds(t: str) -> int:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _now_service_seconds() -> int:
    now = datetime.now(PACIFIC)
    return now.hour * 3600 + now.minute * 60 + now.second


def next_scheduled_arrivals_for_stop(stop_id: str, limit: int = 3) -> List[str]:
    """
    Returns strings like 'Gold 9' (route + minutes) so the Pico can format it.
    """
    if cache.stop_times is None or cache.trips is None or cache.routes is None:
        return []

    st = cache.stop_times
    trips = cache.trips
    routes = cache.routes

    active_sids = active_service_ids_for_today()

    st2 = st[st["stop_id"].astype(str) == str(stop_id)].copy()
    if st2.empty:
        return []

    st2["dep"] = st2["departure_time"].fillna(st2["arrival_time"])
    st2 = st2.dropna(subset=["dep"])
    st2["dep_sec"] = st2["dep"].map(_gtfs_time_to_seconds)

    now_sec = _now_service_seconds()
    horizon = now_sec + 4 * 3600

    upcoming = st2[(st2["dep_sec"] >= now_sec) & (st2["dep_sec"] <= horizon)].copy()
    if upcoming.empty:
        upcoming = st2[st2["dep_sec"] >= now_sec].copy()
    if upcoming.empty:
        return []

    needed_cols = ["trip_id", "route_id"]
    if "service_id" in trips.columns:
        needed_cols.append("service_id")

    upcoming = upcoming.merge(trips[needed_cols], on="trip_id", how="left")

    if active_sids and "service_id" in upcoming.columns:
        filtered = upcoming[upcoming["service_id"].astype(str).isin(active_sids)]
        if not filtered.empty:
            upcoming = filtered

    upcoming = upcoming.merge(
        routes[["route_id", "route_short_name", "route_long_name"]],
        on="route_id",
        how="left",
    )

    def route_name(row):
        sn = str(row.get("route_short_name") or "").strip()
        if sn:
            return sn
        ln = str(row.get("route_long_name") or "").strip()
        return ln if ln else str(row.get("route_id") or "route?")

    upcoming["route"] = upcoming.apply(route_name, axis=1)
    upcoming = upcoming.sort_values("dep_sec")

    seen_dep = set()
    rows = []
    for _, r in upcoming.iterrows():
        dep_sec = int(r["dep_sec"])
        if dep_sec in seen_dep:
            continue
        seen_dep.add(dep_sec)
        rows.append(r)
        if len(rows) >= limit:
            break

    out = []
    for r in rows:
        mins = max(0, int((int(r["dep_sec"]) - now_sec) // 60))
        out.append(f"{r['route']} {mins}")

    return out


def _route_ids_for_short_name(short_name: Optional[str]) -> Optional[Set[str]]:
    if not short_name or cache.routes is None or cache.routes.empty:
        return None

    sn = str(short_name).strip().lower()
    if not sn:
        return None

    routes = cache.routes.copy()
    routes["route_short_name"] = routes["route_short_name"].astype(str).str.strip().str.lower()
    routes["route_id"] = routes["route_id"].astype(str)

    matched = routes[routes["route_short_name"] == sn]
    if matched.empty:
        # Allow passing an actual route_id as the filter as a fallback.
        matched = routes[routes["route_id"].str.lower() == sn]

    if matched.empty:
        return set()

    return set(matched["route_id"].tolist())


def _alert_applies_to_routes(alert: gtfs_realtime_pb2.Alert, allowed_route_ids: Optional[Set[str]]) -> bool:
    if allowed_route_ids is None:
        return True

    for ent in alert.informed_entity:
        rid = str(ent.route_id or "").strip()
        if rid and rid in allowed_route_ids:
            return True
    return False


def get_alert_text(route_filter: Optional[str] = None, max_len: int = 160) -> str:
    if not cache.alerts:
        return "No alerts"

    allowed_route_ids = _route_ids_for_short_name(route_filter)

    msgs: List[str] = []
    for ent in cache.alerts.entity:
        if not ent.HasField("alert"):
            continue
        alert = ent.alert
        if not _alert_applies_to_routes(alert, allowed_route_ids):
            continue
        txt = ""
        if alert.header_text and alert.header_text.translation:
            txt = alert.header_text.translation[0].text.strip()
        elif alert.description_text and alert.description_text.translation:
            txt = alert.description_text.translation[0].text.strip()
        if txt:
            msgs.append(txt)

    if not msgs:
        return "No alerts"

    out = " | ".join(msgs)
    return out[:max_len] + ("…" if len(out) > max_len else "")


# -------------------------
# API
# -------------------------
@app.get("/")
async def root():
    return {"ok": True}


@app.get("/api/display")
async def display(
    stop_id: str = Query(...),
    title: str = Query("39th St WB"),
    route: Optional[str] = Query(
        None,
        description="Route short name or route_id; filters alerts to this route if provided.",
    ),
):
    await ensure_gtfs_loaded()
    await ensure_rt_loaded()

    arrivals = next_scheduled_arrivals_for_stop(stop_id, limit=3)
    while len(arrivals) < 3:
        arrivals.append("--")

    return {
        "title": title,
        "lines": [title, arrivals[0], arrivals[1], arrivals[2]],
        "ticker": get_alert_text(route_filter=route),
    }
