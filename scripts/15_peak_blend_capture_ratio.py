"""Backtest capture ratio using a peak classifier and peak-weighted regressor.

Blend (option 2):
  y_hat = (1 - p_peak) * base_pred + p_peak * spike_pred

Outputs:
  reports/peak_blend_capture_ratio.csv
  reports/peak_blend_capture_ratio.json
"""
from __future__ import annotations

import json
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
PEAK_PCTL = 0.80
PEAK_ALPHA = 3.0

REG_PARAMS = {
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

CLS_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 30,
    "feature_fraction": 0.85,
    "bagging_fraction": 0.85,
    "bagging_freq": 5,
    "verbose": -1,
}


def train_regressor(train_df: pd.DataFrame, valid_df: pd.DataFrame, feat_cols: list[str]) -> lgb.Booster:
    dtrain = lgb.Dataset(train_df[feat_cols], train_df[TARGET], weight=train_df.get("_w"))
    dvalid = lgb.Dataset(valid_df[feat_cols], valid_df[TARGET], reference=dtrain, weight=valid_df.get("_w"))
    return lgb.train(
        REG_PARAMS,
        dtrain,
        num_boost_round=2000,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(80, verbose=False)],
    )


def train_classifier(train_df: pd.DataFrame, valid_df: pd.DataFrame, feat_cols: list[str], peak_price: float) -> lgb.Booster:
    y_train = (train_df[TARGET] >= peak_price).astype(int)
    y_valid = (valid_df[TARGET] >= peak_price).astype(int)
    pos = float(y_train.sum())
    neg = float(len(y_train) - pos)
    scale_pos_weight = (neg / max(pos, 1.0))

    params = dict(CLS_PARAMS)
    params["scale_pos_weight"] = scale_pos_weight

    dtrain = lgb.Dataset(train_df[feat_cols], y_train)
    dvalid = lgb.Dataset(valid_df[feat_cols], y_valid, reference=dtrain)
    return lgb.train(
        params,
        dtrain,
        num_boost_round=2000,
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
    valid_start = test_start - pd.Timedelta(days=30)

    train_df = df.loc[df.index < valid_start].copy()
    valid_df = df.loc[(df.index >= valid_start) & (df.index < test_start)].copy()
    test_df = df.loc[df.index >= test_start].copy()

    peak_price = float(train_df[TARGET].quantile(PEAK_PCTL))
    print(f"Peak threshold p{int(PEAK_PCTL * 100)} = {peak_price:.2f} EUR/MWh")

    # Base regressor
    base_model = train_regressor(train_df, valid_df, feat_cols)
    base_pred = base_model.predict(test_df[feat_cols], num_iteration=base_model.best_iteration)

    # Peak-weighted regressor
    train_df_w = train_df.copy()
    valid_df_w = valid_df.copy()
    train_df_w["_w"] = 1.0 + PEAK_ALPHA * (train_df_w[TARGET] >= peak_price).astype(float)
    valid_df_w["_w"] = 1.0 + PEAK_ALPHA * (valid_df_w[TARGET] >= peak_price).astype(float)
    spike_model = train_regressor(train_df_w, valid_df_w, feat_cols)
    spike_pred = spike_model.predict(test_df[feat_cols], num_iteration=spike_model.best_iteration)

    # Peak classifier
    cls_model = train_classifier(train_df, valid_df, feat_cols, peak_price)
    p_peak = cls_model.predict(test_df[feat_cols], num_iteration=cls_model.best_iteration)
    p_peak = np.clip(p_peak, 0.0, 1.0)

    # Blend
    blend_pred = (1.0 - p_peak) * base_pred + p_peak * spike_pred
    forecast = pd.Series(blend_pred, index=test_df.index, name="blend_pred")
    realized = test_df[TARGET]

    results = rolling_backtest(realized, forecast)
    out_csv = REPORTS_DIR / "peak_blend_capture_ratio.csv"
    out_json = REPORTS_DIR / "peak_blend_capture_ratio.json"
    results.to_csv(out_csv)
    out_json.write_text(json.dumps(summary(results), indent=2))

    print("\nCapture ratio summary:")
    print(json.dumps(summary(results), indent=2))
    print(f"\nsaved {out_csv}")
    print(f"saved {out_json}")


if __name__ == "__main__":
    main()
