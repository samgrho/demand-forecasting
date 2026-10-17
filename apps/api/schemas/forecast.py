from datetime import date
from pydantic import BaseModel, Field


class ForecastRequest(BaseModel):
    location: str = Field(..., description="City or localized region")
    start_date: date
    end_date: date


class EvidenceItem(BaseModel):
    source_name: str
    source_url: str
    observed_at: str
    summary: str
    relevance_score: float


class ForecastResponse(BaseModel):
    location: str
    start_date: date
    end_date: date
    demand_score: float
    confidence: float
    evidence: list[EvidenceItem]
