"""Resolve a user's location text with OpenStreetMap Nominatim.

Usage policy (https://operations.osmfoundation.org/policies/nominatim/):
max 1 request/second, identifying User-Agent, cache results. All three are
enforced here and in the fetcher.
"""

from __future__ import annotations

from datetime import timedelta

from ..fetcher import PoliteFetcher
from ..models import Location, SourceCheck

NOMINATIM = "https://nominatim.openstreetmap.org/search"


class LocationNotFound(Exception):
    pass


async def geocode(fetcher: PoliteFetcher, query: str, trace: list[SourceCheck]) -> Location:
    res = await fetcher.get(
        NOMINATIM,
        source="OpenStreetMap Nominatim",
        params={"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1, "extratags": 1},
        kind="api",
        ttl=timedelta(days=30),
        min_interval=1.1,
        trace=trace,
    )
    hits = res.json()
    if not hits:
        raise LocationNotFound(f"No match for {query!r}")
    hit = hits[0]
    address = hit.get("address", {})
    extratags = hit.get("extratags") or {}
    subdivision = address.get("ISO3166-2-lvl4") or address.get("ISO3166-2-lvl6")
    osm_url = f"https://www.openstreetmap.org/{hit.get('osm_type', 'node')}/{hit.get('osm_id', '')}"
    return Location(
        query=query,
        display_name=hit.get("display_name", query),
        lat=float(hit["lat"]),
        lon=float(hit["lon"]),
        country_code=(address.get("country_code") or "").upper(),
        subdivision_code=subdivision,
        wikidata_id=extratags.get("wikidata"),
        wikipedia_title=extratags.get("wikipedia"),
        source_url=osm_url,
    )
