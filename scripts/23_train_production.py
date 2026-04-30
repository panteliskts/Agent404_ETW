"""Train the production quantile stack on ALL data and persist to models/.

Mirrors the recipe used by the best walk-forward run (scripts/22_dynamic_horizon.py):
  - q05, q95: single LightGBM booster with recency × seasonal sample weights
  - q50: ensemble of 3 boosters (seeds 42, 7, 1337) with recency × seasonal
         × economic-impact weighting

Unlike the walk-forward scripts, this trains on the full dataset (the last
14 days are reserved as the validation window for early stopping; nothing is
held back as a "test" set — production deployment uses every available row).

Outputs in models/:
  lgbm_q05.txt / lgbm_q05.json
  lgbm_q95.txt / lgbm_q95.json
  lgbm_q50_seed{42,7,1337}.txt / .json   (loaded as ensemble by load_quantile_models)
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

from config import MODELS_DIR, PROCESSED_DIR
from src.forecaster import (
    TARGET,
    TrainResult,
    _drop_target_leakage,
    economic_impact_weights,
    make_sample_weights,
)

VALID_DAYS = 14
RECENCY_HALFLIFE = 90.0
SEASONAL_SIGMA = 30.0
ECONOMIC_WEIGHT_SCALE = 25.0
Q50_SEEDS = [42, 7, 1337]


def _split_full(df: pd.DataFrame, valid_days: int):
    """Return (train, valid) using the last `valid_days` for early-stopping only."""
    end = df.index.max()
    valid_start = end - pd.Timedelta(days=valid_days)
    train = df.loc[df.index < valid_start]
    valid = df.loc[df.index >= valid_start]
    return train, valid


def _weights(train_df, valid_df, ref, economic: bool):
    w_train = make_sample_weights(
        train_df.index, ref_date=ref,
        recency_halflife_days=RECENCY_HALFLIFE,
        seasonal_sigma_days=SEASONAL_SIGMA,
    )
    w_valid = make_sample_weights(
        valid_df.index, ref_date=ref,
        recency_halflife_days=RECENCY_HALFLIFE,
        seasonal_sigma_days=SEASONAL_SIGMA,
    )
    if economic:
        w_train = w_train * economic_impact_weights(train_df[TARGET], scale=ECONOMIC_WEIGHT_SCALE)
        w_valid = w_valid * economic_impact_weights(valid_df[TARGET], scale=ECONOMIC_WEIGHT_SCALE)
    w_train = w_train / max(w_train.mean(), 1e-9)
    w_valid = w_valid / max(w_valid.mean(), 1e-9)
    return w_train, w_valid


def _train_one(train_df, valid_df, feat_cols, alpha, hp, w_train, w_valid, early_patience):
    dtrain = lgb.Dataset(train_df[feat_cols], train_df[TARGET], weight=w_train)
    dvalid = lgb.Dataset(valid_df[feat_cols], valid_df[TARGET], weight=w_valid, reference=dtrain)
    params = {
        "objective": "quantile",
        "alpha": alpha,
        "metric": "quantile",
        "bagging_freq": 5,
        "verbose": -1,
        **hp,
    }
    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=4000,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(early_patience), lgb.log_evaluation(period=0)],
    )
    return booster


def _save(booster: lgb.Booster, feat_cols, metrics, name: str):
    out_txt = MODELS_DIR / f"{name}.txt"
    booster.save_model(str(out_txt))
    (MODELS_DIR / f"{name}.json").write_text(
        json.dumps({"feature_cols": feat_cols, "metrics": metrics}, indent=2)
    )
    return out_txt


def main():
    df = pd.read_parquet(PROCESSED_DIR / "features_clean.parquet")
    df = df.dropna(subset=[TARGET]).sort_index()
    feat_cols = _drop_target_leakage(df)

    train_df, valid_df = _split_full(df, VALID_DAYS)
    ref = valid_df.index.max()  # train as if "today" is the latest observation
    print(f"train rows: {len(train_df):,}   valid rows: {len(valid_df):,}   features: {len(feat_cols)}")
    print(f"train range: {train_df.index.min()} -> {train_df.index.max()}")
    print(f"valid range: {valid_df.index.min()} -> {valid_df.index.max()}")

    base_hp = dict(
        learning_rate=0.05, num_leaves=63, min_data_in_leaf=30,
        feature_fraction=0.85, bagging_fraction=0.85,
    )

    # ── q05 / q95 ──────────────────────────────────────────────────────────
    for alpha, key in [(0.05, "q05"), (0.95, "q95")]:
        print(f"\n[ {key} ] training single booster on full data …")
        w_train, w_valid = _weights(train_df, valid_df, ref, economic=False)
        booster = _train_one(
            train_df, valid_df, feat_cols, alpha,
            hp={**base_hp, "bagging_seed": 42, "feature_fraction_seed": 42},
            w_train=w_train, w_valid=w_valid,
            early_patience=200,
        )
        metrics = {
            "alpha": alpha, "best_iter": int(booster.best_iteration),
            "n_train": int(len(train_df)), "n_valid": int(len(valid_df)),
            "trained_through": str(df.index.max()),
        }
        path = _save(booster, feat_cols, metrics, f"lgbm_{key}")
        print(f"  saved {path}  best_iter={metrics['best_iter']}")

    # ── q50 ensemble (3 seeds, economic weighting) ─────────────────────────
    w_train, w_valid = _weights(train_df, valid_df, ref, economic=True)
    for seed in Q50_SEEDS:
        print(f"\n[ q50 seed={seed} ] training ensemble member …")
        booster = _train_one(
            train_df, valid_df, feat_cols, alpha=0.5,
            hp={**base_hp, "bagging_seed": seed, "feature_fraction_seed": seed},
            w_train=w_train, w_valid=w_valid,
            early_patience=80,
        )
        metrics = {
            "alpha": 0.5, "seed": seed, "best_iter": int(booster.best_iteration),
            "n_train": int(len(train_df)), "n_valid": int(len(valid_df)),
            "ensemble_member": True, "ensemble_seeds": Q50_SEEDS,
            "trained_through": str(df.index.max()),
        }
        path = _save(booster, feat_cols, metrics, f"lgbm_q50_seed{seed}")
        print(f"  saved {path}  best_iter={metrics['best_iter']}")

    # ── back-compat: also persist a single q50 (mean-seed) for fallback ────
    print(f"\n[ q50 (compat single) ] training single booster …")
    booster = _train_one(
        train_df, valid_df, feat_cols, alpha=0.5,
        hp={**base_hp, "bagging_seed": 42, "feature_fraction_seed": 42},
        w_train=w_train, w_valid=w_valid,
        early_patience=80,
    )
    metrics = {
        "alpha": 0.5, "best_iter": int(booster.best_iteration),
        "n_train": int(len(train_df)), "n_valid": int(len(valid_df)),
        "trained_through": str(df.index.max()),
        "note": "fallback single — load_quantile_models prefers lgbm_q50_seed*.txt ensemble",
    }
    _save(booster, feat_cols, metrics, "lgbm_q50")

    print("\n✓ production stack persisted to", MODELS_DIR)


if __name__ == "__main__":
    main()
