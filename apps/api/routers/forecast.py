from fastapi import APIRouter

from apps.api.schemas.forecast import ForecastRequest, ForecastResponse
from data_pipeline.inference.predict import predict_demand

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.post("", response_model=ForecastResponse)
def forecast(request: ForecastRequest) -> ForecastResponse:
    score, confidence = predict_demand(request.location, request.start_date, request.end_date)
    return ForecastResponse(
        location=request.location,
        start_date=request.start_date,
        end_date=request.end_date,
        demand_score=score,
        confidence=confidence,
        evidence=[],
    )
