"""Events from web pages the user points us at (city calendars, venue pages,
convention-centre schedules, tourism boards).

Extraction is rule-based and only reads data the publisher marked up for
machines:

* schema.org Event objects in JSON-LD (<script type="application/ld+json">)
* schema.org Event microdata (itemtype=".../Event")
* iCalendar feeds (.ics), including ones a page advertises with
  <link rel="alternate" type="text/calendar">

Each URL is fetched once (plus at most one advertised calendar feed); there is
no crawling. All fetches go through PoliteFetcher, so robots.txt is honoured.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from icalendar import Calendar

from ..fetcher import FetchBlocked, FetchFailed, PoliteFetcher
from ..models import Adjustment, Signal, Source, SourceCheck
from ..sizing import capacity_factor, parse_capacity

MAX_URLS = 20
MAX_SPAN_DAYS = 31

TYPE_WEIGHTS = {
    "Festival": 1.2,
    "SportsEvent": 1.0,
    "BusinessEvent": 1.0,  # conferences, trade shows
    "MusicEvent": 0.9,
    "FoodEvent": 0.7,
    "TheaterEvent": 0.5,
    "ComedyEvent": 0.4,
    "DanceEvent": 0.4,
    "ExhibitionEvent": 0.5,
    "EducationEvent": 0.3,
    "ChildrensEvent": 0.3,
}
EVENT_TYPES = set(TYPE_WEIGHTS) | {
    "Event", "EventSeries", "Hackathon", "LiteraryEvent", "PublicationEvent", "SaleEvent",
    "ScreeningEvent", "SocialEvent", "VisualArtsEvent", "DeliveryEvent", "CourseInstance",
}
DEFAULT_WEIGHT = 0.5
# Words that usually mean "people travel in for this".
BIG_EVENT = re.compile(
    r"\b(festival|marathon|half marathon|triathlon|conference|convention|congress|summit|expo|exposition|"
    r"trade show|championships?|tournament|playoffs?|finals?|grand prix|world cup|fair|parade|"
    r"graduation|commencement|homecoming)\b",
    re.I,
)


def publisher_of(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not m:
        m = re.match(r"(\d{4})(\d{2})(\d{2})", text)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _type_names(node: dict) -> list[str]:
    t = node.get("@type", [])
    types = t if isinstance(t, list) else [t]
    return [str(x).rsplit("/", 1)[-1].rsplit(":", 1)[-1] for x in types]


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
        return _text(value)
    if isinstance(value, dict):
        name = value.get("name")
        addr = value.get("address")
        parts = [_text(name)]
        if isinstance(addr, dict):
            parts.append(", ".join(str(addr[k]) for k in ("streetAddress", "addressLocality", "addressRegion") if addr.get(k)))
        elif addr:
            parts.append(str(addr))
        return " — ".join(p for p in parts if p) or None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def event_weight(types: list[str], title: str) -> float:
    weight = max((TYPE_WEIGHTS.get(t, 0) for t in types), default=0) or DEFAULT_WEIGHT
    if BIG_EVENT.search(title):
        weight = max(weight, 1.0)
    return round(weight, 3)


def _walk(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _walk(value)


def extract_jsonld(html_soup: BeautifulSoup) -> list[dict]:
    found = []
    for tag in html_soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            types = _type_names(node)
            if any(t in EVENT_TYPES for t in types) and node.get("startDate"):
                found.append(
                    {
                        "title": _text(node.get("name")),
                        "start": node.get("startDate"),
                        "end": node.get("endDate"),
                        "types": types,
                        "venue": _text(node.get("location")),
                        "url": node.get("url") if isinstance(node.get("url"), str) else None,
                        "capacity": node.get("maximumAttendeeCapacity"),
                        "description": _text(node.get("description")),
                    }
                )
    return found


def _itemprop(scope, prop):
    el = scope.find(attrs={"itemprop": prop})
    if el is None:
        return None
    return el.get("content") or el.get("datetime") or el.get("href") or el.get_text(" ", strip=True)


def extract_microdata(html_soup: BeautifulSoup) -> list[dict]:
    found = []
    for scope in html_soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/\w*Event", re.I)}):
        types = [scope["itemtype"].rstrip("/").rsplit("/", 1)[-1]]
        start = _itemprop(scope, "startDate")
        if not start:
            continue
        loc = scope.find(attrs={"itemprop": "location"})
        found.append(
            {
                "title": _itemprop(scope, "name"),
                "start": start,
                "end": _itemprop(scope, "endDate"),
                "types": types,
                "venue": (_itemprop(loc, "name") if loc else None) or (loc.get_text(" ", strip=True) if loc else None),
                "url": _itemprop(scope, "url"),
                "capacity": _itemprop(scope, "maximumAttendeeCapacity"),
                "description": None,
            }
        )
    return found


def extract_ics(text: str) -> list[dict]:
    try:
        cal = Calendar.from_ical(text)
    except Exception:  # malformed feeds are common; treat as empty
        return []
    found = []
    for comp in cal.walk("VEVENT"):
        start = comp.get("DTSTART")
        if start is None:
            continue
        end = comp.get("DTEND")
        end_value = end.dt if end is not None else None
        start_value = start.dt
        # iCal all-day DTEND is exclusive.
        if isinstance(end_value, date) and not isinstance(end_value, datetime):
            end_value = end_value - timedelta(days=1)
        found.append(
            {
                "title": _text(str(comp.get("SUMMARY", ""))),
                "start": start_value,
                "end": end_value,
                "types": ["Event"],
                "venue": _text(str(comp.get("LOCATION"))) if comp.get("LOCATION") else None,
                "url": str(comp.get("URL")) if comp.get("URL") else None,
                "capacity": None,
                "description": None,
            }
        )
    return found


def to_signals(
    raw_events: list[dict], page_url: str, fetched_at: datetime, start: date, end: date, page_label: str = "calendar"
) -> list[Signal]:
    signals = []
    page_source = Source(f"{publisher_of(page_url)} ({page_label})", page_url, fetched_at)
    for ev in raw_events:
        title = ev.get("title")
        s = _parse_date(ev.get("start"))
        if not title or s is None:
            continue
        e = _parse_date(ev.get("end")) or s
        if e < s or (e - s).days > MAX_SPAN_DAYS:
            e = s
        if e < start or s > end:
            continue
        sources = [page_source]
        if ev.get("url"):
            ev_url = urljoin(page_url, ev["url"])
            if ev_url.startswith("http") and ev_url != page_url:
                sources.insert(0, Source(f"{publisher_of(ev_url)} (event page)", ev_url, fetched_at))
        types = [t for t in ev.get("types", []) if t]
        category = next((t for t in types if t != "Event"), None)
        desc = ev.get("description")
        if desc and len(desc) > 240:
            desc = desc[:237].rstrip() + "…"
        venue = ev.get("venue")
        sig = Signal(
            kind="event",
            title=title,
            start=s,
            end=e,
            weight=event_weight(types, title),
            sources=sources,
            category=re.sub(r"(?<!^)(?=[A-Z])", " ", category) if category else None,
            venue=venue,
            venue_name=re.split(r" — |, ", venue)[0] if venue else None,
            description=desc or f"Listed on {publisher_of(page_url)}.",
        )
        capacity = parse_capacity(ev.get("capacity"))
        if capacity:
            sig.add_adjustment(
                Adjustment("Venue capacity", capacity_factor(capacity), f"{capacity:,} attendees (published on the page)", [page_source])
            )
        signals.append(sig)
    return signals


def _is_ics(url: str, content_type: str, text: str) -> bool:
    return "text/calendar" in content_type or url.lower().split("?")[0].endswith(".ics") or text.lstrip().startswith("BEGIN:VCALENDAR")


async def webpage_signals(
    fetcher: PoliteFetcher, urls: list[str], start: date, end: date, trace: list[SourceCheck]
) -> list[Signal]:
    signals: list[Signal] = []
    for url in urls[:MAX_URLS]:
        url = url.strip()
        if not url:
            continue
        publisher = publisher_of(url)
        try:
            res = await fetcher.get(url, source=publisher, kind="page", ttl=timedelta(hours=24), trace=trace)
        except (FetchBlocked, FetchFailed):
            continue

        if _is_ics(res.url, res.content_type, res.text):
            found = to_signals(extract_ics(res.text), res.url, res.fetched_at, start, end, "calendar feed")
            signals.extend(found)
            trace.append(SourceCheck(publisher, res.url, "ok", f"{len(found)} events in range from iCalendar feed"))
            continue

        soup = BeautifulSoup(res.text, "html.parser")
        raw = extract_jsonld(soup) or extract_microdata(soup)
        found = to_signals(raw, res.url, res.fetched_at, start, end)

        if not raw:
            link = soup.find("link", attrs={"rel": "alternate", "type": re.compile("text/calendar", re.I)})
            if link and link.get("href"):
                feed_url = urljoin(res.url, link["href"])
                try:
                    feed = await fetcher.get(feed_url, source=publisher, kind="page", ttl=timedelta(hours=24), trace=trace)
                    found = to_signals(extract_ics(feed.text), feed.url, feed.fetched_at, start, end, "calendar feed")
                except (FetchBlocked, FetchFailed):
                    pass

        detail = f"{len(found)} events in range" if raw or found else "no machine-readable (schema.org / iCal) events found on this page"
        trace.append(SourceCheck(publisher, res.url, "ok" if found else "skipped", detail))
        signals.extend(found)
    return signals
