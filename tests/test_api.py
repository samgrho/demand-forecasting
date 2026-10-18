from dataclasses import replace

import respx
from fastapi.testclient import TestClient

from app import main, service
from app.main import app


def _mock_sources(router):
    router.get(url__startswith="https://nominatim.openstreetmap.org/").respond(200, json=[{
        "lat": "30.27", "lon": "-97.74", "display_name": "Testville", "osm_type": "relation", "osm_id": 1,
        "address": {"country_code": "us", "ISO3166-2-lvl4": "US-TX"}, "extratags": {},
    }])
    router.get(url__startswith="https://date.nager.at/api/v3/PublicHolidays/").respond(200, json=[
        {"date": "2026-11-26", "localName": "Thanksgiving Day", "name": "Thanksgiving Day", "global": True},
    ])
    router.get(url__startswith="https://date.nager.at/api/v3/LongWeekend/").respond(200, json=[])


def test_dashboard_renders():
    with TestClient(app, base_url="http://localhost") as client:
        res = client.get("/")
    assert res.status_code == 200
    assert "Hotel Demand Forecaster" in res.text


def test_rejects_reversed_dates():
    with TestClient(app, base_url="http://localhost") as client:
        res = client.post("/api/forecast", json={"location": "Austin", "start": "2026-12-01", "end": "2026-11-01"})
    assert res.status_code == 400


def test_forecast_end_to_end_every_signal_has_a_source(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, cache_path=tmp_path / "c.sqlite3"))
    # Don't depend on the developer's .env (e.g. a real Ticketmaster key).
    monkeypatch.setattr(service, "settings", replace(service.settings, ticketmaster_api_key=""))
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router, TestClient(app, base_url="http://localhost") as client:
        _mock_sources(router)
        res = client.post("/api/forecast", json={
            "location": "Testville", "start": "2026-11-20", "end": "2026-11-30", "radius_km": 25,
        })
    assert res.status_code == 200, res.text
    data = res.json()
    assert len(data["days"]) == 11
    assert data["signals"], "expected the mocked holiday"
    for s in data["signals"]:
        assert s["sources"] and all(src["url"].startswith("https://") for src in s["sources"])
    thanksgiving = next(d for d in data["days"] if d["day"] == "2026-11-26")
    assert thanksgiving["score"] > data["model"]["baseline"]
    outcomes = {c["source"]: c["outcome"] for c in data["source_log"]}
    assert outcomes["Ticketmaster"] == "skipped"


def _isolated_settings(tmp_path, monkeypatch, **values):
    """Point the shared settings object at a temp file for this test."""
    from app.config import settings
    monkeypatch.setattr(settings, "settings_path", tmp_path / "settings.json")
    monkeypatch.setattr(settings, "contact", values.get("contact", ""))
    monkeypatch.setattr(settings, "ticketmaster_api_key", values.get("key", ""))
    monkeypatch.setattr(settings, "cache_path", tmp_path / "c.sqlite3")
    return settings


def test_other_hosts_are_refused():
    with TestClient(app, base_url="http://evil.example") as client:
        assert client.get("/api/health").status_code == 400


def test_settings_never_expose_the_key(tmp_path, monkeypatch):
    _isolated_settings(tmp_path, monkeypatch, contact="me@example.com", key="ABCDEFGH12345678")
    with TestClient(app, base_url="http://localhost") as client:
        data = client.get("/api/settings").json()
    assert data["contact"] == "me@example.com"
    assert data["ticketmaster"] == {"set": True, "hint": "…5678"}
    assert "ABCDEFGH12345678" not in str(data)


def test_save_settings_checks_key_and_persists(tmp_path, monkeypatch):
    import json
    s = _isolated_settings(tmp_path, monkeypatch)
    with respx.mock(assert_all_mocked=True) as router, TestClient(app, base_url="http://localhost") as client:
        router.get(url__startswith="https://app.ticketmaster.com/").respond(200, json={"page": {"totalPages": 0}})
        res = client.put("/api/settings", json={"contact": "me@example.com", "ticketmaster_api_key": "GOODKEY12345"})
        assert res.status_code == 200, res.text
        assert res.json()["ticketmaster_check"] == "valid"
        # the live fetcher picked up the new contact
        assert "me@example.com" in client.app.state.fetcher._client.headers["User-Agent"]
    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved == {"contact": "me@example.com", "ticketmaster_api_key": "GOODKEY12345"}
    assert s.ticketmaster_api_key == "GOODKEY12345"


def test_rejected_key_is_not_saved(tmp_path, monkeypatch):
    s = _isolated_settings(tmp_path, monkeypatch, key="OLDKEY123456")
    with respx.mock(assert_all_mocked=True) as router, TestClient(app, base_url="http://localhost") as client:
        router.get(url__startswith="https://app.ticketmaster.com/").respond(401, json={"fault": {}})
        res = client.put("/api/settings", json={"ticketmaster_api_key": "BADKEY123456"})
    assert res.status_code == 400 and "rejected" in res.json()["detail"]
    assert s.ticketmaster_api_key == "OLDKEY123456"
    assert not (tmp_path / "settings.json").exists()


def test_settings_validation_and_clearing(tmp_path, monkeypatch):
    s = _isolated_settings(tmp_path, monkeypatch, contact="me@example.com", key="OLDKEY123456")
    with TestClient(app, base_url="http://localhost") as client:
        assert client.put("/api/settings", json={"contact": "not an email"}).status_code == 400
        assert client.put("/api/settings", json={"ticketmaster_api_key": "has spaces in it"}).status_code == 400
        res = client.put("/api/settings", json={"ticketmaster_api_key": ""})  # remove the key
    assert res.status_code == 200 and res.json()["ticketmaster"]["set"] is False
    assert s.contact == "me@example.com" and s.ticketmaster_api_key == ""
