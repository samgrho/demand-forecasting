from datetime import date, datetime, timezone

import respx

from app.models import Location
from app.sources.holidays import holiday_signals
from app.sources.ticketmaster import drop_covered_bundles, parse_events, ticketmaster_signals
from app.sources.wikidata import parse_bindings

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
LOC = Location("Austin", "Austin, Texas", 30.27, -97.74, "US", "US-TX", "Q16559", "en:Austin, Texas", "https://osm.test/1")


@respx.mock
async def test_holidays_filter_by_region_and_range(fetcher):
    respx.get("https://date.nager.at/api/v3/PublicHolidays/2026/US").respond(200, json=[
        {"date": "2026-11-26", "localName": "Thanksgiving Day", "name": "Thanksgiving Day", "global": True, "counties": None},
        {"date": "2026-11-27", "localName": "Day after", "name": "Texas only", "global": False, "counties": ["US-TX"]},
        {"date": "2026-11-28", "localName": "Other", "name": "Ohio only", "global": False, "counties": ["US-OH"]},
        {"date": "2026-07-04", "localName": "Independence Day", "name": "Independence Day", "global": True, "counties": None},
    ])
    respx.get("https://date.nager.at/api/v3/LongWeekend/2026/US").respond(200, json=[
        {"startDate": "2026-11-26", "endDate": "2026-11-29", "dayCount": 4, "needBridgeDay": True},
    ])
    trace = []
    sigs = await holiday_signals(fetcher, LOC, date(2026, 11, 1), date(2026, 11, 30), trace)
    titles = {s.title for s in sigs}
    assert "Thanksgiving Day" in titles and "Texas only" in titles
    assert "Ohio only" not in titles and "Independence Day" not in titles
    lw = next(s for s in sigs if s.kind == "long_weekend")
    assert (lw.start, lw.end) == (date(2026, 11, 26), date(2026, 11, 29))
    assert all(s.sources[0].url.startswith("https://date.nager.at/") for s in sigs)


def test_ticketmaster_parse_skips_addons_and_cancelled():
    payload = {"_embedded": {"events": [
        {"name": "Big Band Live", "url": "https://tm.test/e/1", "dates": {"start": {"localDate": "2026-11-01"}},
         "classifications": [{"segment": {"name": "Music"}, "genre": {"name": "Jazz"}}],
         "_embedded": {"venues": [{"name": "Arena", "city": {"name": "Austin"}}]}, "distance": 3.0, "units": "KILOMETERS"},
        {"name": "Big Band Live - Parking", "url": "https://tm.test/e/2", "dates": {"start": {"localDate": "2026-11-01"}}},
        {"name": "Cancelled Show", "url": "https://tm.test/e/3",
         "dates": {"start": {"localDate": "2026-11-02"}, "status": {"code": "cancelled"}}},
    ]}}
    sigs = parse_events(payload, NOW)
    assert [s.title for s in sigs] == ["Big Band Live"]
    s = sigs[0]
    assert s.sources[0].url == "https://tm.test/e/1"
    assert s.category == "Music / Jazz"
    assert s.distance_km == 3.0


async def test_ticketmaster_without_key_is_skipped(fetcher):
    trace = []
    assert await ticketmaster_signals(fetcher, LOC, date(2026, 11, 1), date(2026, 11, 2), 25, "", trace) == []
    assert trace[-1].outcome == "skipped"


@respx.mock
async def test_ticketmaster_key_never_leaks_into_trace(fetcher):
    respx.get(url__startswith="https://app.ticketmaster.com/").respond(200, json={"page": {"number": 0, "totalPages": 1}})
    trace = []
    await ticketmaster_signals(fetcher, LOC, date(2026, 11, 1), date(2026, 11, 2), 25, "SECRETKEY", trace)
    assert trace and all("SECRETKEY" not in c.url for c in trace)


def test_wikidata_merges_rows_per_item():
    payload = {"results": {"bindings": [
        {"event": {"value": "http://www.wikidata.org/entity/Q1"}, "eventLabel": {"value": "City Marathon 2026"},
         "start": {"value": "2026-11-08T00:00:00Z"}, "typeLabel": {"value": "marathon"},
         "article": {"value": "https://en.wikipedia.org/wiki/City_Marathon"}},
        {"event": {"value": "http://www.wikidata.org/entity/Q1"}, "eventLabel": {"value": "City Marathon 2026"},
         "start": {"value": "2026-11-08T00:00:00Z"}, "typeLabel": {"value": "sporting event"}},
        {"event": {"value": "http://www.wikidata.org/entity/Q2"}, "eventLabel": {"value": "Q2"},
         "start": {"value": "2026-11-09T00:00:00Z"}},
    ]}}
    sigs = parse_bindings(payload, NOW)
    assert len(sigs) == 1
    assert sigs[0].category == "marathon, sporting event"
    assert [s.publisher for s in sigs[0].sources] == ["Wikidata", "Wikipedia"]


def _tm(name, day="2026-11-07", venue="Emo's Austin"):
    return {"name": name, "url": f"https://tm.test/{name}", "dates": {"start": {"localDate": day}},
            "classifications": [{"segment": {"name": "Music"}}], "_embedded": {"venues": [{"name": venue}]}}


def test_bundles_dropped_only_when_the_show_is_listed():
    payload = {"_embedded": {"events": [
        _tm("They Might Be Giants"),
        _tm("TWO NIGHTS WITH THEY MIGHT BE GIANTS - 2 Day Ticket"),
        _tm("Big Fest - Weekend Pass", venue="Auditorium Shores"),  # only listing -> keep
        _tm("Expedited Entry & Social Club Happy Hour - Steve Lacy"),
    ]}}
    titles = [s.title for s in drop_covered_bundles(parse_events(payload, NOW))]
    assert titles == ["They Might Be Giants", "Big Fest - Weekend Pass"]
