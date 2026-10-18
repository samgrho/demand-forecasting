from datetime import date, datetime, timezone

import respx

from app.forecast import merge_duplicates
from app.models import ADJUSTMENT_BOUNDS, Adjustment, Location, Performer, Signal, Source
from app.sizing import capacity_factor, name_similarity, popularity_factor
from app.sources.enrich import (
    Venue,
    enrich_events,
    match_venue,
    parse_infobox_capacity,
    parse_venues,
    pick_article,
    pick_venue_article,
)

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
TODAY = date(2026, 10, 18)
LOC = Location("Austin", "Austin, Texas", 30.27, -97.74, "US", "US-TX", "Q16559", None, "https://osm.test/1")

MOODY = Venue("http://www.wikidata.org/entity/Q100", "Moody Center", ["Moody Center ATX"], 15000, (30.2817, -97.7322))
CLUB = Venue("http://www.wikidata.org/entity/Q101", "Mohawk", [], 900, (30.2701, -97.7362))
VENUES = [MOODY, CLUB]


def tm_event(title, venue, coords=None, performers=(), category="Music / Rock", weight=1.0):
    return Signal(
        "event", title, date(2026, 11, 1), date(2026, 11, 1), weight,
        [Source("Ticketmaster", f"https://tm.test/{title}", NOW)],
        category=category, venue_name=venue, venue_coords=coords,
        performers=[Performer(p) for p in performers],
    )


# ---------- pure helpers ----------

def test_factors_are_monotonic_and_bounded():
    assert capacity_factor(100) < capacity_factor(1000) < capacity_factor(15000) < capacity_factor(80000)
    assert capacity_factor(10) == 0.5 and capacity_factor(10_000_000) == 1.7
    assert popularity_factor(1000) < popularity_factor(10_000) < popularity_factor(1_000_000)
    assert popularity_factor(10_000) == 1.0
    assert popularity_factor(0) == 0.75 and popularity_factor(1e9) == 1.6


def test_name_similarity():
    assert name_similarity("Moody Center", "moody center") == 1.0
    assert name_similarity("Circuit of The Americas - COTA", "Circuit of the Americas") == 0.9
    assert name_similarity("Sigur Rós", "Sigur Ros") == 1.0
    assert name_similarity("The National", "National (band)") == 1.0
    assert name_similarity("Moody Center", "Moody Theater") < 0.5


def test_match_venue_uses_coordinates_when_available():
    assert match_venue("Moody Center ATX", (30.2818, -97.7321), VENUES) is MOODY
    # same name but 40 km away -> a different place
    assert match_venue("Moody Center", (30.6, -97.4), VENUES) is None


def test_match_venue_ignores_generic_words():
    erwin = Venue("http://www.wikidata.org/entity/Q1", "Frank Erwin Center", ["Special Events Center"], 17900, (30.2768, -97.7323))
    # shares only "events center" -> not the same place, even close by
    assert match_venue("Palmer Events Center", (30.2588, -97.7522), [erwin]) is None
    assert match_venue("Palmer Events Center", (30.2770, -97.7320), [erwin]) is None
    # the city's own name isn't distinctive either
    austin_arena = Venue("http://www.wikidata.org/entity/Q2", "Austin Arena", [], 5000, (30.27, -97.74))
    assert match_venue("Austin Music Hall", (30.27, -97.74), [austin_arena], {"austin"}) is None


def test_infobox_capacity_parsing():
    wikitext = """{{Infobox venue
| name = ACL Live at the Moody Theater
| opened = 2011
| capacity = 2,750<ref>{{cite web|url=x}}</ref> (standing)<br>2,200 (seated, since 2012)
| seating_type = mixed
}}"""
    assert parse_infobox_capacity(wikitext) == 2750
    assert parse_infobox_capacity("{{Infobox venue\n| name = X\n| opened = 1999\n}}") is None
    assert parse_infobox_capacity("{{Infobox venue\n| capacity = 1,000–1,200\n}}") == 1200


def test_pick_venue_article_checks_name_and_location():
    page = {
        "title": "Moody Theater", "index": 1, "coordinates": [{"lat": 30.2656, "lon": -97.7471}],
        "revisions": [{"slots": {"main": {"content": "{{Infobox venue\n| capacity = 2,750\n}}"}}}],
    }
    # Ticketmaster's long name contains the article title, at the same spot -> same venue
    assert pick_venue_article("Austin City Limits Live at The Moody Theater", (30.2656, -97.7470), [page], {"austin"}) == ("Moody Theater", 2750)
    assert pick_venue_article("Moody Center ATX", (30.2656, -97.7470), [page], {"austin"}) is None  # different venue
    assert pick_venue_article("The Moody Theater", (30.2656, -97.7470), [page], {"austin"}) == ("Moody Theater", 2750)
    assert pick_venue_article("The Moody Theater", (31.0, -97.0), [page], {"austin"}) is None  # far away


def test_match_venue_without_coordinates_needs_strong_name_match():
    assert match_venue("Mohawk", None, VENUES) is CLUB
    assert match_venue("Mohawk Austin Outdoor", None, VENUES) is None  # single-word name isn't "contained"
    assert match_venue("Moody", None, VENUES) is None


def test_parse_venues_reads_wkt_point_and_skips_unlabelled():
    payload = {"results": {"bindings": [
        {"venue": {"value": "http://www.wikidata.org/entity/Q100"}, "venueLabel": {"value": "Moody Center"},
         "capacity": {"value": "15000"}, "location": {"value": "Point(-97.7322 30.2817)"}, "aliases": {"value": "Moody Center ATX"}},
        {"venue": {"value": "http://www.wikidata.org/entity/Q5"}, "venueLabel": {"value": "Q5"}, "capacity": {"value": "100"}},
    ]}}
    venues = parse_venues(payload)
    assert len(venues) == 1
    assert venues[0].coords == (30.2817, -97.7322) and venues[0].aliases == ["Moody Center ATX"]


def test_pick_article_requires_same_name_and_performer_description():
    pages = [
        {"title": "Low", "index": 1, "description": "Topics referred to by the same term", "pageprops": {"disambiguation": ""}},
        {"title": "Low (band)", "index": 2, "description": "American indie rock band"},
        {"title": "Low (David Bowie album)", "index": 3, "description": "1977 studio album"},
    ]
    assert pick_article("Low", pages) == "Low (band)"
    assert pick_article("Low", pages[:1] + pages[2:]) is None
    assert pick_article("Austin", [{"title": "Austin, Texas", "index": 1, "description": "City in Texas"}]) is None


def test_adjustments_multiply_within_bounds():
    s = tm_event("X", "Somewhere")
    s.add_adjustment(Adjustment("Venue capacity", 1.5, "", []))
    s.add_adjustment(Adjustment("Artist popularity", 1.4, "", []))
    assert s.weight == round(1.0 * 1.5 * 1.4, 3)
    s.add_adjustment(Adjustment("other", 5.0, "", []))
    assert s.weight == ADJUSTMENT_BOUNDS[1] and s.base_weight == 1.0


def test_merge_keeps_adjustments_of_stronger_report():
    a = tm_event("Show", "Moody Center")
    a.add_adjustment(Adjustment("Venue capacity", 1.4, "Moody Center holds up to 15,000", [Source("Wikidata", "https://wd.test", NOW)]))
    b = Signal("event", "Show", a.start, a.end, 0.9, [Source("page", "https://page.test", NOW)])
    merged = merge_duplicates([b, a])
    assert len(merged) == 1
    assert merged[0].weight == a.weight and merged[0].adjustments[0].label == "Venue capacity"
    assert len(merged[0].sources) == 2


# ---------- end to end with mocked HTTP ----------

def _mock_wikimedia(router):
    router.get(url__startswith="https://query.wikidata.org/sparql").respond(200, json={"results": {"bindings": [
        {"venue": {"value": "http://www.wikidata.org/entity/Q100"}, "venueLabel": {"value": "Moody Center"},
         "capacity": {"value": "15000"}, "location": {"value": "Point(-97.7322 30.2817)"}},
    ]}})
    router.get(url__startswith="https://en.wikipedia.org/w/api.php", params={"gsrsearch": "Big Star Act"}).respond(200, json={
        "query": {"pages": [{"title": "Big Star Act", "index": 1, "description": "American pop singer"}]}})
    router.get(url__startswith="https://en.wikipedia.org/w/api.php").respond(200, json={"query": {"pages": []}})
    router.get(url__regex=r"https://wikimedia\.org/api/rest_v1/metrics/pageviews/per-article/en\.wikipedia/all-access/user/Big_Star_Act/").respond(
        200, json={"items": [{"timestamp": f"2025{m:02d}0100", "views": 1_000_000} for m in range(1, 13)]})


async def test_enrich_events_sizes_venue_and_artist_with_sources(fetcher):
    big = tm_event("Big Star Act Live", "Moody Center", (30.2818, -97.7321), ["Big Star Act"])
    small = tm_event("Local Band", "Somebody's Bar", (30.27, -97.74), ["Totally Unknown Local Band"])
    game = tm_event("Longhorns vs Aggies", "Moody Center", (30.2818, -97.7321), ["Texas Longhorns"], category="Sports / Basketball")
    trace = []
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        _mock_wikimedia(router)
        await enrich_events(fetcher, LOC, [big, small, game], 25, TODAY, trace)

    labels = {a.label: a for a in big.adjustments}
    assert set(labels) == {"Venue capacity", "Artist popularity"}
    assert "15,000" in labels["Venue capacity"].detail
    assert labels["Venue capacity"].sources[0].url == "http://www.wikidata.org/entity/Q100"
    assert labels["Artist popularity"].factor == popularity_factor(1_000_000)
    assert [s.publisher for s in labels["Artist popularity"].sources] == ["Wikipedia", "Wikimedia pageviews"]
    assert big.weight > big.base_weight

    # unknown venue -> labelled assumption with no source; unknown artist -> no adjustment
    assert [(a.label, a.factor, a.assumed) for a in small.adjustments] == [("Venue capacity", 0.7, True)]
    # sports: venue yes, artist popularity not attempted
    assert [a.label for a in game.adjustments] == ["Venue capacity"]
    summary = {c.source: c.detail for c in trace if c.source in ("Venue capacity", "Artist popularity")}
    assert "sized 1 of 2 venues (1 from Wikidata" in summary["Venue capacity"]
    assert "matched 1 of 2 artists" in summary["Artist popularity"]


async def test_ticketmaster_wiki_link_skips_search(fetcher):
    ev = tm_event("Show", "Nowhere", None, [])
    ev.performers = [Performer("Big Star Act", "https://en.wikipedia.org/wiki/Big_Star_Act")]
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        _mock_wikimedia(router)
        search = router.routes[1]
        await enrich_events(fetcher, LOC, [ev], 25, TODAY, [])
    assert not search.called
    assert [a.label for a in ev.adjustments] == ["Venue capacity", "Artist popularity"]
    assert ev.adjustments[0].assumed and not ev.adjustments[1].assumed
