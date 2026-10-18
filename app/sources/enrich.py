"""Size up events after they are collected: venue capacity and artist popularity.

* Venue capacity: ONE Wikidata query fetches every venue with a published
  "maximum capacity" (P1083) near the hotel; event venues are matched to it by
  name, and by coordinates when the event source gives them.
* Artist popularity: for the headliners of non-sports events, find the
  performer's English Wikipedia article (Ticketmaster's own link if it has
  one, otherwise a search whose result must name the same act and be described
  as a musician/band/comedian/etc.), then average its last 12 months of
  pageviews.

Every match becomes an Adjustment that cites where the number came from.
Events that can't be matched keep their unadjusted weight.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import quote, unquote

from ..fetcher import FetchBlocked, FetchFailed, PoliteFetcher
from ..models import Adjustment, Location, Performer, Signal, Source, SourceCheck
from ..sizing import (
    capacity_factor,
    distinctive_overlap,
    haversine_km,
    name_similarity,
    normalize_name,
    parse_capacity,
    popularity_factor,
)

SPARQL = "https://query.wikidata.org/sparql"
WIKI_API = "https://en.wikipedia.org/w/api.php"
PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"

MAX_VENUE_RADIUS_KM = 150
# Venues big enough to move hotel demand are almost always documented on
# Wikidata or Wikipedia, so an undocumented venue is most likely small. This is
# a model assumption (shown as such, with no source), not a sourced claim.
UNKNOWN_VENUE_FACTOR = 0.7
MAX_VENUE_LOOKUPS = 40  # Wikipedia fallback lookups per forecast (one request each)
MAX_ARTISTS = 80  # artist lookups per forecast (two requests each); all cached afterwards
PERFORMERS_PER_EVENT = 2  # headliner + co-headliner

PERFORMER_DESC = re.compile(
    r"\b(singer|songwriter|band|musician|rapper|hip hop|dj|disc jockey|duo|trio|group|composer|comedian|"
    r"orchestra|symphony|producer|vocalist|guitarist|pianist|drummer|bassist|performer|entertainer|"
    r"magician|choir|ensemble|artist|musical|country music|pop|rock|tribute|idol|boy band|girl group)\b",
    re.I,
)

VENUE_QUERY = """
SELECT ?venue ?venueLabel (MAX(?cap) AS ?capacity) (SAMPLE(?coord) AS ?location)
       (GROUP_CONCAT(DISTINCT ?alt; separator="|") AS ?aliases) WHERE {{
  SERVICE wikibase:around {{
    ?venue wdt:P625 ?coord .
    bd:serviceParam wikibase:center "Point({lon} {lat})"^^geo:wktLiteral .
    bd:serviceParam wikibase:radius "{radius}" .
  }}
  ?venue wdt:P1083 ?cap .
  OPTIONAL {{ ?venue skos:altLabel ?alt . FILTER(LANG(?alt) = "en") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". ?venue rdfs:label ?venueLabel . }}
}}
GROUP BY ?venue ?venueLabel
LIMIT 3000
"""


@dataclass
class Venue:
    url: str  # Wikidata item
    name: str
    aliases: list[str]
    capacity: int
    coords: tuple[float, float] | None


# ---------- venue capacity ----------


def parse_venues(payload: dict) -> list[Venue]:
    venues = []
    for row in payload.get("results", {}).get("bindings", []):
        url = row["venue"]["value"]
        name = row.get("venueLabel", {}).get("value", "")
        capacity = parse_capacity(row.get("capacity", {}).get("value"))
        if not name or name == url.rsplit("/", 1)[-1] or capacity is None:
            continue
        coords = None
        m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", row.get("location", {}).get("value", ""))
        if m:
            coords = (float(m.group(2)), float(m.group(1)))
        aliases = [a for a in row.get("aliases", {}).get("value", "").split("|") if a]
        venues.append(Venue(url, name, aliases, capacity, coords))
    return venues


def match_venue(
    name: str, coords: tuple[float, float] | None, venues: list[Venue], city_words: set[str] = frozenset()
) -> Venue | None:
    """Best venue for an event's venue name.

    The names must always share a distinctive word (not "center", "arena",
    the city's name...). With coordinates: names must overlap (>= 0.5) within
    3 km, or (>= 0.34) within 250 m. Without coordinates: names must be the
    same, or one must contain the other.
    """
    best, best_key = None, None
    for v in venues:
        names = [n for n in [v.name, *v.aliases] if distinctive_overlap(name, n, city_words)]
        if not names:
            continue
        sim = max(name_similarity(name, n) for n in names)
        dist = haversine_km(coords, v.coords) if coords and v.coords else None
        if dist is not None:
            ok = (sim >= 0.5 and dist <= 3.0) or (sim >= 0.34 and dist <= 0.25)
        else:
            ok = sim >= 0.9
        if not ok:
            continue
        key = (sim, -(dist if dist is not None else 99))
        if best_key is None or key > best_key:
            best, best_key = v, key
    return best


async def nearby_venues(fetcher: PoliteFetcher, loc: Location, radius_km: int, trace: list[SourceCheck]):
    radius = min(radius_km + 5, MAX_VENUE_RADIUS_KM)
    query = VENUE_QUERY.format(lat=f"{loc.lat:.5f}", lon=f"{loc.lon:.5f}", radius=radius)
    try:
        res = await fetcher.get(
            SPARQL,
            source="Wikidata (venue capacities)",
            params={"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
            kind="api",
            ttl=timedelta(days=14),
            min_interval=1.0,
            trace=trace,
        )
    except (FetchBlocked, FetchFailed):
        return [], None
    return parse_venues(res.json()), res.fetched_at


def parse_infobox_capacity(wikitext: str) -> int | None:
    """Largest seat count in an infobox's "capacity" field, or None."""
    m = re.search(r"^\s*\|\s*capacity\s*=(.*?)(?=^\s*\||^\s*\}\})", wikitext, re.M | re.S | re.I)
    if not m:
        return None
    text = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", " ", m.group(1), flags=re.S)
    numbers = []
    for raw in re.findall(r"\d{1,3}(?:,\d{3})+|\d+", text):
        n = int(raw.replace(",", ""))
        if "," not in raw and 1850 <= n <= 2100:
            continue  # a year, e.g. "2,750 (since 2011)"
        numbers.append(n)
    caps = [c for c in (parse_capacity(n) for n in numbers) if c and c >= 50]
    return max(caps) if caps else None


def pick_venue_article(name: str, coords: tuple[float, float] | None, pages: list[dict], city_words: set[str]):
    """(title, capacity) of the search result that is clearly this venue, or None."""
    best, best_key = None, None
    for p in pages:
        title = p.get("title", "")
        if "disambiguation" in (p.get("pageprops") or {}) or not distinctive_overlap(name, title, city_words):
            continue
        sim = name_similarity(name, title)
        geo = (p.get("coordinates") or [{}])[0]
        dist = haversine_km(coords, (geo["lat"], geo["lon"])) if coords and "lat" in geo else None
        if dist is not None:
            ok = sim >= 0.5 and dist <= 3.0
        else:
            ok = sim >= 0.9
        if not ok:
            continue
        revs = p.get("revisions") or [{}]
        wikitext = ((revs[0].get("slots") or {}).get("main") or {}).get("content", "")
        capacity = parse_infobox_capacity(wikitext)
        if capacity is None:
            continue
        key = (sim, -(dist if dist is not None else 99), -p.get("index", 99))
        if best_key is None or key > best_key:
            best, best_key = (title, capacity), key
    return best


async def wikipedia_venue(fetcher, name: str, coords, city: str, city_words: set[str], trace: list[SourceCheck]):
    try:
        res = await fetcher.get(
            WIKI_API,
            source="Wikipedia (venue infobox)",
            params={
                "action": "query", "format": "json", "formatversion": 2, "redirects": 1,
                "generator": "search", "gsrsearch": f"{name} {city}".strip(), "gsrlimit": 3, "gsrnamespace": 0,
                "prop": "pageprops|coordinates|revisions", "ppprop": "disambiguation",
                "rvprop": "content", "rvslots": "main", "rvsection": 0,
            },
            kind="api",
            ttl=timedelta(days=30),
            min_interval=0.25,
            trace=trace,
        )
    except (FetchBlocked, FetchFailed):
        return None
    found = pick_venue_article(name, coords, res.json().get("query", {}).get("pages", []), city_words)
    if not found:
        return None
    title, capacity = found
    url = "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
    return Venue(url, title, [], capacity, None), res.fetched_at


async def enrich_venues(fetcher: PoliteFetcher, loc: Location, signals: list[Signal], radius_km: int, trace: list[SourceCheck]) -> None:
    candidates = [s for s in signals if s.kind == "event" and s.venue_name and not s.has_adjustment("Venue capacity")]
    if not candidates:
        return
    city = loc.display_name.split(",")[0].strip()
    city_words = set(normalize_name(city))

    # 1. Wikidata: every nearby venue with a capacity, in one query.
    venues, wd_fetched = await nearby_venues(fetcher, loc, radius_km, trace)
    found: dict[str, tuple[Venue, str, object]] = {}  # venue name -> (venue, publisher, fetched_at)
    coords_for: dict[str, tuple | None] = {}
    counts: dict[str, int] = {}
    for sig in candidates:
        key = sig.venue_name.strip().lower()
        counts[key] = counts.get(key, 0) + 1
        coords_for.setdefault(key, sig.venue_coords)
        if key not in found and venues:
            v = match_venue(sig.venue_name, sig.venue_coords, venues, city_words)
            if v:
                found[key] = (v, "Wikidata", wd_fetched)
    from_wikidata = len(found)

    # 2. Wikipedia infobox for the rest, busiest venues first.
    missing = sorted((k for k in counts if k not in found), key=lambda k: -counts[k])[:MAX_VENUE_LOOKUPS]
    names = {s.venue_name.strip().lower(): s.venue_name for s in candidates}
    results = await asyncio.gather(
        *(wikipedia_venue(fetcher, names[k], coords_for[k], city, city_words, trace) for k in missing), return_exceptions=True
    )
    for k, r in zip(missing, results):
        if r and not isinstance(r, Exception):
            found[k] = (r[0], "Wikipedia", r[1])

    for sig in candidates:
        hit = found.get(sig.venue_name.strip().lower())
        if not hit:
            sig.add_adjustment(
                Adjustment(
                    "Venue capacity",
                    UNKNOWN_VENUE_FACTOR,
                    f"{sig.venue_name}: capacity not found on Wikidata or Wikipedia, assumed small",
                    [],
                )
            )
            continue
        venue, publisher, fetched_at = hit
        sig.add_adjustment(
            Adjustment(
                "Venue capacity",
                capacity_factor(venue.capacity),
                f"{venue.name} holds up to {venue.capacity:,}" + (" (Wikipedia infobox)" if publisher == "Wikipedia" else ""),
                [Source(publisher, venue.url, fetched_at)],
            )
        )
    not_tried = max(0, len(counts) - len(found) - len(missing))
    detail = f"sized {len(found)} of {len(counts)} venues ({from_wikidata} from Wikidata, {len(found) - from_wikidata} from Wikipedia infoboxes)"
    if not_tried:
        detail += f"; {not_tried} smaller venues not looked up (limit {MAX_VENUE_LOOKUPS})"
    trace.append(SourceCheck("Venue capacity", SPARQL, "ok", detail))


# ---------- artist popularity ----------


def _title_from_wiki_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.match(r"https?://en\.(?:m\.)?wikipedia\.org/wiki/([^?#]+)", url)
    return unquote(m.group(1)).replace("_", " ") if m else None


def pick_article(name: str, pages: list[dict]) -> str | None:
    """The search result that is clearly this performer, or None."""
    accepted = [
        p for p in pages
        if "disambiguation" not in (p.get("pageprops") or {})
        and name_similarity(p.get("title", ""), name) == 1.0
        and PERFORMER_DESC.search(p.get("description") or "")
    ]
    if not accepted:
        return None
    return min(accepted, key=lambda p: p.get("index", 99))["title"]


async def find_article(fetcher: PoliteFetcher, performer: Performer, trace: list[SourceCheck]) -> str | None:
    title = _title_from_wiki_url(performer.wikipedia_url)
    if title:
        return title
    try:
        res = await fetcher.get(
            WIKI_API,
            source="Wikipedia search",
            params={
                "action": "query", "format": "json", "formatversion": 2, "redirects": 1,
                "generator": "search", "gsrsearch": performer.name, "gsrlimit": 5, "gsrnamespace": 0,
                "prop": "description|pageprops", "ppprop": "disambiguation",
            },
            kind="api",
            ttl=timedelta(days=30),
            min_interval=0.25,
            trace=trace,
        )
    except (FetchBlocked, FetchFailed):
        return None
    return pick_article(performer.name, res.json().get("query", {}).get("pages", []))


async def monthly_views(fetcher: PoliteFetcher, title: str, today: date, trace: list[SourceCheck]):
    first = date(today.year - 1, today.month, 1)
    last = date(today.year, today.month, 1) - timedelta(days=1)
    slug = quote(title.replace(" ", "_"), safe="")
    url = f"{PAGEVIEWS}/{slug}/monthly/{first:%Y%m%d}00/{last:%Y%m%d}00"
    try:
        res = await fetcher.get(url, source="Wikimedia pageviews", kind="api", ttl=timedelta(days=7), min_interval=0.25, trace=trace)
    except (FetchBlocked, FetchFailed):
        return None
    items = res.json().get("items", [])
    if len(items) < 6:
        return None
    viewer = (
        "https://pageviews.wmcloud.org/?project=en.wikipedia.org&platform=all-access&agent=user"
        f"&start={first:%Y-%m-%d}&end={last:%Y-%m-%d}&pages={quote(title.replace(' ', '_'))}"
    )
    return sum(int(i["views"]) for i in items) / len(items), viewer, res.fetched_at


async def artist_adjustment(fetcher: PoliteFetcher, performer: Performer, today: date, trace: list[SourceCheck]) -> Adjustment | None:
    title = await find_article(fetcher, performer, trace)
    if not title:
        return None
    views = await monthly_views(fetcher, title, today, trace)
    if not views:
        return None
    avg, viewer, fetched_at = views
    article = "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
    return Adjustment(
        "Artist popularity",
        popularity_factor(avg),
        f"{performer.name}: about {avg:,.0f} Wikipedia views/month over the last year",
        [Source("Wikipedia", article, fetched_at), Source("Wikimedia pageviews", viewer, fetched_at)],
    )


def _artist_candidates(signals: list[Signal]) -> list[Signal]:
    out = [
        s for s in signals
        if s.kind == "event" and s.performers and not (s.category or "").startswith("Sports")
        and not s.has_adjustment("Artist popularity")
    ]
    # Spend the lookup budget where popularity matters most: big rooms first.
    def capacity(sig: Signal) -> float:
        return next((a.factor for a in sig.adjustments if a.label == "Venue capacity"), 0.0)

    out.sort(key=lambda s: (-capacity(s), -s.weight, s.start))
    return out


async def enrich_artists(fetcher: PoliteFetcher, signals: list[Signal], today: date, trace: list[SourceCheck]) -> None:
    candidates = _artist_candidates(signals)
    if not candidates:
        return
    wanted: dict[str, Performer] = {}
    for sig in candidates:
        for p in sig.performers[:PERFORMERS_PER_EVENT]:
            key = p.name.strip().lower()
            if key not in wanted and len(wanted) < MAX_ARTISTS:
                wanted[key] = p
    results = await asyncio.gather(*(artist_adjustment(fetcher, p, today, trace) for p in wanted.values()), return_exceptions=True)
    by_name = {k: r for k, r in zip(wanted, results) if isinstance(r, Adjustment)}

    for sig in candidates:
        options = [by_name[p.name.strip().lower()] for p in sig.performers[:PERFORMERS_PER_EVENT] if p.name.strip().lower() in by_name]
        if options:
            sig.add_adjustment(max(options, key=lambda a: a.factor))
    skipped = len({p.name.strip().lower() for s in candidates for p in s.performers[:PERFORMERS_PER_EVENT]}) - len(wanted)
    detail = f"matched {len(by_name)} of {len(wanted)} artists to a Wikipedia article"
    if skipped > 0:
        detail += f"; {skipped} more not looked up (limit {MAX_ARTISTS} per forecast)"
    trace.append(SourceCheck("Artist popularity", WIKI_API, "ok", detail))


async def enrich_events(
    fetcher: PoliteFetcher, loc: Location, signals: list[Signal], radius_km: int, today: date, trace: list[SourceCheck]
) -> None:
    await enrich_venues(fetcher, loc, signals, radius_km, trace)
    await enrich_artists(fetcher, signals, today, trace)
