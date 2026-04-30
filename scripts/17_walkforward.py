"""Walk-forward 30-day validation: simulates weekly retraining.

Retraining cadence
------------------
For each test week W in the 30-day window:
  - Cut train pool at the start of week W (no future leakage).
  - Train q05/q50/q95 on everything before W with recency+seasonal weighting.
  - Predict the 7 days of week W.
  - Dispatch with tuned idle threshold (re-tuned on the 14 days before W).

This mimics production where the operator retrains on Friday for the next 7 days.

Outputs:
  reports/walkforward_daily.csv
  reports/walkforward_summary.json
"""
from __future__ import annotations

import json
import sys
from copy import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DEFAULT_BATTERY, PROCESSED_DIR, REPORTS_DIR
from src.forecaster import (
    QUANTILE_ALPHAS,
    TARGET,
    conformal_calibrate,
    predict_interval,
    train_quantile,
)
from src.scheduler import optimize, realized_revenue


TEST_DAYS = 30
WEEK_DAYS = 7
RECENCY_HALFLIFE = 90.0
SEASONAL_SIGMA = 30.0
ECONOMIC_WEIGHT_SCALE = 25.0
SOFT_CYCLIC_PENALTY = 3.0
SPREAD_PCT_GRID = [0, 5, 10, 15, 20, 25, 30, 40]


def _battery():
    return replace(DEFAULT_BATTERY, cyclic_penalty=SOFT_CYCLIC_PENALTY)


def daily_backtest(pred, realized, idle_mask=None, battery=None):
    if battery is None:
        battery = _battery()
    rows = []
    days = pred.index.normalize()
    for d in days.unique():
        m = days == d
        if m.sum() < 90:
            continue
        try:
            real_d = realized[m]
            perf = optimize(real_d, battery=battery)
            im = idle_mask[m] if idle_mask is not None else None
            sched = optimize(pred[m], battery=battery, idle_mask=im)
            rev = realized_revenue(sched, real_d, battery=battery)
            rows.append({
                "date": pd.Timestamp(d).date(),
                "perfect_eur": perf.objective_eur,
                "realized_eur": rev,
                "capture_ratio": rev / perf.objective_eur if perf.objective_eur > 0 else 0.0,
                "idle_mtus": int(im.sum()) if im is not None else 0,
            })
        except Exception as exc:
            print(f"    {d.date()} skipped: {exc}")
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def tune_idle_threshold(disp, real, q05, q95, battery):
    spreads = (q95 - q05).values
    best_thr, best_rev = 0.0, -np.inf
    for pct in SPREAD_PCT_GRID:
        thr = float(np.percentile(spreads, pct)) if pct > 0 else 0.0
        idle = pd.Series((q95 - q05) < thr, index=disp.index)
        bt = daily_backtest(disp, real, idle_mask=idle, battery=battery)
        rev = float(bt["realized_eur"].sum()) if len(bt) else -np.inf
        if rev > best_rev:
            best_rev, best_thr = rev, thr
    return best_thr


def _ensemble_predict(models, frame):
    preds = [
        pd.Series(m.model.predict(frame[m.feature_cols], num_iteration=m.model.best_iteration),
                  index=frame.index)
        for m in models
    ]
    return pd.concat(preds, axis=1).mean(axis=1)


def run_fold(train_pool, valid_df, week_df):
    """Train (q05 + q95 single + q50 ensemble), conformalize, dispatch one week."""
    # Single q05 / q95
    q_tail = {}
    for a in [0.05, 0.95]:
        k = f"q{int(a * 100):02d}"
        q_tail[k] = train_quantile(
            train_pool, alpha=a, valid_days=30, test_days=7,
            sample_weights=True,
            recency_halflife_days=RECENCY_HALFLIFE,
            seasonal_sigma_days=SEASONAL_SIGMA,
        )
    # q50 ensemble (3 seeds, economic-weighted)
    q50_seeds = []
    for seed in [42, 7, 1337]:
        m = train_quantile(
            train_pool, alpha=0.5, valid_days=30, test_days=7,
            sample_weights=True,
            recency_halflife_days=RECENCY_HALFLIFE,
            seasonal_sigma_days=SEASONAL_SIGMA,
            economic_weight=True,
            economic_weight_scale=ECONOMIC_WEIGHT_SCALE,
            hparams=dict(
                learning_rate=0.05, num_leaves=63, min_data_in_leaf=30,
                feature_fraction=0.85, bagging_fraction=0.85,
                bagging_seed=seed, feature_fraction_seed=seed,
            ),
        )
        q50_seeds.append(m)

    # Predict valid + test
    valid_q = predict_interval(q_tail, valid_df); valid_q.columns = ["q05", "q95"]
    valid_q["q50"] = _ensemble_predict(q50_seeds, valid_df)
    valid_q = valid_q[["q05", "q50", "q95"]]
    week_q = predict_interval(q_tail, week_df); week_q.columns = ["q05", "q95"]
    week_q["q50"] = _ensemble_predict(q50_seeds, week_df)
    week_q = week_q[["q05", "q50", "q95"]]

    # Conformal calibration
    week_q["q05"] = conformal_calibrate(valid_q["q05"], valid_df[TARGET], week_q["q05"], alpha=0.05)
    week_q["q50"] = conformal_calibrate(valid_q["q50"], valid_df[TARGET], week_q["q50"], alpha=0.50)
    week_q["q95"] = conformal_calibrate(valid_q["q95"], valid_df[TARGET], week_q["q95"], alpha=0.95)

    valid_disp = 0.6 * valid_q["q50"] + 0.2 * valid_q["q05"] + 0.2 * valid_q["q95"]
    week_disp  = 0.6 * week_q["q50"]  + 0.2 * week_q["q05"]  + 0.2 * week_q["q95"]
    bat = _battery()
    thr = tune_idle_threshold(valid_disp, valid_df[TARGET], valid_q["q05"], valid_q["q95"], bat)
    week_idle = pd.Series((week_q["q95"] - week_q["q05"]) < thr, index=week_q.index)
    bt = daily_backtest(week_disp, week_df[TARGET], idle_mask=week_idle, battery=bat)
    return bt, thr, week_q, week_disp


def main():
    df = pd.read_parquet(PROCESSED_DIR / "features_clean.parquet")
    df = df.dropna(subset=[TARGET]).sort_index()
    end = df.index.max()
    test_window_start = end - pd.Timedelta(days=TEST_DAYS)

    # Walk-forward: each fold trains on data strictly before that fold's start.
    fold_starts = [test_window_start + pd.Timedelta(days=i * WEEK_DAYS) for i in range(5)]
    fold_ends   = [s + pd.Timedelta(days=WEEK_DAYS) for s in fold_starts]
    # last fold trims to test_end
    test_end = end + pd.Timedelta(seconds=1)
    fold_ends[-1] = min(fold_ends[-1], test_end)

    all_bt = []
    fold_summaries = []
    for i, (fstart, fend) in enumerate(zip(fold_starts, fold_ends)):
        if fstart >= test_end:
            break
        if (fend - fstart).total_seconds() < 86400:  # <1 day, skip
            continue
        train_pool = df.loc[df.index < fstart].copy()
        valid_df   = df.loc[(df.index >= fstart - pd.Timedelta(days=14)) &
                             (df.index < fstart)].copy()
        week_df    = df.loc[(df.index >= fstart) & (df.index < fend)].copy()
        if len(week_df) < 96:
            continue
        print(f"\n[FOLD {i}] train<{fstart.date()}  valid={len(valid_df)}  week={fstart.date()}-{fend.date()} ({len(week_df)} rows)")
        bt, thr, week_q, week_disp = run_fold(train_pool, valid_df, week_df)
        if len(bt) == 0:
            continue
        all_bt.append(bt)
        s = {
            "fold": i,
            "train_pool_rows": int(len(train_pool)),
            "week_start": str(fstart.date()),
            "week_end": str(fend.date()),
            "days": int(len(bt)),
            "mean_capture": round(float(bt["capture_ratio"].mean()), 4),
            "overall_capture": round(float(bt["realized_eur"].sum() / max(bt["perfect_eur"].sum(), 1e-9)), 4),
            "median_capture": round(float(bt["capture_ratio"].median()), 4),
            "min_capture": round(float(bt["capture_ratio"].min()), 4),
            "idle_threshold": round(thr, 2),
            "week_realized_eur": round(float(bt["realized_eur"].sum()), 2),
            "week_perfect_eur":  round(float(bt["perfect_eur"].sum()), 2),
        }
        print(f"  fold {i}: mean={s['mean_capture']:.3f}  overall={s['overall_capture']:.3f}  "
              f"realized=€{s['week_realized_eur']:>9.0f}  perfect=€{s['week_perfect_eur']:>9.0f}")
        fold_summaries.append(s)

    full = pd.concat(all_bt) if all_bt else pd.DataFrame()
    full = full.round(2)

    summary = {
        "total_days": int(len(full)),
        "n_folds": len(fold_summaries),
        "mean_capture_ratio":     round(float(full["capture_ratio"].mean()), 3),
        "median_capture_ratio":   round(float(full["capture_ratio"].median()), 3),
        "min_capture_ratio":      round(float(full["capture_ratio"].min()), 3),
        "max_capture_ratio":      round(float(full["capture_ratio"].max()), 3),
        "p10_capture_ratio":      round(float(full["capture_ratio"].quantile(0.10)), 3),
        "p90_capture_ratio":      round(float(full["capture_ratio"].quantile(0.90)), 3),
        "std_capture_ratio":      round(float(full["capture_ratio"].std()), 3),
        "total_perfect_eur":      round(float(full["perfect_eur"].sum()), 2),
        "total_realized_eur":     round(float(full["realized_eur"].sum()), 2),
        "overall_capture_ratio":  round(float(full["realized_eur"].sum() / max(full["perfect_eur"].sum(), 1e-9)), 3),
        "mean_eur_per_day":       round(float(full["realized_eur"].mean()), 2),
        "folds": fold_summaries,
        "config": {
            "recency_halflife_days": RECENCY_HALFLIFE,
            "seasonal_sigma_days": SEASONAL_SIGMA,
            "economic_weight_scale": ECONOMIC_WEIGHT_SCALE,
            "soft_cyclic_penalty": SOFT_CYCLIC_PENALTY,
            "test_days": TEST_DAYS,
            "week_days": WEEK_DAYS,
        },
    }

    print("\n=== WALK-FORWARD SUMMARY ===")
    for k in ["total_days","n_folds","mean_capture_ratio","median_capture_ratio",
              "min_capture_ratio","p10_capture_ratio","overall_capture_ratio",
              "total_realized_eur","mean_eur_per_day"]:
        print(f"  {k:24s}  {summary[k]}")

    (REPORTS_DIR / "walkforward_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    full.to_csv(REPORTS_DIR / "walkforward_daily.csv")
    print(f"\nsaved {REPORTS_DIR / 'walkforward_summary.json'}")
    print(f"saved {REPORTS_DIR / 'walkforward_daily.csv'}")


if __name__ == "__main__":
    main()
