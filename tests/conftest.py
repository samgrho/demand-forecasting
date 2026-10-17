from dataclasses import replace

import httpx
import pytest

from app.cache import ResponseCache
from app.config import settings
from app.fetcher import PoliteFetcher

TEST_SETTINGS = replace(settings, min_host_interval=0.0, contact="tests@example.com")


@pytest.fixture
def cache():
    return ResponseCache(":memory:")


@pytest.fixture
async def fetcher(cache):
    client = httpx.AsyncClient(headers={"User-Agent": TEST_SETTINGS.user_agent})
    f = PoliteFetcher(cache, client=client, settings=TEST_SETTINGS)
    yield f
    await f.aclose()
