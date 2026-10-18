"""Gather every source for a location and date range, then score it."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date

from . import forecast
from .config import settings
from .fetcher import FetchBlocked, FetchFailed, PoliteFetcher
from .models import SourceCheck, to_jsonable, utcnow
from .sources.enrich import enrich_events
from .sources.geocode import geocode
from .sources.holidays import holiday_signals
from .sources.pageviews import seasonal_profile
from .sources.ticketmaster import ticketmaster_signals
from .sources.webpages import webpage_signals
from .sources.wikidata import wikidata_signals

MAX_DAYS = 366


class BadRequest(ValueError):
    pass


@dataclass
class ForecastRequest:
    location: str
    start: date
    end: date
    radius_km: int = 25
    source_urls: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.location.strip():
            raise BadRequest("Enter a city or address.")
        if self.end < self.start:
            raise BadRequest("End date is before start date.")
        if (self.end - self.start).days + 1 > MAX_DAYS:
            raise BadRequest(f"Pick a range of at most {MAX_DAYS} days.")
        if not 1 <= self.radius_km <= 200:
            raise BadRequest("Radius must be between 1 and 200 km.")


async def run_forecast(fetcher: PoliteFetcher, req: ForecastRequest, today: date | None = None) -> dict:
    req.validate()
    today = today or date.today()
    trace: list[SourceCheck] = []
    warnings: list[str] = []

    try:
        loc = await geocode(fetcher, req.location, trace)
    except (FetchBlocked, FetchFailed) as exc:
        raise BadRequest(f"Could not look up the location: {exc}") from exc

    if req.start < today:
        warnings.append("Part of the range is in the past; ticketing sources only list upcoming events.")
    if not settings.contact:
        warnings.append("SCRAPER_CONTACT is not set. Add an email or URL to .env so site operators can reach you.")

    results = await asyncio.gather(
        holiday_signals(fetcher, loc, req.start, req.end, trace),
        ticketmaster_signals(fetcher, loc, req.start, req.end, req.radius_km, settings.ticketmaster_api_key, trace),
        wikidata_signals(fetcher, loc, req.start, req.end, trace),
        webpage_signals(fetcher, req.source_urls, req.start, req.end, trace),
        seasonal_profile(fetcher, loc, today, trace),
        return_exceptions=True,
    )
    signals = []
    seasonal = None
    for name, result in zip(("holidays", "Ticketmaster", "Wikidata", "your web pages", "seasonality"), results):
        if isinstance(result, Exception):
            warnings.append(f"Source group '{name}' failed: {type(result).__name__}: {result}")
            trace.append(SourceCheck(name, "", "error", str(result)))
        elif name == "seasonality":
            seasonal = result
        else:
            signals.extend(result)

    try:
        await enrich_events(fetcher, loc, signals, req.radius_km, today, trace)
    except Exception as exc:  # sizing is a refinement; never lose the forecast over it
        warnings.append(f"Could not size events (venue capacity / artist popularity): {type(exc).__name__}: {exc}")
        trace.append(SourceCheck("event sizing", "", "error", str(exc)))

    signals = forecast.merge_duplicates(signals)
    signals.sort(key=lambda s: (s.start, -s.weight))
    days = forecast.score_days(signals, req.start, req.end, seasonal)
    periods = forecast.busy_periods(days, signals)

    if seasonal is None:
        warnings.append("No seasonal travel-interest data found; every month uses the same baseline.")

    return {
        "generated_at": utcnow(),
        "request": {"location": req.location, "start": req.start, "end": req.end, "radius_km": req.radius_km, "source_urls": req.source_urls},
        "location": loc,
        "model": {
            "baseline": forecast.BASELINE,
            "routine_by_weekday": {
                wd: round(v, 3)
                for wd, v in forecast.routine_by_weekday(
                    [(d.day, sum(dr.contribution for dr in d.drivers if signals[dr.signal_id].kind == "event")) for d in days]
                ).items()
            },
            "saturation": forecast.SATURATION,
            "levels": [{"min": t, "name": n} for t, n in forecast.LEVELS],
            "note": "Index of expected demand pressure from public signals (0-100). Not fitted to any hotel's bookings.",
        },
        "seasonal": seasonal,
        "signals": [{"id": i, **to_jsonable(s)} for i, s in enumerate(signals)],
        "days": days,
        "periods": periods,
        "sources": forecast.all_sources(signals) + ([seasonal.source] if seasonal else []) + [
            {"publisher": "OpenStreetMap Nominatim", "url": loc.source_url, "fetched_at": utcnow()}
        ],
        "source_log": trace,
        "warnings": warnings,
    }
