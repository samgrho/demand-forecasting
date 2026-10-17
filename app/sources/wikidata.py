"""Notable dated events in the city from Wikidata (free, no key).

Only events with a day-precise start date are used, so "sometime in 2027"
entries don't show up as a specific date. Wikidata Query Service policy:
https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual#Query_limits
"""

from __future__ import annotations

from datetime import date, timedelta

from ..fetcher import FetchBlocked, FetchFailed, PoliteFetcher
from ..models import Location, Signal, Source, SourceCheck

SPARQL = "https://query.wikidata.org/sparql"
PUBLISHER = "Wikidata"
WEIGHT = 1.0  # notable enough to be catalogued -> usually draws visitors
MAX_SPAN_DAYS = 31

QUERY = """
SELECT DISTINCT ?event ?eventLabel ?typeLabel ?start ?end ?venueLabel ?article WHERE {{
  {{ ?event wdt:P276 wd:{qid} . }}
  UNION {{ ?event wdt:P276 ?venue . ?venue wdt:P131 wd:{qid} . }}
  UNION {{ ?event wdt:P131 wd:{qid} . }}
  ?event (p:P580|p:P585) ?st .
  ?st (psv:P580|psv:P585) ?sv .
  ?sv wikibase:timeValue ?start ; wikibase:timePrecision ?prec .
  FILTER(?prec >= 11 && ?start >= "{start}T00:00:00Z"^^xsd:dateTime && ?start < "{end}T00:00:00Z"^^xsd:dateTime)
  FILTER NOT EXISTS {{ ?event wdt:P31 wd:Q5 . }}
  OPTIONAL {{ ?event wdt:P582 ?end . }}
  OPTIONAL {{ ?event wdt:P31 ?type . }}
  OPTIONAL {{ ?article schema:about ?event ; schema:isPartOf <https://en.wikipedia.org/> . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
}}
LIMIT 300
"""


def parse_bindings(payload: dict, fetched_at) -> list[Signal]:
    by_item: dict[str, Signal] = {}
    for row in payload.get("results", {}).get("bindings", []):
        item_url = row["event"]["value"]
        label = row.get("eventLabel", {}).get("value", "")
        if not label or label == item_url.rsplit("/", 1)[-1]:
            continue  # no human-readable name
        start = date.fromisoformat(row["start"]["value"][:10])
        end = start
        if "end" in row:
            try:
                end = date.fromisoformat(row["end"]["value"][:10])
            except ValueError:
                pass
        if end < start or (end - start).days > MAX_SPAN_DAYS:
            end = start
        if item_url in by_item:
            sig = by_item[item_url]
            new_type = row.get("typeLabel", {}).get("value")
            if new_type and sig.category and new_type not in sig.category:
                sig.category += f", {new_type}"
            continue
        sources = [Source(PUBLISHER, item_url, fetched_at)]
        if "article" in row:
            sources.append(Source("Wikipedia", row["article"]["value"], fetched_at))
        venue = row.get("venueLabel", {}).get("value")
        by_item[item_url] = Signal(
            kind="event",
            title=label,
            start=start,
            end=end,
            weight=WEIGHT,
            sources=sources,
            category=row.get("typeLabel", {}).get("value"),
            venue=venue,
            description="Catalogued on Wikidata with this date and location.",
        )
    return list(by_item.values())


async def wikidata_signals(
    fetcher: PoliteFetcher, loc: Location, start: date, end: date, trace: list[SourceCheck]
) -> list[Signal]:
    if not loc.wikidata_id:
        trace.append(SourceCheck(PUBLISHER, SPARQL, "skipped", "location has no Wikidata ID in OpenStreetMap"))
        return []
    query = QUERY.format(qid=loc.wikidata_id, start=start.isoformat(), end=(end + timedelta(days=1)).isoformat())
    try:
        res = await fetcher.get(
            SPARQL,
            source=PUBLISHER,
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
            kind="api",
            ttl=timedelta(hours=24),
            min_interval=1.0,
            trace=trace,
        )
    except (FetchBlocked, FetchFailed):
        return []
    return parse_bindings(res.json(), res.fetched_at)
