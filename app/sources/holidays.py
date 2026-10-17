"""Public holidays and long weekends from the Nager.Date API (free, no key)."""

from __future__ import annotations

from datetime import date, timedelta

from ..fetcher import FetchBlocked, FetchFailed, PoliteFetcher
from ..models import Location, Signal, Source, SourceCheck

API = "https://date.nager.at/api/v3"
PUBLISHER = "Nager.Date public holiday API"

# Demand impact units (see forecast.py). Holidays mostly move leisure travel;
# long weekends are when people actually take trips.
HOLIDAY_WEIGHT = 0.8
LONG_WEEKEND_WEIGHT = 1.0


def _applies(holiday: dict, subdivision: str | None) -> bool:
    if holiday.get("global", True):
        return True
    counties = holiday.get("counties") or []
    return subdivision is not None and subdivision in counties


async def holiday_signals(
    fetcher: PoliteFetcher, loc: Location, start: date, end: date, trace: list[SourceCheck]
) -> list[Signal]:
    if not loc.country_code:
        trace.append(SourceCheck(PUBLISHER, API, "skipped", "location has no country code"))
        return []

    signals: list[Signal] = []
    for year in range(start.year, end.year + 1):
        holidays_url = f"{API}/PublicHolidays/{year}/{loc.country_code}"
        try:
            res = await fetcher.get(holidays_url, source=PUBLISHER, kind="api", ttl=timedelta(days=7), min_interval=0.5, trace=trace)
        except (FetchBlocked, FetchFailed):
            continue
        src = Source(PUBLISHER, holidays_url, res.fetched_at)
        for h in res.json():
            day = date.fromisoformat(h["date"])
            if not (start <= day <= end) or not _applies(h, loc.subdivision_code):
                continue
            scope = "nationwide" if h.get("global", True) else f"regional ({loc.subdivision_code})"
            signals.append(
                Signal(
                    kind="holiday",
                    title=h.get("name") or h.get("localName") or "Public holiday",
                    start=day,
                    end=day,
                    weight=HOLIDAY_WEIGHT,
                    sources=[src],
                    category="Public holiday",
                    description=f"{h.get('localName', '')} — {scope} public holiday in {loc.country_code}.",
                )
            )

        weekends_url = f"{API}/LongWeekend/{year}/{loc.country_code}"
        try:
            res = await fetcher.get(weekends_url, source=PUBLISHER, kind="api", ttl=timedelta(days=7), min_interval=0.5, trace=trace)
        except (FetchBlocked, FetchFailed):
            continue
        src = Source(PUBLISHER, weekends_url, res.fetched_at)
        for lw in res.json():
            lw_start, lw_end = date.fromisoformat(lw["startDate"]), date.fromisoformat(lw["endDate"])
            if lw_end < start or lw_start > end:
                continue
            bridge = " (needs a bridge day off)" if lw.get("needBridgeDay") else ""
            signals.append(
                Signal(
                    kind="long_weekend",
                    title=f"{lw.get('dayCount', (lw_end - lw_start).days + 1)}-day long weekend{bridge}",
                    start=lw_start,
                    end=lw_end,
                    weight=LONG_WEEKEND_WEIGHT * (0.6 if lw.get("needBridgeDay") else 1.0),
                    sources=[src],
                    category="Travel period",
                    description=f"Nationwide long weekend in {loc.country_code}, {lw_start:%a %b %d} – {lw_end:%a %b %d}.",
                )
            )
    return signals
