"""Turn sourced signals into a daily demand index (0-100).

The model is deliberately simple and explainable:

  baseline(day) = BASELINE * seasonal factor for that month (Wikimedia pageviews)
  pressure(day) = sum of the weights of every signal covering that day
                  + ARRIVAL_SHARE of the weight of big events starting tomorrow
                    (guests check in the night before)
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
from dataclasses import dataclass, field
from datetime import date, timedelta

from .models import Signal, Source
from .sources.pageviews import SeasonalProfile

BASELINE = 40.0
SATURATION = 3.0
ARRIVAL_SHARE = 0.4
ARRIVAL_MIN_WEIGHT = 0.9  # only events big enough to draw overnight visitors
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
            merged[key] = Signal(**{**sig.__dict__, "sources": list(sig.sources)})
            continue
        existing = merged[key]
        seen = {s.url for s in existing.sources}
        existing.sources.extend(s for s in sig.sources if s.url not in seen)
        existing.weight = max(existing.weight, sig.weight)
        existing.end = max(existing.end, sig.end)
        existing.venue = existing.venue or sig.venue
        existing.category = existing.category or sig.category
        if existing.distance_km is None:
            existing.distance_km = sig.distance_km
    return list(merged.values())


def score_days(signals: list[Signal], start: date, end: date, seasonal: SeasonalProfile | None) -> list[DayForecast]:
    days = []
    d = start
    while d <= end:
        factor = 1.0
        if seasonal:
            factor = min(max(seasonal.factor(d), SEASONAL_CLAMP[0]), SEASONAL_CLAMP[1])
        baseline = BASELINE * factor
        drivers: list[Driver] = []
        for i, sig in enumerate(signals):
            if sig.covers(d):
                drivers.append(Driver(i, sig.weight, "on the day"))
            elif sig.kind == "event" and sig.weight >= ARRIVAL_MIN_WEIGHT and sig.start == d + timedelta(days=1):
                drivers.append(Driver(i, round(sig.weight * ARRIVAL_SHARE, 3), "arrival night"))
        pressure = sum(dr.contribution for dr in drivers)
        score = baseline + (100 - baseline) * (1 - math.exp(-pressure / SATURATION))
        drivers.sort(key=lambda dr: dr.contribution, reverse=True)
        days.append(DayForecast(d, round(score, 1), level_for(score), round(baseline, 1), round(factor, 3), round(pressure, 3), drivers))
        d += timedelta(days=1)
    return days


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
        for s in sig.sources:
            seen.setdefault(s.url, s)
    return list(seen.values())
