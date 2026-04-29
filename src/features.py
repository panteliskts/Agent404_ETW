from __future__ import annotations

import numpy as np
import pandas as pd

from config import GR_TIMEZONE, MTU_SWITCH_DATE, PROCESSED_DIR, RAW_DIR

TRAIN_START = "2024-01-01"

# Full lag set — used for in-sample / 15-min-ahead style backtests.
LAG_PERIODS_15M = [1, 4, 8, 24, 48, 96, 96 * 7]
ROLL_WINDOWS_15M = [4, 16, 96]

# Realistic next-day lag set — only data that is genuinely available at DAM
# gate-closure for day D (day D-1 ~12:00). Lag of 96 = exactly 1 day, lag 672
# = 1 week. Rolling stats are shifted by 96 so they look only at days <= D-1.
LAG_PERIODS_REALISTIC = [96, 96 * 7]
ROLL_WINDOWS_REALISTIC = [96, 96 * 7]
ROLL_SHIFT_REALISTIC = 96

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


def _add_rolls(df: pd.DataFrame, col: str, windows: list[int], shift: int = 1) -> pd.DataFrame:
    for w in windows:
        df[f"{col}_rollmean{w}"] = df[col].shift(shift).rolling(w).mean()
        df[f"{col}_rollstd{w}"] = df[col].shift(shift).rolling(w).std()
    return df


def _load_henex() -> pd.DataFrame:
    files = sorted(RAW_DIR.glob("henex_results*.parquet"))
    if not files:
        return pd.DataFrame()
    df = pd.concat([pd.read_parquet(f) for f in files]).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def build_dataset(start: str = TRAIN_START, realistic_lags_only: bool = False) -> pd.DataFrame:
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

    if {"load_forecast_mw", "forecast_solar_mw", "forecast_wind_onshore_mw"}.issubset(df.columns):
        df["res_total_forecast_mw"] = (
            df["forecast_solar_mw"].fillna(0) + df["forecast_wind_onshore_mw"].fillna(0)
        )
        df["residual_load_forecast_mw"] = df["load_forecast_mw"] - df["res_total_forecast_mw"]

    df = _add_extra_composites(df)

    if realistic_lags_only:
        df = _add_lags(df, PRICE_COL, LAG_PERIODS_REALISTIC)
        df = _add_rolls(df, PRICE_COL, ROLL_WINDOWS_REALISTIC, shift=ROLL_SHIFT_REALISTIC)
    else:
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


# Audit dropped wind/radiation/temperature averages and thermal_gap (near-zero
# gain). gas_share_production survived (~0.16% gain) and is kept.
_EXTRA_COMPOSITES = ("gas_share_production",)


def _add_extra_composites(df: pd.DataFrame) -> pd.DataFrame:
    if {"gen_gas_mw", "production_total_mw"}.issubset(df.columns):
        df["gas_share_production"] = df["gen_gas_mw"] / df["production_total_mw"].replace(0, np.nan)
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


# Columns whose values are NOT known at next-day DAM gate close (D-1 ~12:00).
# They are realized HEnEx outputs published after the day; for honest next-day
# forecasting we either drop them or use only their 1-day lag.
_LEAKY_REALIZED_COLS = (
    "gen_lignite_mw", "gen_gas_mw", "gen_hydro_mw",
    "gen_renewables_mw", "gen_crete_renewables_mw", "gen_crete_conventional_mw",
    "production_total_mw",
    "load_hv_mw", "load_mv_mw", "load_lv_mw", "system_losses_mw",
    "load_crete_mw", "demand_total_mw", "load_total_mw", "load_bess_mw",
    "renewables_buy_mw",
    "volume_mainland_mwh",
    "res_share", "net_export_mw", "gas_share_production",
)


def build_clean_dataset(start: str = TRAIN_START, lag_realized: int = 96) -> pd.DataFrame:
    """Strict gate-close-feasible feature set, target ~35 columns."""
    df = build_dataset(start=start, realistic_lags_only=True)

    # Replace leaky cols with their 24h lag (yesterday-at-this-hour).
    for col in _LEAKY_REALIZED_COLS:
        if col in df.columns:
            df[f"{col}_lag{lag_realized}"] = df[col].shift(lag_realized)
            df = df.drop(columns=[col])

    # Drop redundant calendar — sin/cos pairs encode the same info.
    for col in ("minute_of_day", "doy", "hour", "month"):
        if col in df.columns:
            df = df.drop(columns=[col])

    # Aggregate weather across cities; drop wind direction & diffuse radiation.
    cities = ["athens", "thessaloniki", "patras", "crete"]
    weather_vars = ("temperature_2m", "wind_speed_100m", "cloud_cover", "shortwave_radiation")
    for var in weather_vars:
        cols = [f"{c}_{var}" for c in cities if f"{c}_{var}" in df.columns]
        if cols:
            df[f"gr_avg_{var}"] = df[cols].mean(axis=1)
            df[f"gr_std_{var}"] = df[cols].std(axis=1)
            df = df.drop(columns=cols)

    drop_weather = []
    for c in cities:
        for v in ("wind_direction_100m", "direct_radiation", "diffuse_radiation"):
            col = f"{c}_{v}"
            if col in df.columns:
                drop_weather.append(col)
    if drop_weather:
        df = df.drop(columns=drop_weather)

    df = df.dropna(subset=[PRICE_COL])
    return df


def save() -> str:
    df = build_dataset()
    path = PROCESSED_DIR / "features.parquet"
    df.to_parquet(path)
    print(f"  saved {path}  rows={len(df)}  cols={len(df.columns)}")

    df_real = build_dataset(realistic_lags_only=True)
    real_path = PROCESSED_DIR / "features_realistic.parquet"
    df_real.to_parquet(real_path)
    print(f"  saved {real_path}  rows={len(df_real)}  cols={len(df_real.columns)}")
    return str(path)
