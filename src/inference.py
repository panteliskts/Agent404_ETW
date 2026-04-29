"""End-to-end inference: features -> price quantiles -> battery schedule.

Public API used by the app:
    forecast_day(target_date) -> DataFrame[q10,q50,q90] indexed at 15-min
    decide_schedule(target_date) -> DataFrame[action,power_mw,soc_mwh,...]
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from config import DEFAULT_BATTERY, GR_TIMEZONE, PROCESSED_DIR, BatterySpec
from src.forecaster import load_quantile_models, predict_interval
from src.scheduler import compute_low_confidence_mask, optimize


REALISTIC_FEATURES_PATH = PROCESSED_DIR / "features_realistic.parquet"


def _load_features(path: Path = REALISTIC_FEATURES_PATH) -> pd.DataFrame:
    if not path.exists():
        raise RuntimeError(
            f"missing {path}. Run scripts/02_build_features.py to regenerate."
        )
    return pd.read_parquet(path)


def _slice_day(df: pd.DataFrame, target_date) -> pd.DataFrame:
    if isinstance(target_date, str):
        target_date = pd.Timestamp(target_date).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()
    mask = df.index.tz_convert(GR_TIMEZONE).date == target_date
    out = df.loc[mask]
    if out.empty:
        raise RuntimeError(f"no feature rows for {target_date}")
    return out


def forecast_day(target_date) -> pd.DataFrame:
    """Returns a 96-row DataFrame with q10, q50, q90 forecasts in EUR/MWh."""
    models = load_quantile_models()
    if models is None:
        raise RuntimeError("Quantile models missing — run scripts/06_train_final.py first.")
    feats = _slice_day(_load_features(), target_date)
    quantiles = predict_interval(models, feats)
    quantiles.columns = [f"price_{c}_eur_mwh" for c in quantiles.columns]
    return quantiles


def decide_schedule(
    target_date,
    battery: BatterySpec = DEFAULT_BATTERY,
    use_idle_mask: bool = True,
) -> pd.DataFrame:
    """Returns one row per 15-min MTU with the battery decision."""
    quantiles = forecast_day(target_date)
    q10 = quantiles["price_q10_eur_mwh"]
    q50 = quantiles["price_q50_eur_mwh"]
    q90 = quantiles["price_q90_eur_mwh"]

    idle_mask = compute_low_confidence_mask(q10, q90, battery=battery) if use_idle_mask else None

    schedule = optimize(q50, battery=battery, idle_mask=idle_mask)
    df = schedule.to_frame()
    df["price_q10"] = q10
    df["price_q50"] = q50
    df["price_q90"] = q90
    df["spread"] = q90 - q10
    df["confidence"] = np.where(idle_mask.values, "low", "high") if idle_mask is not None else "high"

    eps = 1e-6
    action = np.where(df["charge_mw"] > eps, "charge",
              np.where(df["discharge_mw"] > eps, "discharge", "idle"))
    df["action"] = action
    df["power_mw"] = df["discharge_mw"] - df["charge_mw"]

    df = df[
        [
            "action",
            "power_mw",
            "charge_mw",
            "discharge_mw",
            "soc_mwh",
            "price_q10",
            "price_q50",
            "price_q90",
            "spread",
            "confidence",
        ]
    ]
    df.attrs["expected_revenue_eur"] = float(schedule.objective_eur)
    df.attrs["battery"] = asdict(battery)
    return df
