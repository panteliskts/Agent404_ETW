"""Backtest capture ratio using time-of-day buckets with seasonal + recency weights.

- Uses realistic-lags features.
- Trains per day and per 6-hour bucket (4 buckets).
- Weights training samples by:
  * Seasonal proximity (Gaussian on day-of-year, sigma=30d)
  * Recency (half-life 30d, exponential decay)

Outputs:
  reports/time_bucket_capture_ratio.csv
  reports/time_bucket_capture_ratio.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import PROCESSED_DIR, REPORTS_DIR
from src.evaluate import rolling_backtest, summary
from src.forecaster import TARGET, _drop_target_leakage

TEST_DAYS = 30
SIGMA_DAYS = 30.0
RECENCY_HALFLIFE_DAYS = 30.0
BUCKET_HOURS = 6

PARAMS = {
    "objective": "regression",
    "metric": "mae",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 30,
    "feature_fraction": 0.85,
    "bagging_fraction": 0.85,
    "bagging_freq": 5,
    "verbose": -1,
}


def day_of_year_distance(a: int, b: int) -> int:
    diff = abs(a - b)
    return min(diff, 365 - diff)


def gaussian_weight(d: int, sigma: float) -> float:
    return math.exp(-0.5 * (d / sigma) ** 2)


def recency_weight(days_ago: float, half_life_days: float) -> float:
    # Exponential decay with half-life.
    return 0.5 ** (days_ago / max(half_life_days, 1e-6))


def train_bucket_model(train_df: pd.DataFrame, valid_df: pd.DataFrame, feat_cols: list[str]) -> lgb.Booster:
    dtrain = lgb.Dataset(train_df[feat_cols], train_df[TARGET], weight=train_df["_w"])
    dvalid = lgb.Dataset(valid_df[feat_cols], valid_df[TARGET], reference=dtrain, weight=valid_df["_w"])
    return lgb.train(
        PARAMS,
        dtrain,
        num_boost_round=1600,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(80, verbose=False)],
    )


def main() -> None:
    path = PROCESSED_DIR / "features_realistic.parquet"
    if not path.exists():
        raise SystemExit(f"missing {path}. Run scripts/02_build_features.py first.")

    df = pd.read_parquet(path).dropna(subset=[TARGET]).sort_index()
    feat_cols = _drop_target_leakage(df)

    end = df.index.max()
    test_start = end - pd.Timedelta(days=TEST_DAYS)
    test_df = df.loc[df.index >= test_start].copy()

    print(f"Test window: {test_df.index.min()} -> {test_df.index.max()} ({len(test_df)} rows)")
    print(f"Buckets: {24 // BUCKET_HOURS} (each {BUCKET_HOURS}h)")
    print(f"Seasonal sigma={SIGMA_DAYS}d, recency half-life={RECENCY_HALFLIFE_DAYS}d")

    forecasts = []
    days = pd.unique(test_df.index.normalize())

    for day in days:
        day_start = pd.Timestamp(day)
        day_df = test_df.loc[test_df.index.normalize() == day]
        if day_df.empty:
            continue

        train_pool = df.loc[df.index < day_start].copy()
        if train_pool.empty:
            continue

        doy = int(day_start.dayofyear)
        train_pool["_doy"] = train_pool.index.dayofyear
        train_pool["_days_ago"] = (day_start - train_pool.index).total_seconds() / 86400.0
        train_pool["_w"] = train_pool["_doy"].apply(
            lambda x: gaussian_weight(day_of_year_distance(int(x), doy), SIGMA_DAYS)
        ) * train_pool["_days_ago"].apply(
            lambda d: recency_weight(float(d), RECENCY_HALFLIFE_DAYS)
        )

        for bucket in range(24 // BUCKET_HOURS):
            day_bucket = day_df[(day_df.index.hour // BUCKET_HOURS) == bucket]
            if day_bucket.empty:
                continue

            train_bucket = train_pool[(train_pool.index.hour // BUCKET_HOURS) == bucket]
            if len(train_bucket) < 2000:
                continue

            # Validation = last 14 days before day_start within the same bucket.
            valid_cut = day_start - pd.Timedelta(days=14)
            valid_bucket = train_bucket[train_bucket.index >= valid_cut]
            train_bucket = train_bucket[train_bucket.index < valid_cut]
            if len(valid_bucket) < 200 or len(train_bucket) < 1000:
                continue

            model = train_bucket_model(train_bucket, valid_bucket, feat_cols)
            yhat = model.predict(day_bucket[feat_cols], num_iteration=model.best_iteration)
            forecasts.append(pd.Series(yhat, index=day_bucket.index))

    if not forecasts:
        raise SystemExit("no forecasts produced; check bucket sizes")

    forecast = pd.concat(forecasts).sort_index()
    realized = test_df.loc[forecast.index, TARGET]

    results = rolling_backtest(realized, forecast)
    out_csv = REPORTS_DIR / "time_bucket_capture_ratio.csv"
    out_json = REPORTS_DIR / "time_bucket_capture_ratio.json"
    results.to_csv(out_csv)
    out_json.write_text(json.dumps(summary(results), indent=2))

    print("\nCapture ratio summary:")
    print(json.dumps(summary(results), indent=2))
    print(f"\nsaved {out_csv}")
    print(f"saved {out_json}")


if __name__ == "__main__":
    main()
