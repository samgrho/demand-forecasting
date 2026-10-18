"""Runtime configuration.

The two values a user sets (contact email and Ticketmaster key) are edited in
the app's Settings dialog and saved to a per-user settings.json:

* Installed app: %APPDATA%\\HotelDemandForecaster\\settings.json, with the
  response cache in %LOCALAPPDATA%\\HotelDemandForecaster.
* Running from source: data/settings.json and data/cache.sqlite3; values in a
  local .env file are used as defaults until settings.json overrides them.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from . import __version__

APP_ID = "HotelDemandForecaster"
ROOT = Path(__file__).resolve().parent.parent
FROZEN = bool(getattr(sys, "frozen", False))  # running from the PyInstaller build

if FROZEN:
    CONFIG_DIR = Path(os.getenv("APPDATA") or Path.home()) / APP_ID
    DATA_DIR = Path(os.getenv("LOCALAPPDATA") or Path.home()) / APP_ID
else:
    load_dotenv(ROOT / ".env")
    CONFIG_DIR = DATA_DIR = ROOT / "data"

EDITABLE = ("contact", "ticketmaster_api_key")


@dataclass
class Settings:
    # Identifies this scraper to the sites it visits. Site operators (and the
    # OpenStreetMap / Wikimedia usage policies) expect a way to contact you.
    contact: str = ""
    ticketmaster_api_key: str = ""
    app_name: str = f"{APP_ID}/{__version__}"

    cache_path: Path = DATA_DIR / "cache.sqlite3"
    settings_path: Path = field(default=CONFIG_DIR / "settings.json")

    # Minimum seconds between two requests to the same host. A site's
    # robots.txt Crawl-delay overrides this when it asks for more.
    min_host_interval: float = 2.0
    request_timeout: float = 20.0
    max_page_bytes: int = 5 * 1024 * 1024

    @property
    def user_agent(self) -> str:
        if self.contact:
            return f"{self.app_name} (+contact: {self.contact})"
        return f"{self.app_name} (hotel demand research tool)"

    def update(self, **values: str) -> None:
        """Change user-editable values and persist them."""
        for key, value in values.items():
            if key in EDITABLE:
                setattr(self, key, value.strip())
        self.save()

    def save(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.settings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: getattr(self, k) for k in EDITABLE}, indent=2), encoding="utf-8")
        tmp.replace(self.settings_path)


def load_settings() -> Settings:
    s = Settings(
        contact=os.getenv("SCRAPER_CONTACT", ""),
        ticketmaster_api_key=os.getenv("TICKETMASTER_API_KEY", ""),
        cache_path=Path(os.getenv("CACHE_PATH", str(DATA_DIR / "cache.sqlite3"))),
        min_host_interval=float(os.getenv("MIN_HOST_INTERVAL", "2.0")),
        request_timeout=float(os.getenv("REQUEST_TIMEOUT", "20")),
        max_page_bytes=int(os.getenv("MAX_PAGE_BYTES", str(5 * 1024 * 1024))),
    )
    try:
        saved = json.loads(s.settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    for key in EDITABLE:
        if isinstance(saved.get(key), str):
            setattr(s, key, saved[key])
    return s


settings = load_settings()
