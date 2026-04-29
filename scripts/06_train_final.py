"""Train the final q10/q50/q90 quantile models on the realistic-lags dataset.

Output models land in models/lgbm_q10.{txt,json}, lgbm_q50.*, lgbm_q90.* —
loaded by src/inference.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import PROCESSED_DIR, REPORTS_DIR
from src.forecaster import (
    QUANTILE_ALPHAS,
    rolling_origin_cv,
    train_all_quantiles,
)


def main():
    path = PROCESSED_DIR / "features_realistic.parquet"
    if not path.exists():
        raise SystemExit(f"missing {path}. Run scripts/02_build_features.py first.")

    df = pd.read_parquet(path)
    print(f"loaded REALISTIC features: rows={len(df)}  cols={len(df.columns)}")

    print("\n[CV] rolling-origin (5 folds, 14d each) on realistic-lags dataset:")
    cv = rolling_origin_cv(df, n_folds=5, test_days=14, valid_days=14, model="lgbm")
    print(cv.to_string(index=False))
    print(f"  mean MAE = {cv['mae'].mean():.2f}   std = {cv['mae'].std():.2f}")
    cv.to_csv(REPORTS_DIR / "final_cv.csv", index=False)

    print("\n[TRAIN] q10 / q50 / q90 quantile models")
    results = train_all_quantiles(df, valid_days=30, test_days=7)
    summary = {
        f"q{int(a*100):02d}": {
            "best_iter": results[f"q{int(a*100):02d}"].metrics["best_iter"],
            "n_features": len(results[f"q{int(a*100):02d}"].feature_cols),
        }
        for a in QUANTILE_ALPHAS
    }
    summary["cv_mae_mean"] = float(cv["mae"].mean())
    summary["cv_mae_std"] = float(cv["mae"].std())
    summary["cv_rmse_mean"] = float(cv["rmse"].mean())
    summary["n_train_rows"] = int(len(df))
    summary["features_used"] = list(results["q50"].feature_cols)

    out = REPORTS_DIR / "final_model_summary.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nsaved {out}")
    print(f"models saved to: {ROOT / 'models'}")


if __name__ == "__main__":
    main()
