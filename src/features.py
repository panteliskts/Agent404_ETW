from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import holidays as _holidays
    _HOLIDAYS_AVAILABLE = True
except ImportError:
    _HOLIDAYS_AVAILABLE = False

from config import GR_TIMEZONE, MTU_SWITCH_DATE, PROCESSED_DIR, RAW_DIR

# Geographic centroid used for solar-geometry features. Athens latitude is
# representative for both load (south coast) and the bulk of solar capacity.
_GR_LAT_DEG = 38.0
_GR_LON_DEG = 23.7

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


def _solar_elevation(idx: pd.DatetimeIndex, lat_deg: float, lon_deg: float) -> np.ndarray:
    """Solar elevation in degrees (>0 day, <0 night). Closed-form, sufficient
    for ranking: midday peak depth, dawn/dusk sharpness, day length."""
    utc = idx.tz_convert("UTC")
    doy = np.asarray(utc.dayofyear, dtype=float)
    frac_h = utc.hour + utc.minute / 60.0 + utc.second / 3600.0
    decl = np.radians(23.45) * np.sin(2 * np.pi * (284 + doy) / 365.0)
    # Solar time approximation (no equation-of-time correction; ranking-only).
    solar_time = frac_h + lon_deg / 15.0
    hour_angle = np.radians(15.0 * (solar_time - 12.0))
    phi = np.radians(lat_deg)
    sin_alt = np.sin(phi) * np.sin(decl) + np.cos(phi) * np.cos(decl) * np.cos(hour_angle)
    return np.degrees(np.arcsin(np.clip(sin_alt, -1.0, 1.0)))


def _greek_holiday_features(idx: pd.DatetimeIndex) -> pd.DataFrame:
    """is_holiday, is_holiday_eve, is_holiday_after, days_to_holiday (clipped)."""
    df = pd.DataFrame(index=idx)
    if not _HOLIDAYS_AVAILABLE:
        df["is_holiday"] = 0
        df["is_holiday_eve"] = 0
        df["is_holiday_after"] = 0
        df["days_to_holiday"] = 7
        return df

    years = sorted({int(y) for y in idx.year.unique()})
    gr = _holidays.country_holidays("GR", years=years + [years[0] - 1, years[-1] + 1])
    holiday_dates = pd.to_datetime(sorted(gr.keys()))
    holiday_set = {pd.Timestamp(d).normalize() for d in holiday_dates}
    dates = idx.tz_convert(GR_TIMEZONE).normalize().tz_localize(None)

    df["is_holiday"] = dates.isin(holiday_set).astype(int)
    df["is_holiday_eve"] = (dates + pd.Timedelta(days=1)).isin(holiday_set).astype(int)
    df["is_holiday_after"] = (dates - pd.Timedelta(days=1)).isin(holiday_set).astype(int)

    # Days to nearest upcoming holiday in [0, 30]; 30 acts as "far away".
    sorted_hd = np.array(sorted(holiday_set), dtype="datetime64[ns]")
    if len(sorted_hd) > 0:
        d_arr = np.asarray(dates.values, dtype="datetime64[ns]")
        idx_search = np.searchsorted(sorted_hd, d_arr)
        idx_search = np.clip(idx_search, 0, len(sorted_hd) - 1)
        next_h = sorted_hd[idx_search]
        delta_days = (next_h - d_arr).astype("timedelta64[D]").astype(int)
        df["days_to_holiday"] = np.clip(delta_days, 0, 30)
    else:
        df["days_to_holiday"] = 30
    return df


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

    # Solar geometry — deterministic, drives the daily generation shape and
    # dawn/dusk price ramps. Rank-stable across forecast noise.
    elev = _solar_elevation(idx, _GR_LAT_DEG, _GR_LON_DEG)
    df["solar_elevation_deg"] = elev
    df["solar_is_day"] = (elev > 0).astype(int)
    df["solar_clip_pos"] = np.clip(elev, 0, None)  # 0 at night, monotone in midday

    # Day length (hours of sun per calendar day) — proxies for seasonality
    # in solar-driven price collapse.
    declin = 23.45 * np.sin(2 * np.pi * (284 + df["doy"].values) / 365.0)
    cos_omega = -np.tan(np.radians(_GR_LAT_DEG)) * np.tan(np.radians(declin))
    cos_omega = np.clip(cos_omega, -1.0, 1.0)
    df["day_length_h"] = 2 * np.degrees(np.arccos(cos_omega)) / 15.0

    df = df.join(_greek_holiday_features(idx))
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

    # SDAC-coupled neighbor zone DA prices (Italy-South, Bulgaria, Romania).
    # Stored as ffill-style stepwise quantities. They are NOT directly usable
    # at gate close for the same delivery day (all SDAC zones clear together);
    # build_clean_dataset replaces them with their 24h / 7d lags.
    entsoe_neigh = _load_parquet("entsoe_neighbor_prices_*.parquet")
    if not entsoe_neigh.empty:
        entsoe_neigh = _resample_to_15min(entsoe_neigh, ffill_cols=tuple(entsoe_neigh.columns))

    df = henex_15m.copy()
    for piece in (weather, fuels, entsoe_load, entsoe_rens, entsoe_neigh):
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
_EXTRA_COMPOSITES = (
    "gas_share_production",
    "res_penetration",
    "solar_load_ratio",
    "wind_load_ratio",
    "collapse_risk",
    "solar_surplus_midday",
    "national_solar_radiation",
)


def _add_extra_composites(df: pd.DataFrame) -> pd.DataFrame:
    if {"gen_gas_mw", "production_total_mw"}.issubset(df.columns):
        df["gas_share_production"] = df["gen_gas_mw"] / df["production_total_mw"].replace(0, np.nan)

    # ── Renewable oversupply / price collapse risk features ──────────────────
    load = df.get("load_forecast_mw")
    solar = df.get("forecast_solar_mw")
    wind  = df.get("forecast_wind_onshore_mw")

    if load is not None and solar is not None and wind is not None:
        safe_load = load.replace(0, np.nan)
        res_total = solar.fillna(0) + wind.fillna(0)

        # RES as fraction of load — primary collapse signal (>1 means oversupply)
        df["res_penetration"] = res_total / safe_load

        # Solar and wind separately
        df["solar_load_ratio"] = solar.fillna(0) / safe_load
        df["wind_load_ratio"]  = wind.fillna(0)  / safe_load

        # Interaction: high RES penetration × recent price level
        # Captures "prices were high + renewables ramping → collapse incoming"
        if PRICE_COL in df.columns:
            price_lag = df[PRICE_COL].shift(4)  # 1-hour lag
            df["collapse_risk"] = df["res_penetration"] * price_lag.clip(lower=0)

        # Solar surplus during midday (10-14h) — worst collapse window
        if "hour" in df.columns:
            midday = df["hour"].between(10, 14)
            df["solar_surplus_midday"] = df["solar_load_ratio"].where(midday, 0)

    # National solar radiation — average across all 4 weather stations
    rad_cols = [c for c in df.columns if c.endswith("_shortwave_radiation")]
    if len(rad_cols) >= 2:
        df["national_solar_radiation"] = df[rad_cols].mean(axis=1)

    # ── Hand-engineered SPIKE LIKELIHOOD ─────────────────────────────────────
    # Pattern audit on the worst-capture days isolated this signature:
    #   LOW solar forecast + HIGH cloud + HIGH residual load + EVENING (17-22h)
    # Encoded directly as a domain-knowledge probability so the model doesn't
    # have to learn the interaction from too few examples. The score is
    # standardised within rolling history (so it's regime-stable across years).
    if load is not None and solar is not None and wind is not None:
        cloud_cols = [c for c in df.columns if c.endswith("_cloud_cover")]
        cloud_avg = df[cloud_cols].mean(axis=1) if cloud_cols else pd.Series(0.5, index=df.index)

        thermal = (load.fillna(0) - solar.fillna(0) - wind.fillna(0)).clip(lower=0)
        # Z-scored thermal stress: how anomalously high is residual load now
        # vs the trailing 30-day distribution at the same hour-of-day?
        if "hour" in df.columns:
            grp = df.groupby(df["hour"])
            thermal_mu = grp[load.name if hasattr(load, "name") else "load_forecast_mw"].transform(
                lambda s: s.rolling(96 * 30, min_periods=96).mean().shift(96)
            )  # mean of LOAD at this hour, used as a denominator scale
            thermal_z = (thermal - thermal_mu) / thermal_mu.replace(0, np.nan)
        else:
            thermal_z = thermal / safe_load
        thermal_z = thermal_z.fillna(0).clip(-2, 5)

        # Components in [0,1]:
        #   cloud:   0 clear → 1 fully overcast
        #   solar_def: 0 high solar (good) → 1 zero solar (bad). Use solar_load_ratio inverse.
        cloud_term = (cloud_avg / 100.0).clip(0, 1) if cloud_avg.max() > 1.0 else cloud_avg.clip(0, 1)
        solar_def_term = (1.0 - df.get("solar_load_ratio", pd.Series(0, index=df.index))).clip(0, 1)
        thermal_term = (thermal_z.clip(0, 2) / 2.0)
        if "hour" in df.columns:
            evening_term = df["hour"].between(17, 22).astype(float)
            morning_ramp_term = df["hour"].between(6, 9).astype(float) * 0.5
        else:
            evening_term = pd.Series(0, index=df.index)
            morning_ramp_term = pd.Series(0, index=df.index)
        weekday_term = (1.0 - df.get("is_weekend", pd.Series(0, index=df.index)).astype(float))

        # Weighted sum then squashed. Coefficients reflect the audit:
        # cloud 0.20, solar deficit 0.30, thermal stress 0.25, evening 0.15, weekday 0.10
        raw = (
            0.20 * cloud_term
            + 0.30 * solar_def_term
            + 0.25 * thermal_term
            + 0.15 * (evening_term + morning_ramp_term).clip(0, 1)
            + 0.10 * weekday_term
        )
        df["spike_likelihood"] = raw.clip(0, 1)
        # Daily peak of spike likelihood — broadcast as feature across the day.
        days_idx = df.index.normalize() if df.index.tz is None else df.index.tz_convert(df.index.tz).normalize()
        df["spike_likelihood_daymax"] = df["spike_likelihood"].groupby(days_idx).transform("max")

    return df


_WEATHER_VARS = ("temperature_2m", "wind_speed_100m", "cloud_cover", "shortwave_radiation")
_CITIES = ("athens", "thessaloniki", "patras", "crete")

# Columns that the production models were trained with but come from ENTSO-E
# generation/load actuals — not present in the cache. We add their 96-period
# lag versions as NaN so LightGBM can predict (it handles NaN natively).
_LEAKY_LAG_COLS = (
    "gen_lignite_mw", "gen_gas_mw", "gen_hydro_mw",
    "gen_renewables_mw", "gen_crete_renewables_mw", "gen_crete_conventional_mw",
    "production_total_mw",
    "load_hv_mw", "load_mv_mw", "load_lv_mw", "system_losses_mw",
    "load_crete_mw", "demand_total_mw", "load_total_mw",
    "volume_mainland_mwh",
    "res_share", "net_export_mw", "gas_share_production",
)

_NEIGHBOR_COLS = ("da_price_it_sud_eur_mwh", "da_price_bg_eur_mwh", "da_price_ro_eur_mwh")


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds all derived features to a pre-loaded, merged DataFrame.
    df must have dam_price_eur_mwh on a tz-aware DatetimeIndex.
    Produces the full column set expected by the production models; missing
    source columns are left as NaN (LightGBM handles them natively).
    """
    df = df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize(GR_TIMEZONE)

    df = df.join(_calendar_features(df.index), how="left")

    # Price lags and rolling stats matching the realistic (clean-dataset) set
    df = _add_lags(df, "dam_price_eur_mwh", LAG_PERIODS_REALISTIC)
    df = _add_rolls(df, "dam_price_eur_mwh", ROLL_WINDOWS_REALISTIC, shift=ROLL_SHIFT_REALISTIC)

    # Aggregate per-city weather into national averages/stds expected by models
    for var in _WEATHER_VARS:
        cols = [f"{c}_{var}" for c in _CITIES if f"{c}_{var}" in df.columns]
        if cols:
            df[f"gr_avg_{var}"] = df[cols].mean(axis=1)
            df[f"gr_std_{var}"] = df[cols].std(axis=1)
            df = df.drop(columns=cols)

    # Drop per-city columns not needed by models
    drop_weather = []
    for c in _CITIES:
        for v in ("wind_direction_100m", "direct_radiation", "diffuse_radiation"):
            col = f"{c}_{v}"
            if col in df.columns:
                drop_weather.append(col)
    if drop_weather:
        df = df.drop(columns=drop_weather)

    # Composite features from forecast columns
    load = df.get("load_forecast_mw")
    solar = df.get("forecast_solar_mw")
    wind = df.get("forecast_wind_onshore_mw")

    if load is not None and solar is not None and wind is not None:
        safe_load = load.replace(0, np.nan)
        res_total = solar.fillna(0) + wind.fillna(0)
        df["res_penetration"] = res_total / safe_load
        df["solar_load_ratio"] = solar.fillna(0) / safe_load
        df["wind_load_ratio"] = wind.fillna(0) / safe_load
        if PRICE_COL in df.columns:
            df["collapse_risk"] = df["res_penetration"] * df[PRICE_COL].shift(4).clip(lower=0)
        if "hour" in df.columns:
            midday = df["hour"].between(10, 14)
            df["solar_surplus_midday"] = df["solar_load_ratio"].where(midday, 0)

    if load is not None and solar is not None and wind is not None:
        cloud_cols = [c for c in df.columns if c.endswith("_cloud_cover")]
        cloud_avg = df[cloud_cols].mean(axis=1) if cloud_cols else pd.Series(0.5, index=df.index)

        thermal = (load.fillna(0) - solar.fillna(0) - wind.fillna(0)).clip(lower=0)
        safe_load2 = load.replace(0, np.nan)
        if "hour" in df.columns:
            grp = df.groupby(df["hour"])
            thermal_mu = grp["load_forecast_mw"].transform(
                lambda s: s.rolling(96 * 30, min_periods=96).mean().shift(96)
            )
            thermal_z = (thermal - thermal_mu) / thermal_mu.replace(0, np.nan)
        else:
            thermal_z = thermal / safe_load2
        thermal_z = thermal_z.fillna(0).clip(-2, 5)

        cloud_term = (cloud_avg / 100.0).clip(0, 1) if cloud_avg.max() > 1.0 else cloud_avg.clip(0, 1)
        solar_def_term = (1.0 - df.get("solar_load_ratio", pd.Series(0, index=df.index))).clip(0, 1)
        thermal_term = thermal_z.clip(0, 2) / 2.0
        if "hour" in df.columns:
            evening_term = df["hour"].between(17, 22).astype(float)
            morning_ramp_term = df["hour"].between(6, 9).astype(float) * 0.5
        else:
            evening_term = pd.Series(0, index=df.index)
            morning_ramp_term = pd.Series(0, index=df.index)
        weekday_term = (1.0 - df.get("is_weekend", pd.Series(0, index=df.index)).astype(float))

        raw = (
            0.20 * cloud_term
            + 0.30 * solar_def_term
            + 0.25 * thermal_term
            + 0.15 * (evening_term + morning_ramp_term).clip(0, 1)
            + 0.10 * weekday_term
        )
        df["spike_likelihood"] = raw.clip(0, 1)
        days_idx = (
            df.index.normalize() if df.index.tz is None
            else df.index.tz_convert(df.index.tz).normalize()
        )
        df["spike_likelihood_daymax"] = df["spike_likelihood"].groupby(days_idx).transform("max")

    # National solar radiation
    rad_cols = [c for c in df.columns if c.endswith("_shortwave_radiation")]
    if len(rad_cols) >= 2:
        df["national_solar_radiation"] = df[rad_cols].mean(axis=1)

    # Residual load forecast
    if "load_forecast_mw" in df.columns and "res_total_forecast_mw" in df.columns:
        df["residual_load_forecast_mw"] = df["load_forecast_mw"] - df["res_total_forecast_mw"]

    # CCGT short-run marginal cost proxy
    if {"ttf_eur_mwh", "eua_eur_t"}.issubset(df.columns):
        df["ccgt_srmc_eur_mwh"] = df["ttf_eur_mwh"] * 2.0 + df["eua_eur_t"] * 0.37

    # Neighbor zone price lags (present in raw when ENTSO-E is live; NaN from cache)
    for col in _NEIGHBOR_COLS:
        lag96_col = f"{col}_lag96"
        lag672_col = f"{col}_lag672"
        if col in df.columns:
            df[lag96_col] = df[col].shift(ROLL_SHIFT_REALISTIC)
            df[lag672_col] = df[col].shift(ROLL_SHIFT_REALISTIC * 7)
            if "dam_price_eur_mwh_lag96" in df.columns:
                df[f"{col.replace('_eur_mwh','')}_minus_gr_lag96"] = (
                    df[lag96_col] - df["dam_price_eur_mwh_lag96"]
                )
            df = df.drop(columns=[col])
        else:
            # Add as NaN so LightGBM can still predict
            for lag_col in (lag96_col, lag672_col):
                if lag_col not in df.columns:
                    df[lag_col] = np.nan
            minus_col = f"{col.replace('_eur_mwh','')}_minus_gr_lag96"
            if minus_col not in df.columns:
                df[minus_col] = np.nan

    # ENTSO-E generation/load lagged columns — NaN when not in source data
    for col in _LEAKY_LAG_COLS:
        lag_col = f"{col}_lag96"
        if lag_col not in df.columns:
            if col in df.columns:
                df[lag_col] = df[col].shift(ROLL_SHIFT_REALISTIC)
                df = df.drop(columns=[col])
            else:
                df[lag_col] = np.nan

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
    # SDAC neighbor zones — published at the same time as Greek DAM, so the
    # same-day price is unavailable at gate close. Their lag96 / lag672 carry
    # the cross-zone coupling signal.
    "da_price_it_sud_eur_mwh", "da_price_bg_eur_mwh", "da_price_ro_eur_mwh",
)


_NEIGHBOR_PRICE_COLS = ("da_price_it_sud_eur_mwh", "da_price_bg_eur_mwh", "da_price_ro_eur_mwh")


def build_clean_dataset(start: str = TRAIN_START, lag_realized: int = 96) -> pd.DataFrame:
    """Strict gate-close-feasible feature set, target ~35 columns."""
    df = build_dataset(start=start, realistic_lags_only=True)

    # Replace leaky cols with their 24h lag (yesterday-at-this-hour).
    for col in _LEAKY_REALIZED_COLS:
        if col in df.columns:
            df[f"{col}_lag{lag_realized}"] = df[col].shift(lag_realized)
            df = df.drop(columns=[col])

    # Neighbor DA prices: also expose the 7-day lag (same DOW last week) — the
    # market "memory" signal. Spreads between Greece and neighbors carry
    # coupling info that lag96 alone smooths over.
    for col in _NEIGHBOR_PRICE_COLS:
        lag96_col = f"{col}_lag96"
        lag672_col = f"{col}_lag672"
        if lag96_col in df.columns:
            df[lag672_col] = df[lag96_col].shift(96 * 6)  # 96 already shifted, +6d=672
            # Spread vs Greek lag96 — direct cross-zone divergence proxy.
            if "dam_price_eur_mwh_lag96" in df.columns:
                df[f"{col.replace('_eur_mwh','')}_minus_gr_lag96"] = (
                    df[lag96_col] - df["dam_price_eur_mwh_lag96"]
                )

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
    """Persist three feature snapshots:
      - features.parquet:           full lags (lag1..lag96*7), in-sample / debug.
      - features_realistic.parquet: realistic price lags but RAW market-clearing
                                    outputs from HEnEx (leaky for next-day).
                                    Kept for backwards compatibility with the
                                    older inference path.
      - features_clean.parquet:     strict gate-close-feasible — all next-day
                                    clearing outputs replaced by their 24h lag.
                                    THIS is what next-day forecasting must use.
    """
    df = build_dataset()
    path = PROCESSED_DIR / "features.parquet"
    df.to_parquet(path)
    print(f"  saved {path}  rows={len(df)}  cols={len(df.columns)}")

    df_real = build_dataset(realistic_lags_only=True)
    real_path = PROCESSED_DIR / "features_realistic.parquet"
    df_real.to_parquet(real_path)
    print(f"  saved {real_path}  rows={len(df_real)}  cols={len(df_real.columns)}")

    df_clean = build_clean_dataset()
    clean_path = PROCESSED_DIR / "features_clean.parquet"
    df_clean.to_parquet(clean_path)
    print(f"  saved {clean_path}  rows={len(df_clean)}  cols={len(df_clean.columns)}")
    return str(path)
