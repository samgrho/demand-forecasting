"""Seasonal travel interest from Wikimedia pageview statistics (free, no key).

Views of a destination's Wikivoyage travel guide (or, failing that, its
Wikipedia article) are a public proxy for how many people are planning trips
there in each month. Three full years are combined into a month-of-year index
where 1.0 = an average month (see month_index for how).

API docs: https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import quote

from ..fetcher import FetchBlocked, FetchFailed, PoliteFetcher, redact
from ..models import Location, Source, SourceCheck

PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
WBAPI = "https://www.wikidata.org/w/api.php"
PUBLISHER = "Wikimedia pageviews"
YEARS = 3
MIN_MONTHLY = 5000


@dataclass
class SeasonalProfile:
    page_title: str
    project: str  # e.g. "en.wikivoyage"
    month_index: dict[int, float]  # 1..12 -> relative interest, mean 1.0
    monthly_views: dict[str, int]  # "YYYY-MM" -> views, for display
    source: Source

    def factor(self, day: date) -> float:
        return self.month_index.get(day.month, 1.0)


async def _sitelinks(fetcher: PoliteFetcher, qid: str, trace) -> dict[str, str]:
    try:
        res = await fetcher.get(
            WBAPI,
            source="Wikidata",
            params={"action": "wbgetentities", "ids": qid, "props": "sitelinks", "sitefilter": "enwikivoyage|enwiki", "format": "json"},
            kind="api",
            ttl=timedelta(days=30),
            min_interval=1.0,
            trace=trace,
        )
    except (FetchBlocked, FetchFailed):
        return {}
    links = res.json().get("entities", {}).get(qid, {}).get("sitelinks", {})
    return {site: v["title"] for site, v in links.items()}


def month_index(views: dict[str, int]) -> dict[int, float]:
    """Month-of-year index (mean 1.0) that ignores long-term trend and one-off spikes.

    Each consecutive 12-month window is scaled by its own mean (removes growth
    or decline of the page overall), then each calendar month takes the median
    across years (a single news spike doesn't move it).
    """
    months = sorted(views)
    by_month: dict[int, list[float]] = {}
    for i in range(0, len(months) - 11, 12):
        window = months[i : i + 12]
        mean = sum(views[m] for m in window) / 12
        if mean <= 0:
            continue
        for m in window:
            by_month.setdefault(int(m[5:7]), []).append(views[m] / mean)
    medians = {m: statistics.median(v) for m, v in by_month.items()}
    if len(medians) < 12:
        return {}
    overall = sum(medians.values()) / 12
    return {m: round(v / overall, 3) for m, v in medians.items()}


async def seasonal_profile(fetcher: PoliteFetcher, loc: Location, today: date, trace: list[SourceCheck]) -> SeasonalProfile | None:
    candidates: list[tuple[str, str]] = []  # (project, title)
    if loc.wikidata_id:
        links = await _sitelinks(fetcher, loc.wikidata_id, trace)
        # Wikivoyage views are closer to travel intent, but most guides get too
        # little traffic to be stable; those only win if they clear MIN_MONTHLY.
        if "enwikivoyage" in links:
            candidates.append(("en.wikivoyage", links["enwikivoyage"]))
        if "enwiki" in links:
            candidates.append(("en.wikipedia", links["enwiki"]))
    if not candidates and loc.wikipedia_title and ":" in loc.wikipedia_title:
        lang, title = loc.wikipedia_title.split(":", 1)
        candidates.append((f"{lang}.wikipedia", title))
    if not candidates:
        trace.append(SourceCheck(PUBLISHER, PAGEVIEWS, "skipped", "no Wikivoyage/Wikipedia page linked to this location"))
        return None

    first = date(today.year - YEARS, today.month, 1)
    last = date(today.year, today.month, 1) - timedelta(days=1)
    for project, title in candidates:
        slug = quote(title.replace(" ", "_"), safe="")
        url = f"{PAGEVIEWS}/{project}/all-access/user/{slug}/monthly/{first:%Y%m%d}00/{last:%Y%m%d}00"
        try:
            res = await fetcher.get(url, source=PUBLISHER, kind="api", ttl=timedelta(days=7), min_interval=0.5, trace=trace)
        except (FetchBlocked, FetchFailed):
            continue
        views = {item["timestamp"][:4] + "-" + item["timestamp"][4:6]: int(item["views"]) for item in res.json().get("items", [])}
        index = month_index(views)
        if len(index) < 12:
            continue
        if project.endswith("wikivoyage") and sum(views.values()) / len(views) < MIN_MONTHLY and len(candidates) > 1:
            trace.append(SourceCheck(PUBLISHER, redact(url), "skipped", f"Wikivoyage traffic below {MIN_MONTHLY}/month; too noisy"))
            continue
        human = (
            f"https://pageviews.wmcloud.org/?project={project}.org&platform=all-access&agent=user"
            f"&start={first:%Y-%m-%d}&end={last:%Y-%m-%d}&pages={quote(title.replace(' ', '_'))}"
        )
        return SeasonalProfile(title, project, index, views, Source(f"{PUBLISHER} ({project}.org)", human, res.fetched_at))
    return None
