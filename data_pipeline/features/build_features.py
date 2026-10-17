"""Feature engineering pipeline."""

import pandas as pd


def build_features(raw_rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(raw_rows)
    if df.empty:
        return pd.DataFrame(
            [
                {
                    "event_count": 0,
                    "trend_index": 0,
                    "weather_severity_index": 0,
                    "is_holiday": 0,
                    "is_weekend": 0,
                }
            ]
        )
    return df
