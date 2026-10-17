"""Application settings loaded from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Demand Forecasting API", alias="APP_NAME")
    env: str = Field(default="development", alias="ENV")
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/demand_forecasting",
        alias="DATABASE_URL",
    )

    model_config = SettingsConfigDict(case_sensitive=False)


settings = Settings()
