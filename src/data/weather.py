from __future__ import annotations

import pandas as pd
import requests

from config import GR_TIMEZONE, RAW_DIR, WEATHER_LOCATIONS

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY_VARS = [
    "temperature_2m",
    "wind_speed_100m",
    "wind_direction_100m",
    "cloud_cover",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
]


def _fetch(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_weather(start: str, end: str, forecast: bool = False) -> pd.DataFrame:
    frames = []
    for loc in WEATHER_LOCATIONS:
        params = {
            "latitude": loc["lat"],
            "longitude": loc["lon"],
            "hourly": ",".join(HOURLY_VARS),
            "timezone": GR_TIMEZONE,
        }
        if forecast:
            params["forecast_days"] = 7
            url = FORECAST_URL
        else:
            params["start_date"] = start
            params["end_date"] = end
            url = ARCHIVE_URL
        data = _fetch(url, params)
        h = data["hourly"]
        df = pd.DataFrame(h)
        df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(GR_TIMEZONE)
        df = df.set_index("time")
        df.columns = [f"{loc['name'].lower()}_{c}" for c in df.columns]
        frames.append(df)
    out = pd.concat(frames, axis=1)
    return out


def save(start: str, end: str) -> None:
    df = fetch_weather(start, end, forecast=False)
    path = RAW_DIR / f"weather_{start}_{end}.parquet"
    df.to_parquet(path)
    print(f"  saved {path.name}  rows={len(df)}  cols={len(df.columns)}")
