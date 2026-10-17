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

    def covers(self, day: date) -> bool:
        return self.start <= day <= self.end

    def dedupe_key(self) -> tuple:
        return (self.kind, self.title.strip().lower(), self.start, (self.venue or "").strip().lower())


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
