"""Validate the trained quantile models on the held-out test window.

Reports:
  Point accuracy of q50 (median forecast):
    - MAE, RMSE, MAPE, sMAPE, R^2, direction accuracy
  Quantile calibration:
    - Pinball loss per quantile (proper scoring rule)
    - Empirical coverage: fraction realized below q10 / inside [q10,q90] / above q90
  Economic value (the metric that matters for the deliverable):
    - Per-day perfect-foresight revenue, forecast-based realized revenue, capture ratio
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DEFAULT_BATTERY, PROCESSED_DIR, REPORTS_DIR
from src.forecaster import load_quantile_models, predict_interval
from src.scheduler import compute_low_confidence_mask, optimize, realized_revenue


TEST_DAYS = 7  # matches the held-out window in scripts/06_train_final.py


def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, alpha: float) -> float:
    diff = y_true - y_pred
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def main():
    df = pd.read_parquet(PROCESSED_DIR / "features.parquet")
    end = df.index.max()
    test_start = end - pd.Timedelta(days=TEST_DAYS)
    test_df = df.loc[df.index >= test_start].copy()
    print(f"Test window: {test_df.index.min()} -> {test_df.index.max()}  ({len(test_df)} rows)")

    models = load_quantile_models()
    if models is None:
        raise SystemExit("Quantile models missing. Run scripts/06_train_final.py first.")

    quantiles = predict_interval(models, test_df)
    quantiles.columns = ["q10", "q50", "q90"]
    y_true = test_df["dam_price_eur_mwh"].values
    q10, q50, q90 = quantiles["q10"].values, quantiles["q50"].values, quantiles["q90"].values

    # ---------- POINT ACCURACY (q50) ----------
    err = y_true - q50
    abs_err = np.abs(err)
    mae = float(np.mean(abs_err))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mean_abs_y = float(np.mean(np.abs(y_true)))
    mape = float(np.mean(abs_err / np.maximum(np.abs(y_true), 1.0)))  # guard tiny denoms
    smape = float(np.mean(2 * abs_err / np.maximum(np.abs(y_true) + np.abs(q50), 1.0)))
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    # Direction accuracy on 15-min changes
    dy = np.sign(np.diff(y_true))
    dq = np.sign(np.diff(q50))
    direction_acc = float(np.mean(dy == dq))

    point = {
        "MAE_eur_mwh": round(mae, 2),
        "RMSE_eur_mwh": round(rmse, 2),
        "MAPE_pct": round(mape * 100, 2),
        "sMAPE_pct": round(smape * 100, 2),
        "R2": round(r2, 3),
        "direction_acc_pct": round(direction_acc * 100, 1),
        "mean_realized_price_eur_mwh": round(float(y_true.mean()), 2),
        "n": int(len(y_true)),
    }

    # ---------- QUANTILE CALIBRATION ----------
    quant = {
        "pinball_q10": round(pinball_loss(y_true, q10, 0.10), 2),
        "pinball_q50": round(pinball_loss(y_true, q50, 0.50), 2),
        "pinball_q90": round(pinball_loss(y_true, q90, 0.90), 2),
        "coverage_below_q10_pct": round(float(np.mean(y_true < q10)) * 100, 1),
        "coverage_inside_q10_q90_pct": round(float(np.mean((y_true >= q10) & (y_true <= q90))) * 100, 1),
        "coverage_above_q90_pct": round(float(np.mean(y_true > q90)) * 100, 1),
        "mean_spread_eur_mwh": round(float(np.mean(q90 - q10)), 2),
        # Nominal coverage targets for reference: 10 / 80 / 10
    }

    # ---------- ECONOMIC VALUE (per-day backtest) ----------
    eco_rows = []
    days = pd.unique(test_df.index.normalize())
    for d in days:
        day_test = test_df.loc[test_df.index.normalize() == d]
        if len(day_test) < 90:
            continue
        realized = day_test["dam_price_eur_mwh"]
        day_q = quantiles.loc[day_test.index]
        try:
            perfect = optimize(realized, battery=DEFAULT_BATTERY)
            idle_mask = compute_low_confidence_mask(day_q["q10"], day_q["q90"], battery=DEFAULT_BATTERY)
            fcst = optimize(day_q["q50"], battery=DEFAULT_BATTERY, idle_mask=idle_mask)
            real_rev = realized_revenue(fcst, realized, battery=DEFAULT_BATTERY)
            eco_rows.append({
                "date": pd.Timestamp(d).date(),
                "perfect_eur": round(perfect.objective_eur, 2),
                "realized_eur": round(real_rev, 2),
                "capture_ratio": round(real_rev / perfect.objective_eur, 3) if perfect.objective_eur > 0 else 0.0,
                "idle_mtus": int(idle_mask.sum()),
                "throughput_mwh": round(float((fcst.charge_mw + fcst.discharge_mw).sum() * fcst.delta_h), 1),
            })
        except Exception as exc:
            print(f"  {d.date()} skipped: {exc}")

    eco = pd.DataFrame(eco_rows).set_index("date")
    eco_summary = {
        "days_tested": int(len(eco)),
        "mean_capture_ratio": round(float(eco["capture_ratio"].mean()), 3),
        "median_capture_ratio": round(float(eco["capture_ratio"].median()), 3),
        "min_capture_ratio": round(float(eco["capture_ratio"].min()), 3),
        "total_perfect_eur": round(float(eco["perfect_eur"].sum()), 2),
        "total_realized_eur": round(float(eco["realized_eur"].sum()), 2),
        "overall_capture_ratio": round(float(eco["realized_eur"].sum() / eco["perfect_eur"].sum()), 3),
        "mean_eur_per_day": round(float(eco["realized_eur"].mean()), 2),
        "mean_idle_mtus_per_day": round(float(eco["idle_mtus"].mean()), 1),
    }

    # ---------- OUTPUT ----------
    print("\n=== POINT ACCURACY (q50 vs realized) ===")
    for k, v in point.items():
        print(f"  {k:30s}  {v}")
    print("\n=== QUANTILE CALIBRATION (nominal 10 / 80 / 10) ===")
    for k, v in quant.items():
        print(f"  {k:30s}  {v}")
    print("\n=== ECONOMIC VALUE (battery scheduler backtest) ===")
    for k, v in eco_summary.items():
        print(f"  {k:30s}  {v}")
    print("\n=== PER-DAY CAPTURE RATIOS ===")
    print(eco.to_string())

    out = {
        "test_window_start": str(test_df.index.min()),
        "test_window_end": str(test_df.index.max()),
        "point_accuracy": point,
        "quantile_calibration": quant,
        "economic_value": eco_summary,
    }
    (REPORTS_DIR / "validation.json").write_text(json.dumps(out, indent=2, default=str))
    eco.to_csv(REPORTS_DIR / "validation_daily.csv")
    print(f"\nsaved {REPORTS_DIR / 'validation.json'}")
    print(f"saved {REPORTS_DIR / 'validation_daily.csv'}")


if __name__ == "__main__":
    main()
