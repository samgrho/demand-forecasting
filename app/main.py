"""FastAPI app: JSON API plus the dashboard page."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .cache import ResponseCache
from .config import settings
from .fetcher import FetchBlocked, FetchFailed, PoliteFetcher
from .models import to_jsonable
from .service import BadRequest, ForecastRequest, run_forecast
from .sources.geocode import LocationNotFound
from .sources.ticketmaster import API as TICKETMASTER_API

HERE = Path(__file__).resolve().parent
# The server only ever runs on this machine. Refusing other Host headers stops
# a web page from reaching it through DNS rebinding.
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]

EMAIL_OR_URL = re.compile(r"^(?:[^@\s]+@[^@\s]+\.[^@\s]+|https?://\S+\.\S+)$")
API_KEY = re.compile(r"^[A-Za-z0-9]{8,100}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.fetcher = PoliteFetcher(ResponseCache(settings.cache_path))
    yield
    await app.state.fetcher.aclose()


app = FastAPI(title="Hotel Demand Forecaster", version=__version__, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


class ForecastIn(BaseModel):
    location: str = Field(..., max_length=200)
    start: date
    end: date
    radius_km: int = 25
    source_urls: list[str] = Field(default_factory=list, max_length=20)


class SettingsIn(BaseModel):
    # None = leave unchanged; "" = clear
    contact: str | None = Field(None, max_length=200)
    ticketmaster_api_key: str | None = Field(None, max_length=100)


def asset_url(request: Request, path: str) -> str:
    """Static URL with the file's modification time appended, so browsers fetch
    a fresh copy whenever the file changes instead of reusing a cached one."""
    version = int((HERE / "static" / path).stat().st_mtime)
    return f"{request.app.url_path_for('static', path=path)}?v={version}"


def settings_view() -> dict:
    """What the UI may see. Never includes the full API key."""
    key = settings.ticketmaster_api_key
    return {
        "contact": settings.contact,
        "ticketmaster": {"set": bool(key), "hint": f"…{key[-4:]}" if len(key) >= 8 else ""},
        "settings_path": str(settings.settings_path),
        "version": __version__,
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    response = templates.TemplateResponse(
        request,
        "index.html",
        {
            "ticketmaster_enabled": bool(settings.ticketmaster_api_key),
            "contact_set": bool(settings.contact),
            "version": __version__,
            "css_url": asset_url(request, "style.css"),
            "js_url": asset_url(request, "app.js"),
        },
    )
    # The page itself is tiny; always revalidate so it points at current assets.
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": __version__, "ticketmaster": bool(settings.ticketmaster_api_key), "contact_set": bool(settings.contact)}


@app.get("/api/settings")
async def get_settings():
    return settings_view()


async def check_ticketmaster_key(fetcher: PoliteFetcher, key: str) -> str:
    """'valid', 'invalid' or 'unreachable' — one tiny request to the Discovery API."""
    try:
        await fetcher.get(
            TICKETMASTER_API, source="Ticketmaster (key check)", params={"apikey": key, "size": 1},
            kind="api", ttl=timedelta(minutes=10), min_interval=0.25,
        )
        return "valid"
    except FetchFailed as exc:
        return "invalid" if re.search(r"HTTP 40[13]", str(exc)) else "unreachable"
    except FetchBlocked:
        return "unreachable"


@app.put("/api/settings")
async def put_settings(body: SettingsIn, request: Request):
    changes: dict[str, str] = {}
    if body.contact is not None:
        contact = body.contact.strip()
        if contact and not EMAIL_OR_URL.match(contact):
            raise HTTPException(400, "Contact must be an email address or a web address starting with http(s)://")
        changes["contact"] = contact
    check = None
    if body.ticketmaster_api_key is not None:
        key = body.ticketmaster_api_key.strip()
        if key and not API_KEY.match(key):
            raise HTTPException(400, "That doesn't look like a Ticketmaster key (letters and digits only, as shown under My Apps).")
        if key:
            check = await check_ticketmaster_key(request.app.state.fetcher, key)
            if check == "invalid":
                raise HTTPException(400, "Ticketmaster rejected that key. Copy the Consumer Key from developer.ticketmaster.com → My Apps.")
        changes["ticketmaster_api_key"] = key
    if changes:
        settings.update(**changes)
        request.app.state.fetcher.refresh_identity()
    return {**settings_view(), "ticketmaster_check": check}


@app.post("/api/forecast")
async def create_forecast(body: ForecastIn, request: Request):
    req = ForecastRequest(
        location=body.location,
        start=body.start,
        end=body.end,
        radius_km=body.radius_km,
        source_urls=[u for u in body.source_urls if u.strip()],
    )
    try:
        result = await run_forecast(request.app.state.fetcher, req)
    except LocationNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except BadRequest as exc:
        raise HTTPException(400, str(exc)) from exc
    return to_jsonable(result)
