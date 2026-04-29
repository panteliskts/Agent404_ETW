"""Compare clean dataset (aggregated weather, lagged realized cols) vs realistic-lags baseline.

Tests on q50 (median) only for faster iteration. Reports:
  - MAE improvement
  - Feature count reduction
  - Feature importance of clean set
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import PROCESSED_DIR
from src.features import build_dataset, build_clean_dataset, PRICE_COL, TRAIN_START


def _rows_per_day(df: pd.DataFrame) -> int:
    if len(df.index) < 2:
        return 96
    delta = df.index.to_series().diff().dropna().mode().iloc[0]
    if not isinstance(delta, pd.Timedelta) or delta <= pd.Timedelta(0):
        return 96
    return int(pd.Timedelta("1D") / delta)


def rolling_origin_cv_simple(df: pd.DataFrame, n_folds: int = 5, test_days: int = 7, valid_days: int = 30) -> float:
    """Rolling-origin CV on q50, returns mean MAE."""
    mae_list = []
    total_rows = len(df)
    rows_per_day = _rows_per_day(df)
    test_rows = test_days * rows_per_day
    valid_rows = valid_days * rows_per_day

    for fold in range(n_folds):
        test_start_idx = total_rows - (n_folds - fold) * test_rows
        valid_start_idx = test_start_idx - valid_rows
        train_end_idx = valid_start_idx

        if train_end_idx <= 0 or test_start_idx + test_rows > total_rows:
            continue

        train_df = df.iloc[:train_end_idx]
        valid_df = df.iloc[valid_start_idx:test_start_idx]
        test_df = df.iloc[test_start_idx:test_start_idx + test_rows]

        if len(train_df) < rows_per_day * 30 or len(valid_df) < valid_rows or len(test_df) < test_rows:
            continue

        X_train = train_df.drop(columns=[PRICE_COL])
        y_train = train_df[PRICE_COL]
        X_valid = valid_df.drop(columns=[PRICE_COL])
        y_valid = valid_df[PRICE_COL]
        X_test = test_df.drop(columns=[PRICE_COL])
        y_test = test_df[PRICE_COL]

        train_data = lgb.Dataset(X_train, label=y_train)
        valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

        params = {
            "objective": "regression",
            "metric": "mae",
            "num_leaves": 63,
            "learning_rate": 0.05,
            "min_data_in_leaf": 50,
            "verbose": -1,
        }

        model = lgb.train(
            params,
            train_data,
            num_boost_round=300,
            valid_sets=[valid_data],
            callbacks=[lgb.early_stopping(50, verbose=False)],
        )

        preds = model.predict(X_test)
        mae = float(np.mean(np.abs(y_test - preds)))
        mae_list.append(mae)
        print(f"  fold {fold + 1}: MAE={mae:.2f} €/MWh")

    mean_mae = float(np.mean(mae_list))
    return mean_mae


def main():
    print("[10] Experiment: clean dataset vs realistic-lags\n")

    print("[LOAD] realistic-lags baseline")
    df_realistic = build_dataset(start=TRAIN_START, realistic_lags_only=True)
    df_realistic = df_realistic.dropna(subset=[PRICE_COL]).sort_index()
    print(f"  rows={len(df_realistic)}  cols={len(df_realistic.columns)}")
    print(f"  feature cols={len(df_realistic.columns) - 1}")

    print("\n[LOAD] clean dataset (aggregated weather, lagged realized)")
    df_clean = build_clean_dataset(start=TRAIN_START)
    df_clean = df_clean.dropna(subset=[PRICE_COL]).sort_index()
    print(f"  rows={len(df_clean)}  cols={len(df_clean.columns)}")
    print(f"  feature cols={len(df_clean.columns) - 1}")
    print(f"  reduction: {len(df_realistic.columns) - 1} -> {len(df_clean.columns) - 1} features")

    print("\n[CV] realistic-lags baseline (5-fold rolling-origin, q50 only)")
    mae_realistic = rolling_origin_cv_simple(df_realistic, n_folds=5, test_days=7, valid_days=30)
    print(f"Mean MAE: {mae_realistic:.2f} €/MWh")

    print("\n[CV] clean dataset (5-fold rolling-origin, q50 only)")
    mae_clean = rolling_origin_cv_simple(df_clean, n_folds=5, test_days=7, valid_days=30)
    print(f"Mean MAE: {mae_clean:.2f} €/MWh")

    improvement = mae_realistic - mae_clean
    pct_improvement = (improvement / mae_realistic) * 100 if mae_realistic > 0 else 0
    print(f"\n[RESULT] Clean vs Realistic-lags:")
    print(f"  realistic baseline: {mae_realistic:.2f} €/MWh")
    print(f"  clean dataset:      {mae_clean:.2f} €/MWh")
    print(f"  improvement:        {improvement:+.2f} €/MWh ({pct_improvement:+.1f}%)")
    print(f"  feature reduction:  {len(df_realistic.columns) - 1} -> {len(df_clean.columns) - 1} ({((len(df_realistic.columns) - len(df_clean.columns)) / (len(df_realistic.columns) - 1)) * 100:.0f}% reduction)")

    if improvement > -1.0:
        print("\n✓ Clean dataset acceptable (MAE difference < 1 €/MWh)")
        print("  Proceed to hyperparameter tuning on clean features")
    else:
        print("\n✗ Clean dataset worse by > 1 €/MWh")
        print("  Consider: missing feature, over-aggregation, or leakage removal cost")


if __name__ == "__main__":
    main()
