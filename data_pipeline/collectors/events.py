"""Collect events from public local sources.

Start by implementing provider-specific adapters in this package.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class EventSignal:
    source_name: str
    source_url: str
    title: str
    starts_at: datetime
    location: str


def collect_local_events(location: str, start_date: str, end_date: str) -> list[EventSignal]:
    """Return event signals for a location and date range.

    TODO: Implement adapters for allowed sources.
    """
    _ = (location, start_date, end_date)
    return []
