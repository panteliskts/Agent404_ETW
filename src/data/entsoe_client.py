from __future__ import annotations

import pandas as pd
from entsoe import EntsoePandasClient

from config import ENTSOE_API_KEY, GR_BIDDING_ZONE, GR_TIMEZONE, RAW_DIR


def _client() -> EntsoePandasClient:
    if not ENTSOE_API_KEY:
        raise RuntimeError(
            "ENTSOE_API_KEY missing. Register at transparency.entsoe.eu, request the "
            "Restful API token, then put it in .env"
        )
    return EntsoePandasClient(api_key=ENTSOE_API_KEY)


def _ts(start: str, end: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    s = pd.Timestamp(start, tz=GR_TIMEZONE)
    e = pd.Timestamp(end, tz=GR_TIMEZONE)
    return s, e


def fetch_dam_prices(start: str, end: str) -> pd.Series:
    s, e = _ts(start, end)
    px = _client().query_day_ahead_prices(GR_BIDDING_ZONE, start=s, end=e)
    px.name = "dam_price_eur_mwh"
    return px


def fetch_load_forecast(start: str, end: str) -> pd.Series:
    s, e = _ts(start, end)
    df = _client().query_load_forecast(GR_BIDDING_ZONE, start=s, end=e)
    series = df.iloc[:, 0] if isinstance(df, pd.DataFrame) else df
    series.name = "load_forecast_mw"
    return series


def fetch_actual_load(start: str, end: str) -> pd.Series:
    s, e = _ts(start, end)
    df = _client().query_load(GR_BIDDING_ZONE, start=s, end=e)
    series = df.iloc[:, 0] if isinstance(df, pd.DataFrame) else df
    series.name = "load_actual_mw"
    return series


def fetch_wind_solar_forecast(start: str, end: str) -> pd.DataFrame:
    s, e = _ts(start, end)
    df = _client().query_wind_and_solar_forecast(GR_BIDDING_ZONE, start=s, end=e)
    df.columns = [f"forecast_{c.lower().replace(' ', '_')}_mw" for c in df.columns]
    return df


def fetch_generation_actual(start: str, end: str) -> pd.DataFrame:
    s, e = _ts(start, end)
    df = _client().query_generation(GR_BIDDING_ZONE, start=s, end=e, psr_type=None)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(c).strip() for c in df.columns]
    df.columns = [f"gen_{c.lower().replace(' ', '_')}_mw" for c in df.columns]
    return df


def fetch_all(start: str, end: str) -> dict[str, pd.DataFrame | pd.Series]:
    out = {}
    out["dam"] = fetch_dam_prices(start, end)
    out["load_forecast"] = fetch_load_forecast(start, end)
    try:
        out["load_actual"] = fetch_actual_load(start, end)
    except Exception as exc:
        print(f"[entsoe] actual load skipped: {exc}")
    out["wind_solar_forecast"] = fetch_wind_solar_forecast(start, end)
    try:
        out["generation_actual"] = fetch_generation_actual(start, end)
    except Exception as exc:
        print(f"[entsoe] generation actual skipped: {exc}")
    return out


def save_all(start: str, end: str) -> None:
    bundle = fetch_all(start, end)
    for name, obj in bundle.items():
        path = RAW_DIR / f"entsoe_{name}_{start}_{end}.parquet"
        if isinstance(obj, pd.Series):
            obj.to_frame().to_parquet(path)
        else:
            obj.to_parquet(path)
        print(f"  saved {path.name}  rows={len(obj)}")
