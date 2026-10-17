"""Training entrypoint for baseline demand model."""

from pathlib import Path
import joblib
from xgboost import XGBRegressor

MODEL_PATH = Path("models/demand_xgb.joblib")


def train_model(X, y) -> Path:
    model = XGBRegressor(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
    )
    model.fit(X, y)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    return MODEL_PATH
