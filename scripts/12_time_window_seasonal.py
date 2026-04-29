"""Baseline: time-of-day bucketed model with seasonal weighting.

- Splits day into 4 buckets (6-hour blocks).
- For each test day, trains a model per bucket using only that bucket's rows.
- Applies Gaussian weights based on day-of-year distance (sigma days).

This keeps all features but restricts training to the same time-of-day block and
upweights seasonal neighbors.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import PROCESSED_DIR
from src.forecaster import TARGET, _drop_target_leakage

TEST_DAYS = 7
SIGMA_DAYS = 30.0
BUCKET_HOURS = 6


def day_of_year_distance(a: int, b: int) -> int:
    """Cyclic day-of-year distance (wraps at 365)."""
    diff = abs(a - b)
    return min(diff, 365 - diff)


def gaussian_weight(d: int, sigma: float) -> float:
    return math.exp(-0.5 * (d / sigma) ** 2)


def bucket_for_hour(hour: int) -> int:
    return hour // BUCKET_HOURS


def train_bucket_model(train_df: pd.DataFrame, valid_df: pd.DataFrame, feat_cols: list[str]) -> lgb.Booster:
    dtrain = lgb.Dataset(train_df[feat_cols], train_df[TARGET], weight=train_df["_w"])
    dvalid = lgb.Dataset(valid_df[feat_cols], valid_df[TARGET], reference=dtrain, weight=valid_df["_w"])
    params = {
        "objective": "regression",
        "metric": "mae",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "min_data_in_leaf": 50,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "verbose": -1,
    }
    return lgb.train(
        params,
        dtrain,
        num_boost_round=1200,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(80, verbose=False)],
    )


def main() -> None:
    path = PROCESSED_DIR / "features_realistic.parquet"
    if not path.exists():
        raise SystemExit(f"missing {path}. Run scripts/02_build_features.py first.")

    df = pd.read_parquet(path)
    df = df.dropna(subset=[TARGET]).sort_index()
    feat_cols = _drop_target_leakage(df)

    end = df.index.max()
    test_start = end - pd.Timedelta(days=TEST_DAYS)
    train_pool = df.loc[df.index < test_start].copy()
    test_df = df.loc[df.index >= test_start].copy()

    if test_df.empty:
        raise SystemExit("test window empty")

    print(f"Train pool: {train_pool.index.min()} -> {train_pool.index.max()} ({len(train_pool)} rows)")
    print(f"Test window: {test_df.index.min()} -> {test_df.index.max()} ({len(test_df)} rows)")
    print(f"Buckets: {24 // BUCKET_HOURS} (each {BUCKET_HOURS}h), seasonal sigma={SIGMA_DAYS}d")

    preds = []
    for day in pd.unique(test_df.index.normalize()):
        day_df = test_df.loc[test_df.index.normalize() == day]
        doy = int(pd.Timestamp(day).dayofyear)

        # Build seasonal weights for the full train pool once per day.
        train_pool = train_pool.copy()
        train_pool["_doy"] = train_pool.index.dayofyear
        train_pool["_w"] = train_pool["_doy"].apply(lambda x: gaussian_weight(day_of_year_distance(int(x), doy), SIGMA_DAYS))

        for bucket in range(24 // BUCKET_HOURS):
            day_bucket = day_df[(day_df.index.hour // BUCKET_HOURS) == bucket]
            if day_bucket.empty:
                continue

            train_bucket = train_pool[(train_pool.index.hour // BUCKET_HOURS) == bucket]
            if len(train_bucket) < 1000:
                continue

            # Small validation slice from end of train bucket.
            valid_cut = train_bucket.index.max() - pd.Timedelta(days=14)
            valid_bucket = train_bucket[train_bucket.index >= valid_cut]
            train_bucket = train_bucket[train_bucket.index < valid_cut]
            if len(valid_bucket) < 200 or len(train_bucket) < 1000:
                continue

            model = train_bucket_model(train_bucket, valid_bucket, feat_cols)
            yhat = model.predict(day_bucket[feat_cols], num_iteration=model.best_iteration)
            preds.append(pd.Series(yhat, index=day_bucket.index))

    if not preds:
        raise SystemExit("no predictions produced; check bucket sizes")

    pred = pd.concat(preds).sort_index()
    aligned = test_df.loc[pred.index]
    mae = float(np.mean(np.abs(aligned[TARGET] - pred)))
    print(f"\nMAE (time-of-day buckets + seasonal weights): {mae:.2f} €/MWh")


if __name__ == "__main__":
    main()
