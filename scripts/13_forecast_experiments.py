"""Run forecast experiments on realistic-lags features.

Experiments:
  1) baseline (tuned params)
  2) price-weighted (upweight high-price periods)
  3) blended (baseline + weighted, volatility-gated)

Outputs reports/forecast_experiments.csv.
"""
from __future__ import annotations

import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import PROCESSED_DIR, REPORTS_DIR
from src.forecaster import TARGET, _drop_target_leakage

TEST_DAYS = 30

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


def train_lgbm(train_df: pd.DataFrame, valid_df: pd.DataFrame, feat_cols: list[str]) -> lgb.Booster:
    dtrain = lgb.Dataset(train_df[feat_cols], train_df[TARGET], weight=train_df.get("_w"))
    dvalid = lgb.Dataset(valid_df[feat_cols], valid_df[TARGET], reference=dtrain, weight=valid_df.get("_w"))
    return lgb.train(
        PARAMS,
        dtrain,
        num_boost_round=2000,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(80, verbose=False)],
    )


def make_price_weights(y: pd.Series, pctl: float = 0.80, alpha: float = 2.0) -> pd.Series:
    thresh = float(y.quantile(pctl))
    w = np.ones(len(y), dtype=float)
    w[y.values >= thresh] = 1.0 + alpha
    return pd.Series(w, index=y.index)


def pick_vol_feature(feat_cols: list[str]) -> str | None:
    candidates = [c for c in feat_cols if "dam_price_eur_mwh" in c and "roll_std" in c]
    if not candidates:
        return None
    # Prefer 96-step (1-day) std if present.
    for c in candidates:
        if "96" in c:
            return c
    return candidates[0]


def eval_mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def eval_weighted_mae(y_true: np.ndarray, y_pred: np.ndarray, weights: np.ndarray) -> float:
    return float(np.average(np.abs(y_true - y_pred), weights=weights))


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

    print(f"Train: {train_df.index.min()} -> {train_df.index.max()} ({len(train_df)} rows)")
    print(f"Valid: {valid_df.index.min()} -> {valid_df.index.max()} ({len(valid_df)} rows)")
    print(f"Test:  {test_df.index.min()} -> {test_df.index.max()} ({len(test_df)} rows)")

    # Baseline
    base_model = train_lgbm(train_df, valid_df, feat_cols)
    base_pred = base_model.predict(test_df[feat_cols], num_iteration=base_model.best_iteration)

    # Price-weighted
    train_df_w = train_df.copy()
    valid_df_w = valid_df.copy()
    train_df_w["_w"] = make_price_weights(train_df_w[TARGET], pctl=0.80, alpha=2.0)
    valid_df_w["_w"] = make_price_weights(valid_df_w[TARGET], pctl=0.80, alpha=2.0)
    w_model = train_lgbm(train_df_w, valid_df_w, feat_cols)
    w_pred = w_model.predict(test_df[feat_cols], num_iteration=w_model.best_iteration)

    # Volatility-gated blend
    vol_col = pick_vol_feature(feat_cols)
    if vol_col:
        vol = test_df[vol_col].values
        p50, p90 = np.percentile(vol, [50, 90])
        denom = max(p90 - p50, 1e-6)
        gate = np.clip((vol - p50) / denom, 0.0, 1.0)
        blend_pred = gate * w_pred + (1.0 - gate) * base_pred
    else:
        blend_pred = None

    # Metrics
    y_true = test_df[TARGET].values
    high_w = make_price_weights(test_df[TARGET], pctl=0.80, alpha=2.0).values

    rows = []
    rows.append({
        "model": "baseline",
        "mae": eval_mae(y_true, base_pred),
        "w_mae": eval_weighted_mae(y_true, base_pred, high_w),
    })
    rows.append({
        "model": "price_weighted",
        "mae": eval_mae(y_true, w_pred),
        "w_mae": eval_weighted_mae(y_true, w_pred, high_w),
    })
    if blend_pred is not None:
        rows.append({
            "model": f"blend_vol_gated_{vol_col}",
            "mae": eval_mae(y_true, blend_pred),
            "w_mae": eval_weighted_mae(y_true, blend_pred, high_w),
        })

    out = pd.DataFrame(rows).sort_values("mae").reset_index(drop=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "forecast_experiments.csv"
    out.to_csv(out_path, index=False)

    print("\nResults:")
    print(out.to_string(index=False))
    print(f"\nsaved {out_path}")


if __name__ == "__main__":
    main()
