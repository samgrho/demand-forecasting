"""How big is an event? Pure helpers shared by the sources and the enrichment step.

Two size signals turn into weight multipliers (see models.Adjustment):

* Venue capacity -> how many people can attend at all.
* Artist popularity -> monthly Wikipedia readership of the headliner, a public
  proxy for how far fans will travel to see them.
"""

from __future__ import annotations

import math
import re
import unicodedata

# capacity_factor: 100 seats -> 0.5, 1k -> 0.9, 3k -> ~1.1, 10k -> 1.3, 50k -> ~1.6, 100k+ -> 1.7
CAPACITY_RANGE = (0.5, 1.7)
# popularity_factor: 1k views/month -> 0.75, 10k -> 1.0, 100k -> 1.25, 1M -> 1.5, 2.5M+ -> 1.6
POPULARITY_RANGE = (0.75, 1.6)


def capacity_factor(capacity: float) -> float:
    if capacity <= 0:
        return 1.0
    raw = 0.5 + (math.log10(capacity) - 2) / 2.5
    return round(min(max(raw, CAPACITY_RANGE[0]), CAPACITY_RANGE[1]), 3)


def popularity_factor(monthly_views: float) -> float:
    if monthly_views <= 0:
        return POPULARITY_RANGE[0]
    raw = 1.0 + 0.25 * math.log10(monthly_views / 10_000)
    return round(min(max(raw, POPULARITY_RANGE[0]), POPULARITY_RANGE[1]), 3)


def parse_capacity(value) -> int | None:
    """'18,000' / 18000 / '18000.0' -> 18000; junk -> None."""
    if value is None:
        return None
    try:
        n = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return int(n) if 10 <= n <= 500_000 else None


def normalize_name(name: str) -> list[str]:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\([^)]*\)", " ", text)  # "(band)", "(Austin)"
    tokens = re.findall(r"[a-z0-9]+", text)
    return [t for t in tokens if t != "the"]


def name_similarity(a: str, b: str) -> float:
    """1.0 = same name; 0.9 = one name fully contains the other (2+ words); else word overlap."""
    ta, tb = normalize_name(a), normalize_name(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(short) >= 2 and set(short) <= set(long_):
        return 0.9
    sa, sb = set(ta), set(tb)
    return len(sa & sb) / len(sa | sb)


# Words that appear in many venue names, so sharing them proves nothing.
GENERIC_VENUE_WORDS = {
    "and", "of", "at", "on", "in", "a", "center", "centre", "arena", "stadium", "field", "park", "theater",
    "theatre", "hall", "club", "live", "events", "event", "music", "amphitheater", "amphitheatre", "ballroom",
    "auditorium", "pavilion", "house", "bar", "lounge", "room", "venue", "square", "garden", "gardens",
    "convention", "concert", "concerts", "performing", "arts", "art", "memorial", "city", "downtown", "nightclub",
    "comedy", "studio", "studios", "plaza", "place", "complex", "dome", "coliseum", "colosseum", "bowl",
}


def distinctive_overlap(a: str, b: str, extra_generic: set[str] = frozenset()) -> bool:
    """Do two venue names share at least one word that isn't generic (or the city's name)?"""
    generic = GENERIC_VENUE_WORDS | set(extra_generic)
    return bool((set(normalize_name(a)) & set(normalize_name(b))) - generic)


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))
