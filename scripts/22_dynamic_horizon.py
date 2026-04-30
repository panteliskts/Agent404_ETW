"""Dynamic rolling-horizon MPC using confidence-based horizon selection.

Chooses 2-4 day horizon per day based on forecast uncertainty, and applies
geometric discounting to future days to hedge forecast error.

Outputs:
  reports/dynamic_horizon_summary.json
  reports/dynamic_horizon_daily.csv
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
    TARGET,
    conformal_calibrate,
    predict_interval,
    train_quantile,
)
from src.scheduler import optimize, optimize_multiday_horizon, realized_revenue

TEST_DAYS = 30
WEEK_DAYS = 7
RECENCY_HALFLIFE = 90.0
SEASONAL_SIGMA = 30.0
ECONOMIC_WEIGHT_SCALE = 25.0
SOFT_CYCLIC_PENALTY = 3.0
SPREAD_PCT_GRID = [0, 5, 10, 15, 20, 25, 30, 40]

HORIZON_MIN = 2
HORIZON_MID = 3
HORIZON_MAX = 4
FUTURE_BASE_DISCOUNT = 0.1
FUTURE_DECAY = 0.6


def _battery():
    return replace(DEFAULT_BATTERY, cyclic_penalty=SOFT_CYCLIC_PENALTY)


def _discount_curve(horizon_days: int) -> list[float]:
    discounts = [1.0]
    for i in range(1, horizon_days):
        discounts.append(FUTURE_BASE_DISCOUNT * (FUTURE_DECAY ** (i - 1)))
    return discounts


def _daily_spread_mean(q05: pd.Series, q95: pd.Series) -> pd.Series:
    spread = (q95 - q05)
    return spread.groupby(spread.index.normalize()).mean()


def _choose_horizon(spread_mean: float, thr_low: float, thr_high: float) -> int:
    if spread_mean <= thr_low:
        return HORIZON_MAX
    if spread_mean <= thr_high:
        return HORIZON_MID
    return HORIZON_MIN


def dispatch_day_dynamic(days, unique_days, i, pred_full, idle_mask, battery, horizon_days):
    m0 = days == unique_days[i]
    if m0.sum() < 90:
        return None, False
    if i + horizon_days - 1 < len(unique_days):
        prices_by_day = []
        masks_by_day = []
        for j in range(horizon_days):
            dj = unique_days[i + j]
            mj = days == dj
            prices_by_day.append(pred_full[mj])
            masks_by_day.append(idle_mask[mj] if idle_mask is not None else None)
        discounts = _discount_curve(horizon_days)
        return (
            optimize_multiday_horizon(
                prices_by_day,
                battery=battery,
                idle_masks=masks_by_day,
                discounts=discounts,
            ),
            True,
        )
    im = idle_mask[m0] if idle_mask is not None else None
    return optimize(pred_full[m0], battery=battery, idle_mask=im), False


def backtest_dynamic(pred_full, realized, idle_mask, battery, daily_spread, thr_low, thr_high):
    rows = []
    days = pred_full.index.normalize()
    unique_days = days.unique().sort_values()
    spread_daily = daily_spread.reindex(unique_days).ffill()

    for i, d in enumerate(unique_days):
        m0 = days == d
        if m0.sum() < 90:
            continue
        try:
            real_d = realized[m0]
            perf = optimize(real_d, battery=battery)
            spread_mean = float(spread_daily.loc[d])
            horizon_days = _choose_horizon(spread_mean, thr_low, thr_high)
            sched, used_horizon = dispatch_day_dynamic(
                days, unique_days, i, pred_full, idle_mask, battery, horizon_days
            )
            if sched is None:
                continue
            rev = realized_revenue(sched, real_d, battery=battery)
            rows.append({
                "date": pd.Timestamp(d).date(),
                "perfect_eur": perf.objective_eur,
                "realized_eur": rev,
                "capture_ratio": rev / perf.objective_eur if perf.objective_eur > 0 else 0.0,
                "horizon_days": horizon_days,
                "spread_mean": round(spread_mean, 4),
                "used_horizon": used_horizon,
            })
        except Exception as exc:
            print(f"    dynamic {d.date()} skipped: {exc}")
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def tune_idle_threshold(disp, real, q05, q95, battery):
    spreads = (q95 - q05).values
    best_thr, best_rev = 0.0, -np.inf
    for pct in SPREAD_PCT_GRID:
        thr = float(np.percentile(spreads, pct)) if pct > 0 else 0.0
        idle = pd.Series((q95 - q05) < thr, index=disp.index)
        bt = backtest_dynamic(disp, real, idle, battery,
                              _daily_spread_mean(q05, q95),
                              thr_low=np.percentile(spreads, 33),
                              thr_high=np.percentile(spreads, 66))
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
    q_tail = {}
    for a in [0.05, 0.95]:
        k = f"q{int(a * 100):02d}"
        q_tail[k] = train_quantile(
            train_pool, alpha=a, valid_days=30, test_days=7,
            sample_weights=True,
            recency_halflife_days=RECENCY_HALFLIFE,
            seasonal_sigma_days=SEASONAL_SIGMA,
        )
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

    valid_q = predict_interval(q_tail, valid_df)
    valid_q.columns = ["q05", "q95"]
    valid_q["q50"] = _ensemble_predict(q50_seeds, valid_df)
    valid_q = valid_q[["q05", "q50", "q95"]]

    week_q = predict_interval(q_tail, week_df)
    week_q.columns = ["q05", "q95"]
    week_q["q50"] = _ensemble_predict(q50_seeds, week_df)
    week_q = week_q[["q05", "q50", "q95"]]

    for c, a in [("q05", 0.05), ("q50", 0.50), ("q95", 0.95)]:
        week_q[c] = conformal_calibrate(valid_q[c], valid_df[TARGET], week_q[c], alpha=a)

    valid_disp = 0.6 * valid_q["q50"] + 0.2 * valid_q["q05"] + 0.2 * valid_q["q95"]
    week_disp = 0.6 * week_q["q50"] + 0.2 * week_q["q05"] + 0.2 * week_q["q95"]

    bat = _battery()
    thr = tune_idle_threshold(valid_disp, valid_df[TARGET], valid_q["q05"], valid_q["q95"], bat)
    week_idle = pd.Series((week_q["q95"] - week_q["q05"]) < thr, index=week_q.index)

    valid_daily_spread = _daily_spread_mean(valid_q["q05"], valid_q["q95"])
    thr_low = float(valid_daily_spread.quantile(0.33))
    thr_high = float(valid_daily_spread.quantile(0.66))

    return week_disp, week_idle, week_df[TARGET], week_q, thr, thr_low, thr_high


def main():
    df = pd.read_parquet(PROCESSED_DIR / "features_clean.parquet")
    df = df.dropna(subset=[TARGET]).sort_index()
    end = df.index.max()
    test_window_start = end - pd.Timedelta(days=TEST_DAYS)

    fold_starts = [test_window_start + pd.Timedelta(days=i * WEEK_DAYS) for i in range(5)]
    fold_ends = [s + pd.Timedelta(days=WEEK_DAYS) for s in fold_starts]
    test_end = end + pd.Timedelta(seconds=1)
    fold_ends[-1] = min(fold_ends[-1], test_end)

    fold_data = []
    for i, (fstart, fend) in enumerate(zip(fold_starts, fold_ends)):
        if fstart >= test_end or (fend - fstart).total_seconds() < 86400:
            continue
        train_pool = df.loc[df.index < fstart].copy()
        valid_df = df.loc[(df.index >= fstart - pd.Timedelta(days=14)) &
                          (df.index < fstart)].copy()
        week_df = df.loc[(df.index >= fstart) & (df.index < fend)].copy()
        if len(week_df) < 96:
            continue
        print(f"\n[FOLD {i}] train<{fstart.date()}  week={fstart.date()}-{fend.date()}")
        week_disp, week_idle, week_real, week_q, thr, thr_low, thr_high = run_fold(
            train_pool, valid_df, week_df
        )
        fold_data.append((week_disp, week_idle, week_real, week_q, thr, thr_low, thr_high))
        print(f"  idle_threshold={thr:.2f}  spread_thr_low={thr_low:.2f}  spread_thr_high={thr_high:.2f}")

    bat = _battery()
    all_bt = []
    for week_disp, week_idle, week_real, week_q, _thr, thr_low, thr_high in fold_data:
        daily_spread = _daily_spread_mean(week_q["q05"], week_q["q95"])
        bt = backtest_dynamic(week_disp, week_real, week_idle, bat, daily_spread, thr_low, thr_high)
        if len(bt):
            all_bt.append(bt)

    full = pd.concat(all_bt) if all_bt else pd.DataFrame()

    summary = {
        "total_days": int(len(full)),
        "mean_capture_ratio": round(float(full["capture_ratio"].mean()), 4),
        "median_capture_ratio": round(float(full["capture_ratio"].median()), 4),
        "overall_capture_ratio": round(float(full["realized_eur"].sum() / max(full["perfect_eur"].sum(), 1e-9)), 4),
        "total_realized_eur": round(float(full["realized_eur"].sum()), 2),
        "mean_eur_per_day": round(float(full["realized_eur"].mean()), 2),
        "horizon_counts": full["horizon_days"].value_counts().to_dict() if len(full) else {},
        "config": {
            "horizon_min": HORIZON_MIN,
            "horizon_mid": HORIZON_MID,
            "horizon_max": HORIZON_MAX,
            "future_base_discount": FUTURE_BASE_DISCOUNT,
            "future_decay": FUTURE_DECAY,
        },
    }

    (REPORTS_DIR / "dynamic_horizon_summary.json").write_text(
        json.dumps(summary, indent=2)
    )
    if len(full):
        full.reset_index().to_csv(REPORTS_DIR / "dynamic_horizon_daily.csv", index=False)

    print("\n=== DYNAMIC HORIZON SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"\nsaved {REPORTS_DIR / 'dynamic_horizon_summary.json'}")
    if len(full):
        print(f"saved {REPORTS_DIR / 'dynamic_horizon_daily.csv'}")


if __name__ == "__main__":
    main()
