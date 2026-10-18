"""Plain data types shared across sources, scoring and the API."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Location:
    query: str
    display_name: str
    lat: float
    lon: float
    country_code: str  # ISO 3166-1 alpha-2, upper case
    subdivision_code: str | None  # ISO 3166-2, e.g. "US-TX"
    wikidata_id: str | None
    wikipedia_title: str | None  # "en:Austin, Texas" style
    source_url: str


@dataclass
class Source:
    """Where a claim came from, so the user can verify it."""

    publisher: str
    url: str
    fetched_at: datetime


@dataclass
class Performer:
    name: str
    wikipedia_url: str | None = None  # when the listing links one


@dataclass
class Adjustment:
    """A sourced multiplier on a signal's weight (e.g. venue size, artist popularity)."""

    label: str  # "Venue capacity" | "Artist popularity"
    factor: float
    detail: str  # human-readable claim, e.g. "Moody Center holds 15,000"
    sources: list[Source]  # empty = a model assumption, not a sourced claim

    @property
    def assumed(self) -> bool:
        return not self.sources


# Bounds on the combined effect of all adjustments, so one mega-event can't
# drown out everything else on the calendar.
ADJUSTMENT_BOUNDS = (0.4, 2.5)


@dataclass
class Signal:
    """One thing that may raise demand over a span of days."""

    kind: str  # "event" | "holiday" | "long_weekend"
    title: str
    start: date
    end: date  # inclusive
    weight: float  # demand impact units, see forecast.py
    sources: list[Source]
    category: str | None = None
    venue: str | None = None
    distance_km: float | None = None
    description: str | None = None
    venue_name: str | None = None  # venue alone, for capacity lookups
    venue_coords: tuple[float, float] | None = None  # (lat, lon) when the source gives it
    performers: list[Performer] = field(default_factory=list)
    adjustments: list[Adjustment] = field(default_factory=list)
    base_weight: float | None = None  # weight before adjustments

    def __post_init__(self):
        if self.base_weight is None:
            self.base_weight = self.weight

    def covers(self, day: date) -> bool:
        return self.start <= day <= self.end

    def has_adjustment(self, label: str) -> bool:
        return any(a.label == label for a in self.adjustments)

    def add_adjustment(self, adj: Adjustment) -> None:
        self.adjustments.append(adj)
        product = 1.0
        for a in self.adjustments:
            product *= a.factor
        lo, hi = ADJUSTMENT_BOUNDS
        self.weight = round(self.base_weight * min(max(product, lo), hi), 3)


@dataclass
class SourceCheck:
    """A log line for every source the app tried, including ones it skipped."""

    source: str
    url: str
    outcome: str  # "ok" | "cached" | "blocked" | "error" | "skipped"
    detail: str = ""
    at: datetime = field(default_factory=utcnow)


def to_jsonable(obj):
    """dataclasses -> JSON-safe dicts (dates as ISO strings)."""
    if hasattr(obj, "__dataclass_fields__"):
        obj = asdict(obj)
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj
