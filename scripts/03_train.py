from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import PROCESSED_DIR
from src import forecaster


def main():
    path = PROCESSED_DIR / "features.parquet"
    if not path.exists():
        raise SystemExit(f"missing {path}. Run scripts/02_build_features.py first.")
    df = pd.read_parquet(path)
    print(f"loaded features: rows={len(df)}  cols={len(df.columns)}")
    result = forecaster.train(df)
    saved = result.save()
    print(f"model saved -> {saved}")


if __name__ == "__main__":
    main()
