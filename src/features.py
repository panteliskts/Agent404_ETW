from __future__ import annotations

import numpy as np
import pandas as pd

from config import GR_TIMEZONE, MTU_SWITCH_DATE, PROCESSED_DIR, RAW_DIR

TRAIN_START = "2024-01-01"

LAG_PERIODS_15M = [1, 4, 8, 24, 48, 96, 96 * 7]
ROLL_WINDOWS_15M = [4, 16, 96]

PRICE_COL = "dam_price_eur_mwh"

HENEX_FFILL_COLS = (
    PRICE_COL,
    "dam_price_60min_idx_eur_mwh",
)


def _load_parquet(name_glob: str) -> pd.DataFrame:
    files = sorted(RAW_DIR.glob(name_glob))
    if not files:
        return pd.DataFrame()
    parts = [pd.read_parquet(f) for f in files]
    df = pd.concat(parts).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def _ensure_athens(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize(GR_TIMEZONE)
    else:
        df.index = df.index.tz_convert(GR_TIMEZONE)
    return df


def _resample_to_15min(df: pd.DataFrame, ffill_cols: tuple[str, ...] = ()) -> pd.DataFrame:
    """Resample mixed-resolution frame to a clean 15-min grid.

    Uses ffill for stepwise quantities (prices that hold across an hour) and
    time-interpolation for smooth quantities (load, generation, weather).
    """
    if df.empty:
        return df
    df = _ensure_athens(df)
    grid = df.resample("15min").asfreq()
    out_cols = {}
    for c in df.columns:
        if c in ffill_cols:
            out_cols[c] = df[c].reindex(grid.index, method="ffill")
        else:
            out_cols[c] = df[c].reindex(grid.index).interpolate(method="time", limit=4)
    return pd.DataFrame(out_cols, index=grid.index)


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


def _load_henex() -> pd.DataFrame:
    files = sorted(RAW_DIR.glob("henex_results*.parquet"))
    if not files:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(f) for f in files]).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def build_dataset(start: str = TRAIN_START) -> pd.DataFrame:
    print("[features] loading HEnEx ...")
    henex = _load_henex()
    if henex.empty:
        raise RuntimeError("No HEnEx data — run scripts/01_fetch_data.py with --source henex first")

    henex = _ensure_athens(henex)
    henex = henex.loc[henex.index >= pd.Timestamp(start, tz=GR_TIMEZONE)]
    print(f"  henex rows={len(henex)} range={henex.index.min()} -> {henex.index.max()}")

    henex_15m = _resample_to_15min(henex, ffill_cols=HENEX_FFILL_COLS)

    weather = _load_parquet("weather_*.parquet")
    if not weather.empty:
        weather = _resample_to_15min(weather)
        print(f"  weather cols={len(weather.columns)}")

    fuels = _load_parquet("fuels_*.parquet")
    if not fuels.empty:
        fuels = _resample_to_15min(fuels, ffill_cols=tuple(fuels.columns))
        print(f"  fuels cols={len(fuels.columns)}")

    entsoe_load = _load_parquet("entsoe_load_forecast_*.parquet")
    entsoe_rens = _load_parquet("entsoe_wind_solar_forecast_*.parquet")
    if not entsoe_load.empty:
        entsoe_load = _resample_to_15min(entsoe_load)
    if not entsoe_rens.empty:
        entsoe_rens = _resample_to_15min(entsoe_rens)

    df = henex_15m.copy()
    for piece in (weather, fuels, entsoe_load, entsoe_rens):
        if not piece.empty:
            df = df.join(piece, how="left")

    df = df.join(_calendar_features(df.index))

    if {"load_hv_mw", "load_mv_mw", "load_lv_mw"}.issubset(df.columns):
        df["load_total_mw"] = df[["load_hv_mw", "load_mv_mw", "load_lv_mw"]].sum(axis=1, min_count=1)
    if {"gen_renewables_mw", "production_total_mw"}.issubset(df.columns):
        df["res_share"] = df["gen_renewables_mw"] / df["production_total_mw"].replace(0, np.nan)
    if {"production_total_mw", "demand_total_mw"}.issubset(df.columns):
        df["net_export_mw"] = df["production_total_mw"] - df["demand_total_mw"]

    if {"ttf_eur_mwh", "eua_eur_t"}.issubset(df.columns):
        df["ccgt_srmc_eur_mwh"] = df["ttf_eur_mwh"] * 2.0 + df["eua_eur_t"] * 0.37

    df = _add_lags(df, PRICE_COL, LAG_PERIODS_15M)
    df = _add_rolls(df, PRICE_COL, ROLL_WINDOWS_15M)

    df["mtu_15m_active"] = (df.index >= pd.Timestamp(MTU_SWITCH_DATE, tz=GR_TIMEZONE)).astype(int)

    df = df.dropna(subset=[PRICE_COL])

    nan_ratio = df.isna().mean()
    drop_cols = nan_ratio[nan_ratio > 0.70].index.tolist()
    if drop_cols:
        print(f"  dropping {len(drop_cols)} cols with >70% NaN: {drop_cols}")
        df = df.drop(columns=drop_cols)

    return df


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds all derived features to a pre-loaded, merged DataFrame.
    df must have dam_price_eur_mwh on a tz-aware DatetimeIndex.
    Lags require at least 7 days of history; rows with NaN lags are kept
    so callers can decide how to handle them.
    """
    df = df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize(GR_TIMEZONE)

    df = df.join(_calendar_features(df.index), how="left")
    df = _add_lags(df, "dam_price_eur_mwh", LAG_PERIODS_15M)
    df = _add_rolls(df, "dam_price_eur_mwh", ROLL_WINDOWS_15M)

    # Residual load (if load + RES columns present)
    if "load_forecast_mw" in df.columns and "res_total_forecast_mw" in df.columns:
        df["residual_load_mw"] = df["load_forecast_mw"] - df["res_total_forecast_mw"]
        # Greek-specific: midday (11-15) and evening (18-22) rolling means
        df["midday_res_load"] = (
            df["residual_load_mw"].where((df["hour"] >= 11) & (df["hour"] <= 15))
            .rolling(96, min_periods=1).mean()
        )
        df["evening_res_load"] = (
            df["residual_load_mw"].where((df["hour"] >= 18) & (df["hour"] <= 22))
            .rolling(96, min_periods=1).mean()
        )
        df["evening_ramp"] = df["evening_res_load"] - df["midday_res_load"]

    # CCGT short-run marginal cost proxy
    if {"ttf_eur_mwh", "eua_eur_t"}.issubset(df.columns):
        df["ccgt_srmc_eur_mwh"] = df["ttf_eur_mwh"] * 2.0 + df["eua_eur_t"] * 0.37

    df["mtu_15m_active"] = (df.index >= pd.Timestamp(MTU_SWITCH_DATE, tz=GR_TIMEZONE)).astype(int)

    return df.dropna(subset=["dam_price_eur_mwh"])


def save() -> str:
    df = build_dataset()
    path = PROCESSED_DIR / "features.parquet"
    df.to_parquet(path)
    print(f"  saved {path}  rows={len(df)}  cols={len(df.columns)}")
    return str(path)
