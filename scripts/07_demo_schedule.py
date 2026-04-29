"""Demo: produce a 96-row battery decision schedule for one date.

Output CSV: reports/schedule_<date>.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import PROCESSED_DIR, REPORTS_DIR
from src.inference import decide_schedule


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None, help="Target date YYYY-MM-DD (defaults to last available)")
    args = p.parse_args()

    if args.date is None:
        df = pd.read_parquet(PROCESSED_DIR / "features_realistic.parquet")
        target = df.index.max().date()
    else:
        target = args.date

    print(f"target date: {target}")
    schedule = decide_schedule(target)
    out = REPORTS_DIR / f"schedule_{target}.csv"
    schedule.to_csv(out)

    counts = schedule["action"].value_counts().to_dict()
    print(f"  expected revenue (forecast): {schedule.attrs['expected_revenue_eur']:.2f} EUR")
    print(f"  action counts: {counts}")
    print(f"  saved {out}")
    print()
    print(schedule.head(8).to_string())


if __name__ == "__main__":
    main()
