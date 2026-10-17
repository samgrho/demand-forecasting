"""Runtime configuration, read from environment variables (or a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    # Identifies this scraper to the sites it visits. Site operators (and the
    # OpenStreetMap / Wikimedia usage policies) expect a way to contact you.
    contact: str = os.getenv("SCRAPER_CONTACT", "")
    app_name: str = "HotelDemandForecaster/0.1"

    ticketmaster_api_key: str = os.getenv("TICKETMASTER_API_KEY", "")

    cache_path: Path = Path(os.getenv("CACHE_PATH", str(ROOT / "data" / "cache.sqlite3")))

    # Minimum seconds between two requests to the same host. A site's
    # robots.txt Crawl-delay overrides this when it asks for more.
    min_host_interval: float = float(os.getenv("MIN_HOST_INTERVAL", "2.0"))
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "20"))
    max_page_bytes: int = int(os.getenv("MAX_PAGE_BYTES", str(5 * 1024 * 1024)))

    @property
    def user_agent(self) -> str:
        if self.contact:
            return f"{self.app_name} (+contact: {self.contact})"
        return f"{self.app_name} (hotel demand research tool)"


settings = Settings()
