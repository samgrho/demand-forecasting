"""FastAPI entrypoint."""

from fastapi import FastAPI

from apps.api.config import settings
from apps.api.routers import health, forecast

app = FastAPI(title=settings.app_name)

app.include_router(health.router)
app.include_router(forecast.router)
