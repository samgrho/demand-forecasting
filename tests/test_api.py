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
    with TestClient(app) as client:
        res = client.get("/")
    assert res.status_code == 200
    assert "Hotel Demand Forecaster" in res.text


def test_rejects_reversed_dates():
    with TestClient(app) as client:
        res = client.post("/api/forecast", json={"location": "Austin", "start": "2026-12-01", "end": "2026-11-01"})
    assert res.status_code == 400


def test_forecast_end_to_end_every_signal_has_a_source(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, cache_path=tmp_path / "c.sqlite3"))
    # Don't depend on the developer's .env (e.g. a real Ticketmaster key).
    monkeypatch.setattr(service, "settings", replace(service.settings, ticketmaster_api_key=""))
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router, TestClient(app) as client:
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
