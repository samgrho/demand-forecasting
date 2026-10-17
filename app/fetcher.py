"""Polite HTTP fetching.

Rules this module enforces for every request:

* Identifies itself with a descriptive User-Agent (set SCRAPER_CONTACT so site
  operators can reach you).
* Web pages (kind="page") are only fetched if the site's robots.txt allows it.
  Following RFC 9309: a missing robots.txt (4xx) means "allowed", an
  unreachable one (5xx / network error) means "disallowed".
* Official APIs (kind="api") are used under their own terms of service, so
  robots.txt is not consulted for them, but they get the same throttling,
  User-Agent and caching.
* At most one request in flight per host, spaced by MIN_HOST_INTERVAL seconds
  or the site's Crawl-delay, whichever is larger.
* Responses are cached, so repeat lookups don't re-hit the site.
* No retries, no logins, no cookies, nothing behind a paywall; only http(s).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.robotparser import RobotFileParser

import httpx

from .cache import CachedResponse, ResponseCache
from .config import Settings, settings as default_settings
from .models import SourceCheck

ROBOTS_TTL = timedelta(hours=24)
SECRET_PARAMS = {"apikey", "api_key", "key", "token", "access_token"}


class FetchBlocked(Exception):
    """The site asked not to be fetched (robots.txt) or the URL is not allowed."""


class FetchFailed(Exception):
    """Network error or non-success HTTP status."""


@dataclass
class FetchResult:
    url: str
    status: int
    content_type: str
    text: str
    fetched_at: datetime
    from_cache: bool

    def json(self):
        import json

        return json.loads(self.text)


def redact(url: str) -> str:
    """Strip API keys from a URL before it is logged or shown to the user."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    query = [(k, "REDACTED" if k.lower() in SECRET_PARAMS else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit(parts._replace(query=urlencode(query)))


def build_url(url: str, params: dict | None) -> str:
    if not params:
        return url
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True) + [(k, str(v)) for k, v in params.items() if v is not None]
    return urlunsplit(parts._replace(query=urlencode(query)))


class PoliteFetcher:
    def __init__(
        self,
        cache: ResponseCache,
        client: httpx.AsyncClient | None = None,
        settings: Settings = default_settings,
    ):
        self.settings = settings
        self.cache = cache
        self._client = client or httpx.AsyncClient(
            timeout=settings.request_timeout,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en"},
        )
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}

    @property
    def ua_token(self) -> str:
        return self.settings.app_name.split("/")[0]

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(
        self,
        url: str,
        *,
        source: str,
        params: dict | None = None,
        kind: str = "page",
        ttl: timedelta = timedelta(hours=12),
        min_interval: float | None = None,
        headers: dict | None = None,
        trace: list[SourceCheck] | None = None,
    ) -> FetchResult:
        full_url = build_url(url, params)
        shown = redact(full_url)
        log = trace.append if trace is not None else (lambda _c: None)

        parts = urlsplit(full_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            log(SourceCheck(source, shown, "blocked", "only http(s) URLs are fetched"))
            raise FetchBlocked(f"unsupported URL: {shown}")

        key = hashlib.sha256(full_url.encode()).hexdigest()
        cached = self.cache.get(key, ttl)
        if cached is not None:
            log(SourceCheck(source, shown, "cached", f"fetched {cached.fetched_at:%Y-%m-%d %H:%M} UTC"))
            return FetchResult(cached.url, cached.status, cached.content_type, cached.text, cached.fetched_at, True)

        crawl_delay = 0.0
        if kind == "page":
            robots = await self._robots_for(parts)
            if not robots.can_fetch(self.ua_token, full_url):
                log(SourceCheck(source, shown, "blocked", "disallowed by the site's robots.txt"))
                raise FetchBlocked(f"robots.txt disallows {shown}")
            crawl_delay = float(robots.crawl_delay(self.ua_token) or 0)

        interval = max(min_interval if min_interval is not None else self.settings.min_host_interval, crawl_delay)
        try:
            resp = await self._throttled_get(parts.netloc, full_url, interval, headers)
        except httpx.HTTPError as exc:
            log(SourceCheck(source, shown, "error", f"network error: {type(exc).__name__}"))
            raise FetchFailed(str(exc)) from exc

        if resp.status_code != 200:
            log(SourceCheck(source, shown, "error", f"HTTP {resp.status_code}"))
            raise FetchFailed(f"HTTP {resp.status_code} for {shown}")

        result = FetchResult(
            url=str(resp.url),
            status=resp.status_code,
            content_type=resp.headers.get("content-type", ""),
            text=resp.text,
            fetched_at=datetime.now(timezone.utc),
            from_cache=False,
        )
        self.cache.put(key, CachedResponse(result.url, result.status, result.content_type, result.text, result.fetched_at))
        log(SourceCheck(source, shown, "ok", f"HTTP {resp.status_code}"))
        return result

    async def _throttled_get(self, host: str, url: str, interval: float, headers: dict | None) -> httpx.Response:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._host_last.get(host, 0.0) + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with self._client.stream("GET", url, headers=headers) as resp:
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.settings.max_page_bytes:
                            break
                    # Rebuild a fully-read response from the (possibly truncated),
                    # already-decompressed body.
                    headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in ("content-encoding", "content-length")]
                    return httpx.Response(resp.status_code, headers=headers, content=bytes(body), request=resp.request)
            finally:
                self._host_last[host] = time.monotonic()

    def _robots_fresh(self, origin: str) -> bool:
        parser = self._robots.get(origin)
        return parser is not None and time.time() - parser.mtime() < ROBOTS_TTL.total_seconds()

    async def _robots_for(self, parts) -> RobotFileParser:
        origin = f"{parts.scheme}://{parts.netloc}"
        if self._robots_fresh(origin):
            return self._robots[origin]
        lock = self._robots_locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if self._robots_fresh(origin):
                return self._robots[origin]
            robots_url = origin + "/robots.txt"
            parser = RobotFileParser(robots_url)
            key = hashlib.sha256(("robots:" + robots_url).encode()).hexdigest()
            cached = self.cache.get(key, ROBOTS_TTL)
            if cached is not None:
                status, text = cached.status, cached.text
            else:
                try:
                    resp = await self._throttled_get(parts.netloc, robots_url, self.settings.min_host_interval, None)
                    status, text = resp.status_code, resp.text
                except httpx.HTTPError:
                    status, text = 599, ""
                if status < 500:  # don't remember outages for a whole day
                    self.cache.put(key, CachedResponse(robots_url, status, "text/plain", text, datetime.now(timezone.utc)))

            if status == 200:
                parser.parse(text.splitlines())
            elif 400 <= status < 500:
                parser.allow_all = True
            else:
                parser.disallow_all = True
            # RobotFileParser.can_fetch() refuses everything until it thinks it
            # has read the file; mark it as read.
            parser.last_checked = time.time()
            self._robots[origin] = parser
            return parser
