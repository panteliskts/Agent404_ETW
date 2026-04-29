"""30-day held-out validation with proper retraining.

The production models in models/ saw the last 7 days. For a robust capture-ratio
claim we retrain q10/q50/q90 ON DATA STRICTLY BEFORE the 30-day test window,
then evaluate on those 30 days.

Outputs:
  reports/validation_30d.json         — full metrics
  reports/validation_30d_daily.csv    — per-day capture ratios
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

from config import DEFAULT_BATTERY, PROCESSED_DIR, REPORTS_DIR
from src.forecaster import (
    QUANTILE_ALPHAS,
    TARGET,
    _drop_target_leakage,
    predict_interval,
    train_quantile,
)
from src.scheduler import compute_low_confidence_mask, optimize, realized_revenue


TEST_DAYS = 30


def pinball_loss(y_true, y_pred, alpha):
    diff = y_true - y_pred
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def main():
    df = pd.read_parquet(PROCESSED_DIR / "features.parquet")
    df = df.dropna(subset=[TARGET]).sort_index()
    end = df.index.max()
    test_start = end - pd.Timedelta(days=TEST_DAYS)
    train_pool = df.loc[df.index < test_start].copy()
    test_df = df.loc[df.index >= test_start].copy()
    print(f"Train pool: {train_pool.index.min()} -> {train_pool.index.max()}  ({len(train_pool)} rows)")
    print(f"Test window: {test_df.index.min()} -> {test_df.index.max()}  ({len(test_df)} rows)")

    print("\n[TRAIN] q10 / q50 / q90 on train pool (no leakage from test window)")
    results = {}
    for alpha in QUANTILE_ALPHAS:
        key = f"q{int(alpha * 100):02d}"
        print(f"  training {key} ...")
        results[key] = train_quantile(train_pool, alpha=alpha, valid_days=30, test_days=7)

    print("\n[PREDICT] held-out 30-day window")
    quantiles = predict_interval(results, test_df)
    quantiles.columns = ["q10", "q50", "q90"]
    y_true = test_df[TARGET].values
    q10, q50, q90 = quantiles["q10"].values, quantiles["q50"].values, quantiles["q90"].values

    err = y_true - q50
    abs_err = np.abs(err)
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    point = {
        "MAE_eur_mwh": round(float(np.mean(abs_err)), 2),
        "RMSE_eur_mwh": round(float(np.sqrt(np.mean(err ** 2))), 2),
        "R2": round(1 - float(np.sum(err ** 2)) / ss_tot, 3) if ss_tot > 0 else None,
        "direction_acc_pct": round(float(np.mean(np.sign(np.diff(y_true)) == np.sign(np.diff(q50)))) * 100, 1),
        "mean_realized_price_eur_mwh": round(float(y_true.mean()), 2),
        "n": int(len(y_true)),
    }
    quant = {
        "pinball_q10": round(pinball_loss(y_true, q10, 0.10), 2),
        "pinball_q50": round(pinball_loss(y_true, q50, 0.50), 2),
        "pinball_q90": round(pinball_loss(y_true, q90, 0.90), 2),
        "coverage_below_q10_pct": round(float(np.mean(y_true < q10)) * 100, 1),
        "coverage_inside_pct": round(float(np.mean((y_true >= q10) & (y_true <= q90))) * 100, 1),
        "coverage_above_q90_pct": round(float(np.mean(y_true > q90)) * 100, 1),
        "mean_spread_eur_mwh": round(float(np.mean(q90 - q10)), 2),
    }

    print("\n[BACKTEST] daily scheduler, capture ratio vs perfect foresight")
    eco_rows = []
    for d in pd.unique(test_df.index.normalize()):
        day_test = test_df.loc[test_df.index.normalize() == d]
        if len(day_test) < 90:
            continue
        realized = day_test[TARGET]
        day_q = quantiles.loc[day_test.index]
        try:
            perfect = optimize(realized, battery=DEFAULT_BATTERY)
            idle_mask = compute_low_confidence_mask(day_q["q10"], day_q["q90"], battery=DEFAULT_BATTERY)
            fcst = optimize(day_q["q50"], battery=DEFAULT_BATTERY, idle_mask=idle_mask)
            real_rev = realized_revenue(fcst, realized, battery=DEFAULT_BATTERY)
            charge_mwh = float(fcst.charge_mw.sum() * fcst.delta_h)
            disch_mwh = float(fcst.discharge_mw.sum() * fcst.delta_h)
            eco_rows.append({
                "date": pd.Timestamp(d).date(),
                "perfect_eur": round(perfect.objective_eur, 2),
                "realized_eur": round(real_rev, 2),
                "capture_ratio": round(real_rev / perfect.objective_eur, 3) if perfect.objective_eur > 0 else 0.0,
                "buy_mwh": round(charge_mwh, 1),
                "sell_mwh": round(disch_mwh, 1),
                "idle_mtus": int(idle_mask.sum()),
            })
        except Exception as exc:
            print(f"  {d.date()} skipped: {exc}")

    eco = pd.DataFrame(eco_rows).set_index("date")
    eco_summary = {
        "days_tested": int(len(eco)),
        "mean_capture_ratio": round(float(eco["capture_ratio"].mean()), 3),
        "median_capture_ratio": round(float(eco["capture_ratio"].median()), 3),
        "min_capture_ratio": round(float(eco["capture_ratio"].min()), 3),
        "max_capture_ratio": round(float(eco["capture_ratio"].max()), 3),
        "std_capture_ratio": round(float(eco["capture_ratio"].std()), 3),
        "p10_capture_ratio": round(float(eco["capture_ratio"].quantile(0.10)), 3),
        "p90_capture_ratio": round(float(eco["capture_ratio"].quantile(0.90)), 3),
        "total_perfect_eur": round(float(eco["perfect_eur"].sum()), 2),
        "total_realized_eur": round(float(eco["realized_eur"].sum()), 2),
        "overall_capture_ratio": round(float(eco["realized_eur"].sum() / eco["perfect_eur"].sum()), 3),
        "mean_eur_per_day": round(float(eco["realized_eur"].mean()), 2),
        "total_buy_mwh": round(float(eco["buy_mwh"].sum()), 1),
        "total_sell_mwh": round(float(eco["sell_mwh"].sum()), 1),
        "mean_idle_mtus_per_day": round(float(eco["idle_mtus"].mean()), 1),
    }

    print("\n=== POINT ACCURACY ===")
    for k, v in point.items(): print(f"  {k:32s}  {v}")
    print("\n=== QUANTILE CALIBRATION ===")
    for k, v in quant.items(): print(f"  {k:32s}  {v}")
    print("\n=== ECONOMIC VALUE ===")
    for k, v in eco_summary.items(): print(f"  {k:32s}  {v}")

    out = {
        "test_window_start": str(test_df.index.min()),
        "test_window_end": str(test_df.index.max()),
        "test_days": int(len(eco)),
        "n_train_rows": int(len(train_pool)),
        "point_accuracy": point,
        "quantile_calibration": quant,
        "economic_value": eco_summary,
    }
    (REPORTS_DIR / "validation_30d.json").write_text(json.dumps(out, indent=2, default=str))
    eco.to_csv(REPORTS_DIR / "validation_30d_daily.csv")
    print(f"\nsaved {REPORTS_DIR / 'validation_30d.json'}")
    print(f"saved {REPORTS_DIR / 'validation_30d_daily.csv'}")


if __name__ == "__main__":
    main()
