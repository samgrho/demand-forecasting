"""FastAPI app: JSON API plus the dashboard page."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .cache import ResponseCache
from .config import settings
from .fetcher import PoliteFetcher
from .models import to_jsonable
from .service import BadRequest, ForecastRequest, run_forecast
from .sources.geocode import LocationNotFound

HERE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.fetcher = PoliteFetcher(ResponseCache(settings.cache_path))
    yield
    await app.state.fetcher.aclose()


app = FastAPI(title="Hotel Demand Forecaster", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


class ForecastIn(BaseModel):
    location: str = Field(..., max_length=200)
    start: date
    end: date
    radius_km: int = 25
    source_urls: list[str] = Field(default_factory=list, max_length=20)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"ticketmaster_enabled": bool(settings.ticketmaster_api_key), "contact_set": bool(settings.contact)},
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "ticketmaster": bool(settings.ticketmaster_api_key), "contact_set": bool(settings.contact)}


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
