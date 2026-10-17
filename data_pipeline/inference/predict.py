"""Inference utilities for forecast endpoint."""

from datetime import date
import random


def predict_demand(location: str, start_date: date, end_date: date) -> tuple[float, float]:
    """Return a placeholder demand score and confidence.

    Replace with feature collection + trained model inference.
    """
    _ = (location, start_date, end_date)
    score = round(random.uniform(0.35, 0.82), 3)
    confidence = round(random.uniform(0.55, 0.9), 3)
    return score, confidence
