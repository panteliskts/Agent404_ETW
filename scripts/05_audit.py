"""
Model selection / feature audit.

Runs:
  1. Linear Ridge baseline (single test window)
  2. LightGBM full (rolling-origin CV, 5 folds)
  3. Feature-importance dump
  4. LightGBM pruned (drop near-zero importance) — rolling CV
  5. Ablation: with/without extra composite features
Writes summary CSVs to reports/.
"""
from __future__ import annotations

import sys
from pathlib import Path

import lightgbm as lgb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import REPORTS_DIR, PROCESSED_DIR
from src.features import _EXTRA_COMPOSITES
from src.forecaster import (
    TARGET,
    _drop_target_leakage,
    _train_lgbm_quick,
    feature_importance_table,
    rolling_origin_cv,
    time_split,
    train,
    train_ridge,
)


N_FOLDS = 5
TEST_DAYS = 14
VALID_DAYS = 14


def main():
    df_full = pd.read_parquet(PROCESSED_DIR / "features.parquet")
    print(f"loaded features: rows={len(df_full)}  cols={len(df_full.columns)}")

    # --- 1. Linear Ridge baseline (single window) ---
    print("\n[1] Ridge baseline (last 7-day test window)")
    r_ridge = train_ridge(df_full, test_days=7, valid_days=30)
    print(f"  MAE  = {r_ridge['test_mae']:.2f}  RMSE = {r_ridge['test_rmse']:.2f}  n_train={r_ridge['n_train']}  n_test={r_ridge['n_test']}")

    # --- 2. LightGBM full (rolling CV) ---
    print(f"\n[2] LightGBM FULL — rolling-origin CV ({N_FOLDS} folds × {TEST_DAYS}d)")
    cv_full = rolling_origin_cv(df_full, n_folds=N_FOLDS, test_days=TEST_DAYS, valid_days=VALID_DAYS, model="lgbm")
    print(cv_full.to_string(index=False))
    print(f"  mean MAE = {cv_full['mae'].mean():.2f}   std = {cv_full['mae'].std():.2f}")

    # --- 3. Feature-importance dump ---
    print("\n[3] Feature importance (single full-data train)")
    feat_cols = _drop_target_leakage(df_full)
    train_df, valid_df, _ = time_split(df_full.dropna(subset=[TARGET]), valid_days=VALID_DAYS, test_days=TEST_DAYS)
    booster = _train_lgbm_quick(train_df, valid_df, feat_cols)
    imp = feature_importance_table(booster, feat_cols)
    imp_path = REPORTS_DIR / "feature_importance.csv"
    imp.to_csv(imp_path, index=False)
    print(f"  saved {imp_path}")
    print(imp.head(20).to_string(index=False))
    zero_imp = imp.loc[imp["gain"] == 0, "feature"].tolist()
    print(f"  {len(zero_imp)} features with zero gain (will be pruned)")

    # --- 4. LightGBM pruned (drop bottom features by gain) ---
    keep_threshold_pct = 0.20
    cumulative = imp["gain_pct"].cumsum()
    keep_mask = (imp["gain_pct"] > keep_threshold_pct) | (cumulative <= 99.0)
    keep_cols = imp.loc[keep_mask, "feature"].tolist()
    print(f"\n[4] LightGBM PRUNED — keeping {len(keep_cols)}/{len(feat_cols)} features (>{keep_threshold_pct}% gain or top 99% cumulative)")
    cv_pruned = rolling_origin_cv(df_full, n_folds=N_FOLDS, test_days=TEST_DAYS, valid_days=VALID_DAYS, feature_cols=keep_cols, model="lgbm")
    print(cv_pruned.to_string(index=False))
    print(f"  mean MAE = {cv_pruned['mae'].mean():.2f}   std = {cv_pruned['mae'].std():.2f}")

    # --- 5. Ablation: drop extra composites ---
    extras_present = [c for c in _EXTRA_COMPOSITES if c in df_full.columns]
    print(f"\n[5] Ablation — with vs without extra composites: {extras_present}")
    df_no_extras = df_full.drop(columns=extras_present)
    cv_no_extras = rolling_origin_cv(df_no_extras, n_folds=N_FOLDS, test_days=TEST_DAYS, valid_days=VALID_DAYS, model="lgbm")
    print(cv_no_extras.to_string(index=False))
    print(f"  mean MAE without extras = {cv_no_extras['mae'].mean():.2f}")

    # --- Summary table ---
    summary = pd.DataFrame([
        {"model": "Ridge (single window)", "mae": r_ridge["test_mae"], "rmse": r_ridge["test_rmse"], "n_features": len(r_ridge["feature_cols"])},
        {"model": "LGBM full (CV mean)", "mae": cv_full["mae"].mean(), "rmse": cv_full["rmse"].mean(), "n_features": len(feat_cols)},
        {"model": "LGBM pruned (CV mean)", "mae": cv_pruned["mae"].mean(), "rmse": cv_pruned["rmse"].mean(), "n_features": len(keep_cols)},
        {"model": "LGBM no-extras (CV mean)", "mae": cv_no_extras["mae"].mean(), "rmse": cv_no_extras["rmse"].mean(), "n_features": len(feat_cols) - len(extras_present)},
    ])
    print("\n=== SUMMARY ===")
    print(summary.round(2).to_string(index=False))
    summary_path = REPORTS_DIR / "audit_summary.csv"
    summary.to_csv(summary_path, index=False)
    print(f"\nsaved {summary_path}")
    print(f"saved {imp_path}")

    # Persist kept-features list for use by the main trainer
    (REPORTS_DIR / "kept_features.txt").write_text("\n".join(keep_cols))
    print(f"saved {REPORTS_DIR / 'kept_features.txt'}")


if __name__ == "__main__":
    main()
