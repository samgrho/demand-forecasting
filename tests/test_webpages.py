from datetime import date, datetime, timezone

import respx
from bs4 import BeautifulSoup

from app.sources.webpages import event_weight, extract_ics, extract_jsonld, extract_microdata, to_signals, webpage_signals

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)

JSONLD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
  {"@type": "WebPage", "name": "Events"},
  {"@type": "ItemList", "itemListElement": [
    {"@type": "ListItem", "item": {
      "@type": ["Event", "Festival"], "name": "Harvest Festival",
      "startDate": "2026-10-10T10:00:00-05:00", "endDate": "2026-10-12",
      "location": {"@type": "Place", "name": "City Park", "address": {"addressLocality": "Springfield"}},
      "url": "/events/harvest"
    }},
    {"@type": "ListItem", "item": {
      "@type": "MusicEvent", "name": "Jazz Night", "startDate": "2026-12-01",
      "maximumAttendeeCapacity": 300
    }}
  ]}
]}
</script>
<script type="application/ld+json">{ not valid json </script>
</head><body></body></html>
"""

MICRODATA_PAGE = """
<div itemscope itemtype="https://schema.org/SportsEvent">
  <span itemprop="name">City Marathon</span>
  <time itemprop="startDate" datetime="2026-11-08">Nov 8</time>
  <div itemprop="location" itemscope itemtype="https://schema.org/Place"><span itemprop="name">Downtown</span></div>
</div>
"""

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:1
SUMMARY:Tech Conference 2026
DTSTART;VALUE=DATE:20261103
DTEND;VALUE=DATE:20261106
LOCATION:Convention Center
URL:https://conf.test/2026
END:VEVENT
BEGIN:VEVENT
UID:2
SUMMARY:Library story time
DTSTART:20261104T150000Z
END:VEVENT
END:VCALENDAR
"""


def test_jsonld_finds_nested_events_and_skips_bad_json():
    events = extract_jsonld(BeautifulSoup(JSONLD_PAGE, "html.parser"))
    titles = [e["title"] for e in events]
    assert titles == ["Harvest Festival", "Jazz Night"]
    assert events[0]["venue"].startswith("City Park")


def test_to_signals_filters_range_and_keeps_sources():
    events = extract_jsonld(BeautifulSoup(JSONLD_PAGE, "html.parser"))
    sigs = to_signals(events, "https://www.city.test/events", NOW, date(2026, 10, 1), date(2026, 10, 31))
    assert len(sigs) == 1
    sig = sigs[0]
    assert (sig.start, sig.end) == (date(2026, 10, 10), date(2026, 10, 12))
    urls = [s.url for s in sig.sources]
    assert urls == ["https://www.city.test/events/harvest", "https://www.city.test/events"]
    assert sig.sources[0].publisher == "city.test (event page)"
    assert sig.sources[1].publisher == "city.test (calendar)"
    assert sig.weight >= 1.0  # Festival


def test_microdata():
    events = extract_microdata(BeautifulSoup(MICRODATA_PAGE, "html.parser"))
    assert events[0]["title"] == "City Marathon"
    assert events[0]["start"] == "2026-11-08"
    assert events[0]["venue"] == "Downtown"


def test_ics_all_day_end_is_exclusive():
    sigs = to_signals(extract_ics(ICS), "https://conf.test/cal.ics", NOW, date(2026, 11, 1), date(2026, 11, 30))
    conf = next(s for s in sigs if s.title == "Tech Conference 2026")
    assert (conf.start, conf.end) == (date(2026, 11, 3), date(2026, 11, 5))
    assert conf.weight >= 1.0  # "conference" keyword
    story = next(s for s in sigs if s.title == "Library story time")
    assert story.weight < conf.weight


def test_capacity_scales_weight():
    small = event_weight(["MusicEvent"], "Gig", 100)
    big = event_weight(["MusicEvent"], "Gig", 50000)
    assert big > small


@respx.mock
async def test_webpage_signals_respects_robots(fetcher):
    respx.get("https://blocked.test/robots.txt").respond(200, text="User-agent: *\nDisallow: /\n")
    page = respx.get("https://blocked.test/events").respond(200, text=JSONLD_PAGE)
    trace = []
    sigs = await webpage_signals(fetcher, ["https://blocked.test/events"], date(2026, 10, 1), date(2026, 12, 31), trace)
    assert sigs == []
    assert not page.called
    assert trace[-1].outcome == "blocked"


@respx.mock
async def test_webpage_follows_advertised_ics_feed(fetcher):
    respx.get("https://venue.test/robots.txt").respond(404)
    respx.get("https://venue.test/calendar").respond(
        200, text='<html><head><link rel="alternate" type="text/calendar" href="/feed.ics"></head></html>',
        headers={"content-type": "text/html"},
    )
    respx.get("https://venue.test/feed.ics").respond(200, text=ICS, headers={"content-type": "text/calendar"})
    trace = []
    sigs = await webpage_signals(fetcher, ["https://venue.test/calendar"], date(2026, 11, 1), date(2026, 11, 30), trace)
    assert {s.title for s in sigs} == {"Tech Conference 2026", "Library story time"}
    assert all(s.sources[-1].url == "https://venue.test/feed.ics" for s in sigs)
