"""Grid-search LightGBM hyperparameters on realistic-lags features.

Search space (from handoff):
  - learning_rate: [0.01, 0.05, 0.1]
  - num_leaves: [31, 63, 127]
  - min_data_in_leaf: [30, 50, 100]

Uses rolling-origin CV and saves a sorted table to reports/hparam_tuning.csv.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import PROCESSED_DIR, REPORTS_DIR
from src.forecaster import rolling_origin_cv


def main() -> None:
    path = PROCESSED_DIR / "features_realistic.parquet"
    if not path.exists():
        raise SystemExit(f"missing {path}. Run scripts/02_build_features.py first.")

    df = pd.read_parquet(path)
    print(f"loaded REALISTIC features: rows={len(df)}  cols={len(df.columns)}")

    grid = {
        "learning_rate": [0.01, 0.05, 0.1],
        "num_leaves": [63, 127],
        "min_data_in_leaf": [30, 50],
    }

    rows = []
    combos = list(itertools.product(grid["learning_rate"], grid["num_leaves"], grid["min_data_in_leaf"]))
    print(f"grid size: {len(combos)}")

    n_folds = 3
    test_days = 7
    valid_days = 14

    for lr, leaves, min_leaf in combos:
        params = {
            "learning_rate": lr,
            "num_leaves": leaves,
            "min_data_in_leaf": min_leaf,
        }
        cv = rolling_origin_cv(
            df,
            n_folds=n_folds,
            test_days=test_days,
            valid_days=valid_days,
            model="lgbm",
            lgbm_params=params,
        )
        if cv.empty:
            continue
        mean_mae = float(cv["mae"].mean())
        std_mae = float(cv["mae"].std())
        rows.append({
            "learning_rate": lr,
            "num_leaves": leaves,
            "min_data_in_leaf": min_leaf,
            "mae_mean": mean_mae,
            "mae_std": std_mae,
            "rmse_mean": float(cv["rmse"].mean()),
            "n_folds": int(len(cv)),
        })
        print(
            f"  lr={lr:<4} leaves={leaves:<3} min_leaf={min_leaf:<3} "
            f"-> MAE={mean_mae:.2f} (std {std_mae:.2f}, folds {len(cv)})"
        )

    if not rows:
        raise SystemExit("no CV rows produced; check data and folds")

    out = pd.DataFrame(rows).sort_values("mae_mean").reset_index(drop=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "hparam_tuning.csv"
    out.to_csv(out_path, index=False)
    print(f"\nsaved {out_path}")
    print("\nTop 5:")
    print(out.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
