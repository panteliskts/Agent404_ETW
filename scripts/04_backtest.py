from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from config import PROCESSED_DIR, REPORTS_DIR
from src import evaluate, forecaster


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--models-dir", default=None, help="Override models directory (default: models/)")
    args = p.parse_args()

    if args.models_dir:
        config.MODELS_DIR = Path(args.models_dir).resolve()

    df = pd.read_parquet(PROCESSED_DIR / "features.parquet")
    booster, feat_cols = forecaster.load()

    test = df.tail(96 * 30).copy()
    realized = test["dam_price_eur_mwh"]
    forecast = forecaster.predict(booster, test, feat_cols)

    results = evaluate.rolling_backtest(realized, forecast)
    out = REPORTS_DIR / "backtest_daily.csv"
    results.to_csv(out)
    summary = evaluate.summary(results)
    (REPORTS_DIR / "backtest_summary.json").write_text(json.dumps(summary, indent=2))

    print("\n=== BACKTEST SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k:32s}  {v:,.2f}" if isinstance(v, float) else f"  {k:32s}  {v}")


if __name__ == "__main__":
    main()
