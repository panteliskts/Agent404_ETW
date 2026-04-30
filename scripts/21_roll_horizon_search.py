"""Grid search over rolling-horizon length using a fixed future-day discount.

Trains each fold ONCE, then sweeps horizon length at dispatch time.
Evaluates monthly (30-day) overall capture ratio as the primary KPI.

Outputs:
  reports/rolling_horizon_search.json
  reports/rolling_horizon_daily.csv
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

HORIZON_DAYS_GRID = [2, 3, 4, 5, 6, 7]
FUTURE_DISCOUNT = 0.1


def _battery():
    return replace(DEFAULT_BATTERY, cyclic_penalty=SOFT_CYCLIC_PENALTY)


def dispatch_day_horizon(days, unique_days, i, pred_full, idle_mask, battery, horizon_days):
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
        discounts = [1.0] + [FUTURE_DISCOUNT] * (horizon_days - 1)
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


def backtest_horizon(pred_full, realized, idle_mask, battery, horizon_days):
    rows = []
    days = pred_full.index.normalize()
    unique_days = days.unique().sort_values()
    for i, d in enumerate(unique_days):
        m0 = days == d
        if m0.sum() < 90:
            continue
        try:
            real_d = realized[m0]
            perf = optimize(real_d, battery=battery)
            sched, used_horizon = dispatch_day_horizon(
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
                "used_horizon": used_horizon,
            })
        except Exception as exc:
            print(f"    horizon={horizon_days} {d.date()} skipped: {exc}")
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def tune_idle_threshold(disp, real, q05, q95, battery):
    spreads = (q95 - q05).values
    best_thr, best_rev = 0.0, -np.inf
    for pct in SPREAD_PCT_GRID:
        thr = float(np.percentile(spreads, pct)) if pct > 0 else 0.0
        idle = pd.Series((q95 - q05) < thr, index=disp.index)
        bt = backtest_horizon(disp, real, idle, battery, horizon_days=2)
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
    return week_disp, week_idle, week_df[TARGET], thr


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
        week_disp, week_idle, week_real, thr = run_fold(train_pool, valid_df, week_df)
        fold_data.append((week_disp, week_idle, week_real, thr))
        print(f"  idle_threshold={thr:.2f}")

    bat = _battery()
    horizon_results = {}
    summary_rows = []

    print("\n=== HORIZON SWEEP (monthly KPI) ===")
    header = f"{'horizon':>8}  MEAN_CAP  OVERALL_CAP  TOTAL_EUR"
    print(header)

    for horizon_days in HORIZON_DAYS_GRID:
        all_bt = []
        for week_disp, week_idle, week_real, _thr in fold_data:
            bt = backtest_horizon(week_disp, week_real, week_idle, bat, horizon_days)
            if len(bt):
                all_bt.append(bt)
        full = pd.concat(all_bt) if all_bt else pd.DataFrame()
        horizon_results[horizon_days] = full

        mean_cap = float(full["capture_ratio"].mean()) if len(full) else float("nan")
        overall_cap = float(full["realized_eur"].sum() / max(full["perfect_eur"].sum(), 1e-9)) if len(full) else float("nan")
        total_real = float(full["realized_eur"].sum()) if len(full) else 0.0

        summary_rows.append({
            "horizon_days": horizon_days,
            "mean_capture": round(mean_cap, 4) if np.isfinite(mean_cap) else None,
            "overall_capture": round(overall_cap, 4) if np.isfinite(overall_cap) else None,
            "total_realized_eur": round(total_real, 2),
            "mean_eur_per_day": round(float(full["realized_eur"].mean()), 2) if len(full) else None,
        })

        print(f"{horizon_days:>8d}  {mean_cap:>8.4f}  {overall_cap:>11.4f}  {total_real:>9,.0f}")

    summary_df = pd.DataFrame(summary_rows)
    best_overall = summary_df.loc[summary_df["overall_capture"].idxmax()]
    best_eur = summary_df.loc[summary_df["total_realized_eur"].idxmax()]

    (REPORTS_DIR / "rolling_horizon_search.json").write_text(
        json.dumps({
            "summary": summary_rows,
            "best_horizon_overall_capture": int(best_overall["horizon_days"]),
            "best_horizon_total_eur": int(best_eur["horizon_days"]),
            "future_discount": FUTURE_DISCOUNT,
        }, indent=2)
    )

    daily_rows = []
    for horizon_days, df_days in horizon_results.items():
        if len(df_days) == 0:
            continue
        temp = df_days.copy()
        temp["horizon_days"] = horizon_days
        daily_rows.append(temp.reset_index())
    if daily_rows:
        pd.concat(daily_rows).to_csv(REPORTS_DIR / "rolling_horizon_daily.csv", index=False)

    print(f"\nsaved {REPORTS_DIR / 'rolling_horizon_search.json'}")
    if daily_rows:
        print(f"saved {REPORTS_DIR / 'rolling_horizon_daily.csv'}")


if __name__ == "__main__":
    main()
