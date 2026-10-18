from datetime import date, datetime, timedelta, timezone

from app import forecast
from app.models import Signal, Source
from app.sources.pageviews import SeasonalProfile, month_index

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def sig(title, start, end=None, weight=1.0, kind="event", url=None):
    return Signal(kind, title, start, end or start, weight, [Source("test", url or f"https://src.test/{title}", NOW)])


def test_no_signals_sits_at_baseline():
    days = forecast.score_days([], date(2026, 10, 1), date(2026, 10, 3), None)
    assert [d.score for d in days] == [forecast.BASELINE] * 3
    assert all(not d.drivers for d in days)


def test_events_raise_score_with_diminishing_returns():
    d = date(2026, 10, 10)
    one = forecast.score_days([sig("A", d)], d, d, None)[0].score
    two = forecast.score_days([sig("A", d), sig("B", d)], d, d, None)[0].score
    three = forecast.score_days([sig("A", d), sig("B", d), sig("C", d)], d, d, None)[0].score
    assert forecast.BASELINE < one < two < three < 100
    assert (two - one) > (three - two)


def test_big_event_adds_arrival_night():
    ev = sig("Marathon", date(2026, 11, 8), weight=1.2)
    days = forecast.score_days([ev], date(2026, 11, 6), date(2026, 11, 8), None)
    by_day = {d.day: d for d in days}
    assert by_day[date(2026, 11, 6)].pressure == 0
    assert by_day[date(2026, 11, 7)].drivers[0].role == "arrival night"
    assert by_day[date(2026, 11, 8)].drivers[0].role == "on the day"
    assert by_day[date(2026, 11, 8)].score > by_day[date(2026, 11, 7)].score > by_day[date(2026, 11, 6)].score


def test_small_event_has_no_arrival_night():
    ev = sig("Book club", date(2026, 11, 8), weight=0.3)
    days = forecast.score_days([ev], date(2026, 11, 7), date(2026, 11, 7), None)
    assert days[0].drivers == []


def test_merge_duplicates_combines_sources():
    a = sig("U.S. Grand Prix", date(2026, 10, 23), weight=1.0, url="https://a.test/1")
    b = sig("U.S. Grand-Prix", date(2026, 10, 23), weight=1.2, url="https://b.test/2")
    b.end = date(2026, 10, 25)
    merged = forecast.merge_duplicates([a, b])
    assert len(merged) == 1
    m = merged[0]
    assert m.weight == 1.2 and m.end == date(2026, 10, 25)
    assert {s.url for s in m.sources} == {"https://a.test/1", "https://b.test/2"}
    # inputs untouched
    assert len(a.sources) == 1


def test_busy_periods_group_consecutive_days_and_cite_signals():
    fest = sig("Festival", date(2026, 10, 10), date(2026, 10, 12), weight=2.0)
    other = sig("Concert", date(2026, 10, 20), weight=2.5)
    signals = [fest, other]
    days = forecast.score_days(signals, date(2026, 10, 1), date(2026, 10, 31), None)
    periods = forecast.busy_periods(days, signals)
    spans = sorted((p.start, p.end) for p in periods)
    # The festival's arrival night (Oct 9) belongs to the same busy stretch.
    assert (date(2026, 10, 9), date(2026, 10, 12)) in spans
    for p in periods:
        assert p.signal_ids, "every busy period must point at sourced signals"
        assert all(signals[i].sources for i in p.signal_ids)


def test_seasonal_factor_shifts_baseline():
    profile = SeasonalProfile("X", "en.wikipedia", {m: 1.0 for m in range(1, 13)} | {7: 1.5}, {}, Source("w", "https://w.test", NOW))
    jul, aug = forecast.score_days([], date(2026, 7, 31), date(2026, 8, 1), profile)
    assert jul.baseline > aug.baseline


def test_month_index_ignores_trend_and_spikes():
    views = {}
    for y, scale in ((2023, 1.0), (2024, 2.0), (2025, 4.0)):  # page traffic doubling every year
        for m in range(1, 13):
            base = 200 if m == 7 else 100  # July is twice as popular
            views[f"{y}-{m:02d}"] = int(base * scale)
    views["2024-03"] *= 20  # one-off news spike
    idx = month_index(views)
    assert idx[7] > 1.6
    assert abs(idx[3] - idx[4]) < 0.01


def test_routine_event_load_is_part_of_the_baseline():
    start, end = date(2026, 11, 1), date(2026, 11, 28)
    nightly = [sig(f"Club night {i}", start, end, weight=0.8) for i in range(4)]  # every day, all month
    stadium = sig("Stadium show", date(2026, 11, 14), weight=1.8)
    holiday = sig("Thanksgiving", date(2026, 11, 26), weight=0.8, kind="holiday")
    days = {d.day: d for d in forecast.score_days(nightly + [stadium, holiday], start, end, None)}
    ordinary = days[date(2026, 11, 3)]
    assert ordinary.score == forecast.BASELINE and ordinary.routine_excluded == 3.2
    assert days[date(2026, 11, 14)].level in ("Busy", "Very busy")
    assert days[date(2026, 11, 13)].score > ordinary.score  # arrival night still counts
    assert days[date(2026, 11, 26)].score > ordinary.score  # holidays are never "routine"


def test_short_ranges_subtract_nothing():
    d = date(2026, 11, 1)
    days = forecast.score_days([sig("A", d, d + timedelta(days=3))], d, d + timedelta(days=3), None)
    assert all(x.routine_excluded == 0 and x.score > forecast.BASELINE for x in days)


def test_long_ranges_compare_each_weekday_with_its_own_kind():
    start, end = date(2026, 11, 2), date(2026, 11, 29)  # 4 weeks, Mon..Sun
    signals = []
    d = start
    while d <= end:
        n = 6 if d.weekday() == 5 else 2  # Saturdays always have 3x the shows
        signals += [sig(f"Show {d} {i}", d, weight=0.5) for i in range(n)]
        d += timedelta(days=1)
    signals.append(sig("Stadium concert", date(2026, 11, 14), weight=1.8))  # one special Saturday
    days = {x.day: x for x in forecast.score_days(signals, start, end, None)}
    assert days[date(2026, 11, 7)].score == forecast.BASELINE  # ordinary Saturday is "normal"
    assert days[date(2026, 11, 4)].score == forecast.BASELINE  # ordinary Wednesday too
    assert days[date(2026, 11, 14)].level in ("Busy", "Very busy")
