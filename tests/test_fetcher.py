import httpx
import pytest
import respx

from app.fetcher import FetchBlocked, FetchFailed, redact


@respx.mock
async def test_robots_disallow_blocks_page(fetcher):
    respx.get("https://site.test/robots.txt").respond(200, text="User-agent: *\nDisallow: /private/\n")
    page = respx.get("https://site.test/private/events").respond(200, text="secret")
    trace = []
    with pytest.raises(FetchBlocked):
        await fetcher.get("https://site.test/private/events", source="site", trace=trace)
    assert not page.called
    assert trace[-1].outcome == "blocked"
    assert "robots.txt" in trace[-1].detail


@respx.mock
async def test_robots_allows_other_paths(fetcher):
    respx.get("https://site.test/robots.txt").respond(200, text="User-agent: *\nDisallow: /private/\n")
    respx.get("https://site.test/events").respond(200, text="<html></html>", headers={"content-type": "text/html"})
    res = await fetcher.get("https://site.test/events", source="site")
    assert res.status == 200
    assert not res.from_cache


@respx.mock
async def test_robots_rule_for_our_user_agent(fetcher):
    respx.get("https://site.test/robots.txt").respond(
        200, text="User-agent: HotelDemandForecaster\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    )
    with pytest.raises(FetchBlocked):
        await fetcher.get("https://site.test/events", source="site")


@respx.mock
async def test_missing_robots_means_allowed(fetcher):
    respx.get("https://site.test/robots.txt").respond(404)
    respx.get("https://site.test/events").respond(200, text="ok")
    res = await fetcher.get("https://site.test/events", source="site")
    assert res.text == "ok"


@respx.mock
async def test_unreachable_robots_means_disallowed(fetcher):
    respx.get("https://site.test/robots.txt").respond(503)
    page = respx.get("https://site.test/events").respond(200, text="ok")
    with pytest.raises(FetchBlocked):
        await fetcher.get("https://site.test/events", source="site")
    assert not page.called


@respx.mock
async def test_api_requests_skip_robots(fetcher):
    robots = respx.get("https://api.test/robots.txt").respond(200, text="User-agent: *\nDisallow: /\n")
    respx.get("https://api.test/v1/things").respond(200, json={"ok": True})
    res = await fetcher.get("https://api.test/v1/things", source="api", kind="api")
    assert res.json() == {"ok": True}
    assert not robots.called


@respx.mock
async def test_responses_are_cached(fetcher):
    route = respx.get("https://api.test/v1/things").respond(200, json={"n": 1})
    first = await fetcher.get("https://api.test/v1/things", source="api", kind="api")
    trace = []
    second = await fetcher.get("https://api.test/v1/things", source="api", kind="api", trace=trace)
    assert route.call_count == 1
    assert not first.from_cache and second.from_cache
    assert trace[-1].outcome == "cached"


@respx.mock
async def test_sends_identifying_user_agent(fetcher):
    route = respx.get("https://api.test/ua").respond(200, text="ok")
    await fetcher.get("https://api.test/ua", source="api", kind="api")
    ua = route.calls[0].request.headers["user-agent"]
    assert ua.startswith("HotelDemandForecaster/") and "tests@example.com" in ua


@respx.mock
async def test_http_error_is_reported(fetcher):
    respx.get("https://api.test/broken").respond(500)
    trace = []
    with pytest.raises(FetchFailed):
        await fetcher.get("https://api.test/broken", source="api", kind="api", trace=trace)
    assert trace[-1].outcome == "error"


@respx.mock
async def test_network_error_is_reported(fetcher):
    respx.get("https://api.test/down").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(FetchFailed):
        await fetcher.get("https://api.test/down", source="api", kind="api")


async def test_non_http_urls_are_refused(fetcher):
    with pytest.raises(FetchBlocked):
        await fetcher.get("file:///etc/passwd", source="x")


@respx.mock
async def test_gzip_body_is_decoded_once(fetcher):
    import gzip

    respx.get("https://api.test/gz").respond(
        200, content=gzip.compress(b'{"a": 1}'), headers={"content-encoding": "gzip", "content-type": "application/json"}
    )
    res = await fetcher.get("https://api.test/gz", source="api", kind="api")
    assert res.json() == {"a": 1}


def test_redact_hides_api_keys():
    url = "https://app.ticketmaster.com/discovery/v2/events.json?apikey=SECRET&size=10"
    assert "SECRET" not in redact(url)
    assert "size=10" in redact(url)
