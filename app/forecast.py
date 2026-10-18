"""Turn sourced signals into a daily demand index (0-100).

The model is deliberately simple and explainable:

  baseline(day) = BASELINE * seasonal factor for that month (Wikimedia pageviews)
  pressure(day) = sum of the weights of every signal covering that day
                  + ARRIVAL_SHARE of the weight of big events starting tomorrow
                    (guests check in the night before)
                  - the routine event load (median for that weekday in the range),
                    so a city's normal nightly shows don't read as "busy"
  index(day)    = baseline + (100 - baseline) * (1 - exp(-pressure / SATURATION))

So each extra event pushes the index up, but with diminishing returns, and a
day with no signals sits at its seasonal baseline. Every point above baseline
traces back to signals that carry source links.

Weights are rough priors, not fitted to any hotel's bookings — this is an
early-warning tool for "look closer at these dates", not a booking forecast.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from .models import Signal, Source
from .sources.pageviews import SeasonalProfile

BASELINE = 40.0
SATURATION = 3.0
ARRIVAL_SHARE = 0.4
ARRIVAL_MIN_WEIGHT = 0.9  # only events big enough to draw overnight visitors
ROUTINE_MIN_DAYS = 14  # need this many days to judge what a "typical" day's event load is
ROUTINE_WEEKDAY_MIN_DAYS = 28  # ...and this many to judge it per weekday (4+ of each)
SEASONAL_CLAMP = (0.6, 1.6)

LEVELS = [(70, "Very busy"), (52, "Busy"), (35, "Normal"), (0, "Quiet")]


def level_for(score: float) -> str:
    return next(name for threshold, name in LEVELS if score >= threshold)


@dataclass
class Driver:
    signal_id: int
    contribution: float  # impact units on this day
    role: str  # "on the day" | "arrival night"


@dataclass
class DayForecast:
    day: date
    score: float
    level: str
    baseline: float
    seasonal_factor: float
    pressure: float
    drivers: list[Driver] = field(default_factory=list)
    routine_excluded: float = 0.0  # event load treated as an ordinary day's background


@dataclass
class Period:
    start: date
    end: date
    peak_score: float
    peak_day: date
    level: str
    summary: str
    signal_ids: list[int]


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def merge_duplicates(signals: list[Signal]) -> list[Signal]:
    """Same event reported by several sources -> one signal with all sources."""
    merged: dict[tuple, Signal] = {}
    for sig in signals:
        key = (sig.kind, _norm(sig.title), sig.start)
        if key not in merged:
            merged[key] = Signal(**{
                **sig.__dict__,
                "sources": list(sig.sources),
                "adjustments": list(sig.adjustments),
                "performers": list(sig.performers),
            })
            continue
        existing = merged[key]
        seen = {s.url for s in existing.sources}
        existing.sources.extend(s for s in sig.sources if s.url not in seen)
        if sig.weight > existing.weight:
            # Keep the stronger report's weight together with the adjustments that explain it.
            existing.weight, existing.base_weight = sig.weight, sig.base_weight
            existing.adjustments = list(sig.adjustments)
        existing.end = max(existing.end, sig.end)
        existing.venue = existing.venue or sig.venue
        existing.category = existing.category or sig.category
        if existing.distance_km is None:
            existing.distance_km = sig.distance_km
    return list(merged.values())


def score_days(signals: list[Signal], start: date, end: date, seasonal: SeasonalProfile | None) -> list[DayForecast]:
    raw = []
    d = start
    while d <= end:
        factor = 1.0
        if seasonal:
            factor = min(max(seasonal.factor(d), SEASONAL_CLAMP[0]), SEASONAL_CLAMP[1])
        drivers: list[Driver] = []
        for i, sig in enumerate(signals):
            if sig.covers(d):
                drivers.append(Driver(i, sig.weight, "on the day"))
            elif sig.kind == "event" and sig.weight >= ARRIVAL_MIN_WEIGHT and sig.start == d + timedelta(days=1):
                drivers.append(Driver(i, round(sig.weight * ARRIVAL_SHARE, 3), "arrival night"))
        drivers.sort(key=lambda dr: dr.contribution, reverse=True)
        event_load = sum(dr.contribution for dr in drivers if signals[dr.signal_id].kind == "event")
        other_load = sum(dr.contribution for dr in drivers) - event_load
        raw.append((d, factor, drivers, event_load, other_load))
        d += timedelta(days=1)

    routine = routine_by_weekday([(r[0], r[3]) for r in raw])
    days = []
    for d, factor, drivers, event_load, other_load in raw:
        baseline = BASELINE * factor
        excluded = min(event_load, routine[d.weekday()])
        pressure = other_load + event_load - excluded
        score = baseline + (100 - baseline) * (1 - math.exp(-pressure / SATURATION))
        days.append(DayForecast(
            d, round(score, 1), level_for(score), round(baseline, 1), round(factor, 3), round(pressure, 3), drivers, round(excluded, 3)
        ))
    return days


def routine_by_weekday(loads: list[tuple[date, float]]) -> dict[int, float]:
    """Routine event load for each weekday (0=Mon).

    With 4+ weeks of data each weekday is compared with its own kind (a
    Saturday with the typical Saturday), because many cities have far more
    shows at weekends. With 2-4 weeks one median covers all days; with less,
    nothing is subtracted.
    """
    if len(loads) >= ROUTINE_WEEKDAY_MIN_DAYS:
        return {wd: statistics.median(v for d, v in loads if d.weekday() == wd) for wd in range(7)}
    overall = routine_event_load([v for _, v in loads])
    return {wd: overall for wd in range(7)}


def routine_event_load(daily_event_loads: list[float]) -> float:
    """The event load of a typical day in the range (median), treated as part of the baseline.

    In a city with shows every night, that steady background is what "normal"
    looks like; only event pressure above it should push a day toward busy.
    Short ranges don't have enough days to say what's typical, so nothing is
    subtracted there.
    """
    if len(daily_event_loads) < ROUTINE_MIN_DAYS:
        return 0.0
    return statistics.median(daily_event_loads)


def busy_periods(days: list[DayForecast], signals: list[Signal], min_level: str = "Busy", max_periods: int = 12) -> list[Period]:
    threshold = next(t for t, name in LEVELS if name == min_level)
    periods: list[list[DayForecast]] = []
    current: list[DayForecast] = []
    for day in days:
        if day.score >= threshold:
            current.append(day)
        elif current:
            periods.append(current)
            current = []
    if current:
        periods.append(current)

    out = []
    for run in periods:
        peak = max(run, key=lambda x: x.score)
        totals: dict[int, float] = {}
        for day in run:
            for dr in day.drivers:
                totals[dr.signal_id] = totals.get(dr.signal_id, 0) + dr.contribution
        ranked = sorted(totals, key=totals.get, reverse=True)
        top = [signals[i] for i in ranked[:3]]
        names = [s.title for s in top]
        more = len(ranked) - len(top)
        span = peak.day.strftime("%a %b %d") if len(run) == 1 else f"{run[0].day:%a %b %d} – {run[-1].day:%a %b %d}"
        summary = f"{span}: {level_for(peak.score).lower()} (peak {peak.score:.0f}/100 on {peak.day:%a %b %d})"
        if names:
            summary += ", driven by " + "; ".join(names) + (f" and {more} more signal{'s' * (more != 1)}" if more > 0 else "")
        out.append(Period(run[0].day, run[-1].day, peak.score, peak.day, level_for(peak.score), summary + ".", ranked))
    out.sort(key=lambda p: p.peak_score, reverse=True)
    return out[:max_periods]


def all_sources(signals: list[Signal]) -> list[Source]:
    seen: dict[str, Source] = {}
    for sig in signals:
        for s in sig.sources + [src for adj in sig.adjustments for src in adj.sources]:
            seen.setdefault(s.url, s)
    return list(seen.values())
