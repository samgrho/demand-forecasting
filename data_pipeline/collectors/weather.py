"""Weather signal collector using free weather APIs (e.g., Open-Meteo)."""


def collect_weather_signal(latitude: float, longitude: float, start_date: str, end_date: str) -> dict:
    _ = (latitude, longitude, start_date, end_date)
    # TODO: map location -> lat/lon and request API
    return {"weather_severity_index": 0.0}
