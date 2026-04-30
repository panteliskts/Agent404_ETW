"""Grid search over MPC D+1 discount factor (alpha).

Trains each fold ONCE, then sweeps alpha values at dispatch time — no redundant
retraining.  Compares all alpha values + the single-day baseline on the same
30-day walk-forward window.

Outputs:
  reports/mpc_alpha_search.json    -- per-alpha summary table
  reports/mpc_alpha_daily.csv      -- per-day capture for every alpha (wide format)
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
from src.scheduler import optimize, optimize_multiday, realized_revenue

TEST_DAYS   = 30
WEEK_DAYS   = 7
RECENCY_HALFLIFE     = 90.0
SEASONAL_SIGMA       = 30.0
ECONOMIC_WEIGHT_SCALE = 25.0
SOFT_CYCLIC_PENALTY  = 3.0
SPREAD_PCT_GRID = [0, 5, 10, 15, 20, 25, 30, 40]

# alpha=0 means single-day baseline replicated via this script for consistency
ALPHA_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def _battery():
    return replace(DEFAULT_BATTERY, cyclic_penalty=SOFT_CYCLIC_PENALTY)


def dispatch_day(d, days, unique_days, i, pred_full, idle_mask, battery, alpha):
    m0 = days == d
    if m0.sum() < 90:
        return None
    if alpha > 0.0 and i + 1 < len(unique_days):
        d1 = unique_days[i + 1]
        m1 = days == d1
        im0 = idle_mask[m0] if idle_mask is not None else None
        im1 = idle_mask[m1] if idle_mask is not None else None
        return optimize_multiday(
            pred_full[m0], pred_full[m1],
            battery=battery, idle_mask_d0=im0, idle_mask_d1=im1,
            d1_discount=alpha,
        )
    else:
        im = idle_mask[m0] if idle_mask is not None else None
        return optimize(pred_full[m0], battery=battery, idle_mask=im)


def backtest_alpha(pred_full, realized, idle_mask, battery, alpha):
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
            sched = dispatch_day(d, days, unique_days, i, pred_full, idle_mask, battery, alpha)
            if sched is None:
                continue
            rev = realized_revenue(sched, real_d, battery=battery)
            rows.append({
                "date": pd.Timestamp(d).date(),
                "perfect_eur": perf.objective_eur,
                "realized_eur": rev,
                "capture_ratio": rev / perf.objective_eur if perf.objective_eur > 0 else 0.0,
            })
        except Exception as exc:
            print(f"    alpha={alpha} {d.date()} skipped: {exc}")
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def tune_idle_threshold(disp, real, q05, q95, battery):
    spreads = (q95 - q05).values
    best_thr, best_rev = 0.0, -np.inf
    # Use alpha=0 (single-day) for threshold tuning — keeps it identical to baseline
    for pct in SPREAD_PCT_GRID:
        thr = float(np.percentile(spreads, pct)) if pct > 0 else 0.0
        idle = pd.Series((q95 - q05) < thr, index=disp.index)
        bt = backtest_alpha(disp, real, idle, battery, alpha=0.0)
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
    """Train once, return (week_disp, week_idle, week_realized) for all alpha sweeps."""
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

    valid_q = predict_interval(q_tail, valid_df); valid_q.columns = ["q05", "q95"]
    valid_q["q50"] = _ensemble_predict(q50_seeds, valid_df)
    valid_q = valid_q[["q05", "q50", "q95"]]
    week_q = predict_interval(q_tail, week_df); week_q.columns = ["q05", "q95"]
    week_q["q50"] = _ensemble_predict(q50_seeds, week_df)
    week_q = week_q[["q05", "q50", "q95"]]

    for c, a in [("q05", 0.05), ("q50", 0.50), ("q95", 0.95)]:
        week_q[c]  = conformal_calibrate(valid_q[c],  valid_df[TARGET], week_q[c],  alpha=a)

    valid_disp = 0.6 * valid_q["q50"] + 0.2 * valid_q["q05"] + 0.2 * valid_q["q95"]
    week_disp  = 0.6 * week_q["q50"]  + 0.2 * week_q["q05"]  + 0.2 * week_q["q95"]

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
    fold_ends   = [s + pd.Timedelta(days=WEEK_DAYS) for s in fold_starts]
    test_end = end + pd.Timedelta(seconds=1)
    fold_ends[-1] = min(fold_ends[-1], test_end)

    # Collect per-fold dispatch data, then sweep alphas
    fold_data = []
    for i, (fstart, fend) in enumerate(zip(fold_starts, fold_ends)):
        if fstart >= test_end or (fend - fstart).total_seconds() < 86400:
            continue
        train_pool = df.loc[df.index < fstart].copy()
        valid_df   = df.loc[(df.index >= fstart - pd.Timedelta(days=14)) &
                             (df.index < fstart)].copy()
        week_df    = df.loc[(df.index >= fstart) & (df.index < fend)].copy()
        if len(week_df) < 96:
            continue
        print(f"\n[FOLD {i}] train<{fstart.date()}  week={fstart.date()}-{fend.date()}")
        week_disp, week_idle, week_real, thr = run_fold(train_pool, valid_df, week_df)
        fold_data.append((week_disp, week_idle, week_real, thr))
        print(f"  idle_threshold={thr:.2f}")

    # Sweep alphas — collect per-fold weekly results for each alpha
    bat = _battery()
    alpha_results  = {}   # alpha -> 30-day DataFrame
    weekly_results = {}   # alpha -> list of per-fold dicts

    print("\n=== ALPHA SWEEP (weekly breakdown) ===")
    header = f"{'alpha':>6}  " + "  ".join(f"W{j:<7}" for j in range(len(fold_data))) + "  MEAN    TOTAL_EUR   DELTA_EUR"
    print(header)

    baseline_total = None
    for alpha in ALPHA_GRID:
        all_bt = []
        fold_stats = []
        for fi, (week_disp, week_idle, week_real, thr) in enumerate(fold_data):
            bt = backtest_alpha(week_disp, week_real, week_idle, bat, alpha)
            if len(bt):
                all_bt.append(bt)
                fold_stats.append({
                    "fold": fi,
                    "mean_capture": round(float(bt["capture_ratio"].mean()), 4),
                    "overall_capture": round(float(bt["realized_eur"].sum() / max(bt["perfect_eur"].sum(), 1e-9)), 4),
                    "realized_eur": round(float(bt["realized_eur"].sum()), 2),
                    "perfect_eur":  round(float(bt["perfect_eur"].sum()), 2),
                    "idle_threshold": thr,
                })
            else:
                fold_stats.append({"fold": fi, "mean_capture": float("nan"), "realized_eur": 0})

        full = pd.concat(all_bt) if all_bt else pd.DataFrame(columns=["capture_ratio","realized_eur","perfect_eur"])
        alpha_results[alpha]  = full
        weekly_results[alpha] = fold_stats

        total_real = float(full["realized_eur"].sum()) if len(full) else 0.0
        mean_cap   = float(full["capture_ratio"].mean()) if len(full) else float("nan")
        if alpha == 0.0:
            baseline_total = total_real
        delta = total_real - (baseline_total or 0.0)

        week_cols = "  ".join(f"{fs['mean_capture']:.4f}" for fs in fold_stats)
        print(f"  {alpha:>4.1f}  {week_cols}  {mean_cap:.4f}  {total_real:>10,.0f}  {delta:>+10,.0f}")

    # 30-day summary table
    summary_rows = []
    for alpha in ALPHA_GRID:
        full = alpha_results[alpha]
        total_real = float(full["realized_eur"].sum()) if len(full) else 0.0
        summary_rows.append({
            "alpha": alpha,
            "mean_capture":     round(float(full["capture_ratio"].mean()), 4) if len(full) else None,
            "median_capture":   round(float(full["capture_ratio"].median()), 4) if len(full) else None,
            "min_capture":      round(float(full["capture_ratio"].min()), 4) if len(full) else None,
            "p10_capture":      round(float(full["capture_ratio"].quantile(0.10)), 4) if len(full) else None,
            "overall_capture":  round(float(full["realized_eur"].sum() / max(full["perfect_eur"].sum(), 1e-9)), 4) if len(full) else None,
            "std_capture":      round(float(full["capture_ratio"].std()), 4) if len(full) else None,
            "total_realized_eur": round(total_real, 2),
            "delta_eur_vs_baseline": round(total_real - (baseline_total or 0), 2),
            "mean_eur_per_day": round(float(full["realized_eur"].mean()), 2) if len(full) else None,
            "weekly_breakdown": weekly_results[alpha],
        })

    summary_df = pd.DataFrame([{k: v for k, v in r.items() if k != "weekly_breakdown"} for r in summary_rows])
    print("\n=== 30-DAY AGGREGATE TABLE ===")
    print(summary_df.to_string(index=False))

    best = summary_df.loc[summary_df["mean_capture"].idxmax()]
    print(f"\nBest alpha by mean capture : {best['alpha']}  ({best['mean_capture']:.4f})")
    best_eur = summary_df.loc[summary_df["total_realized_eur"].idxmax()]
    print(f"Best alpha by total EUR    : {best_eur['alpha']}  ({best_eur['total_realized_eur']:,.0f})")

    # Save
    (REPORTS_DIR / "mpc_alpha_search.json").write_text(
        json.dumps({
            "summary": summary_rows,
            "best_alpha_mean_capture": float(best["alpha"]),
            "best_alpha_total_eur": float(best_eur["alpha"]),
        }, indent=2)
    )
    # Weekly breakdown CSV: rows = (alpha, fold), cols = stats
    weekly_rows = []
    for alpha in ALPHA_GRID:
        for fs in weekly_results[alpha]:
            weekly_rows.append({"alpha": alpha, **fs})
    pd.DataFrame(weekly_rows).to_csv(REPORTS_DIR / "mpc_alpha_weekly.csv", index=False)

    print(f"\nsaved {REPORTS_DIR / 'mpc_alpha_search.json'}")
    print(f"saved {REPORTS_DIR / 'mpc_alpha_weekly.csv'}")


if __name__ == "__main__":
    main()
