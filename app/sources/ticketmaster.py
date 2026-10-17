"""Ticketed events near the hotel from the Ticketmaster Discovery API.

Terms: https://developer.ticketmaster.com/support/terms-of-use/
Free tier limits: 5 requests/second, 5000/day, and no paging past item 1000.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from ..fetcher import FetchBlocked, FetchFailed, PoliteFetcher
from ..models import Location, Signal, Source, SourceCheck

API = "https://app.ticketmaster.com/discovery/v2/events.json"
PUBLISHER = "Ticketmaster"
PAGE_SIZE = 200
MAX_PAGES = 5  # 200 * 5 = API's 1000-item paging ceiling

# How strongly each kind of event tends to fill hotel rooms (impact units).
SEGMENT_WEIGHTS = {
    "Sports": 1.2,
    "Music": 1.0,
    "Arts & Theatre": 0.5,
    "Family": 0.5,
    "Film": 0.3,
    "Miscellaneous": 0.4,
}
DEFAULT_WEIGHT = 0.3
DISTANCE_SCALE_KM = 15.0

# Ticketmaster lists add-ons (parking, upgrades) as separate "events".
ADD_ON = re.compile(r"\b(parking|upgrade|vip package|add[- ]on|gift card|voucher|suite rental|tailgate pass)\b", re.I)


def distance_factor(km: float | None) -> float:
    if km is None:
        return 0.7
    return 1.0 / (1.0 + km / DISTANCE_SCALE_KM)


def parse_events(payload: dict, fetched_at: datetime) -> list[Signal]:
    signals = []
    for ev in (payload.get("_embedded") or {}).get("events", []):
        name = ev.get("name") or ""
        if ADD_ON.search(name):
            continue
        dates = ev.get("dates") or {}
        if (dates.get("status") or {}).get("code") in ("cancelled", "canceled", "postponed"):
            continue
        start_s = (dates.get("start") or {}).get("localDate")
        if not start_s:
            continue
        start = date.fromisoformat(start_s)
        end_s = (dates.get("end") or {}).get("localDate")
        end = date.fromisoformat(end_s) if end_s else start
        if end < start or (end - start).days > 30:  # season passes etc. — not a single event
            end = start

        cls = (ev.get("classifications") or [{}])[0]
        segment = (cls.get("segment") or {}).get("name")
        genre = (cls.get("genre") or {}).get("name")
        venue = ((ev.get("_embedded") or {}).get("venues") or [{}])[0]
        venue_name = venue.get("name")
        city = (venue.get("city") or {}).get("name")
        km = ev.get("distance")
        if km is not None and (ev.get("units") or "").upper().startswith("MI"):
            km = float(km) * 1.609

        weight = SEGMENT_WEIGHTS.get(segment or "", DEFAULT_WEIGHT) * distance_factor(km)
        category = " / ".join(x for x in (segment, genre) if x and x != "Undefined") or None
        where = ", ".join(x for x in (venue_name, city) if x)
        signals.append(
            Signal(
                kind="event",
                title=name,
                start=start,
                end=end,
                weight=weight,
                sources=[Source(PUBLISHER, ev.get("url") or "https://www.ticketmaster.com/", fetched_at)],
                category=category,
                venue=where or None,
                distance_km=round(float(km), 1) if km is not None else None,
                description=f"Ticketed {(segment or 'event').lower()} listing" + (f" at {where}" if where else "") + ".",
            )
        )
    return signals


async def ticketmaster_signals(
    fetcher: PoliteFetcher,
    loc: Location,
    start: date,
    end: date,
    radius_km: int,
    api_key: str,
    trace: list[SourceCheck],
) -> list[Signal]:
    if not api_key:
        trace.append(SourceCheck(PUBLISHER, API, "skipped", "set TICKETMASTER_API_KEY in .env to enable"))
        return []

    signals: list[Signal] = []
    for page in range(MAX_PAGES):
        params = {
            "apikey": api_key,
            "latlong": f"{loc.lat:.4f},{loc.lon:.4f}",
            "radius": radius_km,
            "unit": "km",
            "startDateTime": f"{start.isoformat()}T00:00:00Z",
            "endDateTime": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
            "size": PAGE_SIZE,
            "page": page,
            "sort": "date,asc",
        }
        try:
            res = await fetcher.get(API, source=PUBLISHER, params=params, kind="api", ttl=timedelta(hours=12), min_interval=0.25, trace=trace)
        except (FetchBlocked, FetchFailed):
            break
        payload = res.json()
        signals.extend(parse_events(payload, res.fetched_at))
        info = payload.get("page") or {}
        if info.get("number", page) + 1 >= info.get("totalPages", 0):
            break
    return signals
