from __future__ import annotations

import numpy as np
import pandas as pd

from config import GR_TIMEZONE, MTU_SWITCH_DATE, PROCESSED_DIR, RAW_DIR

LAG_PERIODS_15M = [1, 4, 8, 24, 48, 96, 96 * 7]
ROLL_WINDOWS_15M = [4, 16, 96]


def _load_parquet(name_glob: str) -> pd.DataFrame:
    files = sorted(RAW_DIR.glob(name_glob))
    if not files:
        return pd.DataFrame()
    parts = [pd.read_parquet(f) for f in files]
    df = pd.concat(parts).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def _to_15min(df: pd.DataFrame, how: str = "ffill") -> pd.DataFrame:
    if df.empty:
        return df
    df = df.sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize(GR_TIMEZONE)
    else:
        df.index = df.index.tz_convert(GR_TIMEZONE)
    out = df.resample("15min").interpolate(method="time") if how == "interp" else df.resample("15min").ffill()
    return out


def _calendar_features(idx: pd.DatetimeIndex) -> pd.DataFrame:
    df = pd.DataFrame(index=idx)
    df["hour"] = idx.hour
    df["minute_of_day"] = idx.hour * 60 + idx.minute
    df["dow"] = idx.dayofweek
    df["is_weekend"] = (idx.dayofweek >= 5).astype(int)
    df["month"] = idx.month
    df["doy"] = idx.dayofyear
    df["sin_tod"] = np.sin(2 * np.pi * df["minute_of_day"] / 1440)
    df["cos_tod"] = np.cos(2 * np.pi * df["minute_of_day"] / 1440)
    df["sin_doy"] = np.sin(2 * np.pi * df["doy"] / 365)
    df["cos_doy"] = np.cos(2 * np.pi * df["doy"] / 365)
    return df


def _add_lags(df: pd.DataFrame, col: str, lags: list[int]) -> pd.DataFrame:
    for k in lags:
        df[f"{col}_lag{k}"] = df[col].shift(k)
    return df


def _add_rolls(df: pd.DataFrame, col: str, windows: list[int]) -> pd.DataFrame:
    for w in windows:
        df[f"{col}_rollmean{w}"] = df[col].shift(1).rolling(w).mean()
        df[f"{col}_rollstd{w}"] = df[col].shift(1).rolling(w).std()
    return df


def build_dataset() -> pd.DataFrame:
    dam = _load_parquet("entsoe_dam_*.parquet")
    if dam.empty:
        raise RuntimeError("No DAM price files found in data/raw — run scripts/01_fetch_data.py first")
    dam = _to_15min(dam, how="ffill")
    dam.columns = ["dam_price_eur_mwh"]

    load_fc = _load_parquet("entsoe_load_forecast_*.parquet")
    if not load_fc.empty:
        load_fc = _to_15min(load_fc, how="interp")

    rens = _load_parquet("entsoe_wind_solar_forecast_*.parquet")
    if not rens.empty:
        rens = _to_15min(rens, how="interp")

    weather = _load_parquet("weather_*.parquet")
    if not weather.empty:
        weather = _to_15min(weather, how="interp")

    fuels = _load_parquet("fuels_*.parquet")
    if not fuels.empty:
        fuels = _to_15min(fuels, how="ffill")

    df = dam.copy()
    for piece in (load_fc, rens, weather, fuels):
        if not piece.empty:
            df = df.join(piece, how="left")

    df = df.join(_calendar_features(df.index))

    df = _add_lags(df, "dam_price_eur_mwh", LAG_PERIODS_15M)
    df = _add_rolls(df, "dam_price_eur_mwh", ROLL_WINDOWS_15M)

    if "load_forecast_mw" in df.columns:
        wind_cols = [c for c in df.columns if c.startswith("forecast_") and "wind" in c]
        solar_cols = [c for c in df.columns if c.startswith("forecast_") and "solar" in c]
        df["res_total_forecast_mw"] = df[wind_cols + solar_cols].sum(axis=1)
        df["residual_load_mw"] = df["load_forecast_mw"] - df["res_total_forecast_mw"]

    if {"ttf_eur_mwh", "eua_eur_t"}.issubset(df.columns):
        # CCGT short-run marginal cost proxy: heat-rate ~2.0, emission factor ~0.37 t/MWh thermal -> ~0.18 t/MWh elec.
        df["ccgt_srmc_eur_mwh"] = df["ttf_eur_mwh"] * 2.0 + df["eua_eur_t"] * 0.37

    df["mtu_15m_active"] = (df.index >= pd.Timestamp(MTU_SWITCH_DATE, tz=GR_TIMEZONE)).astype(int)

    df = df.dropna(subset=["dam_price_eur_mwh"])
    return df


def save() -> str:
    df = build_dataset()
    path = PROCESSED_DIR / "features.parquet"
    df.to_parquet(path)
    print(f"  saved {path}  rows={len(df)}  cols={len(df.columns)}")
    return str(path)
