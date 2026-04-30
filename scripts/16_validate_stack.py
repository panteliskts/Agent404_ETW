"""30-day held-out validation of the full forecasting + dispatch stack.

Pipeline
--------
  Features:
    - features_realistic.parquet (no leaky lags)
    - + Greek holidays, solar geometry, collapse-risk (added in Phase 1)

  Forecasts (LightGBM on realistic features):
    - q05 / q50 / q95 quantile heads
    - Recency weighting (half-life 90 d) + seasonal Gaussian (σ 30 d)
    - Economic-impact weight on q50 (∝ |price - daily_mean|): forces the
      median forecast to fit within-day spreads, not just MAE-minimising
      level. This is the most direct lever on capture ratio.

  Dispatch:
    - Idle-mask spread threshold tuned on the *validation* window
      (last 30 days of the train pool), then frozen for the test window.
    - Soft cyclic SoC (cyclic_penalty > 0): lets the optimiser end the day
      slightly off the starting SoC when the marginal value exceeds the
      penalty — frees revenue on volatile days.

Outputs:
  reports/validation_30d.json
  reports/validation_30d_daily.csv
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
RECENCY_HALFLIFE = 90.0
SEASONAL_SIGMA = 30.0
ECONOMIC_WEIGHT_SCALE = 25.0  # EUR/MWh — typical within-day std

# Soft cyclic SoC: penalty (€/MWh) on terminal-SoC deviation. Set >0 to allow
# end-of-day SoC drift when revenue justifies it. 0 = hard equality (default).
SOFT_CYCLIC_PENALTY = 3.0  # tuned on validation sweep; ≥3 saturates

# Threshold percentiles to evaluate when tuning the spread-based idle mask.
SPREAD_PCT_GRID = [0, 5, 10, 15, 20, 25, 30, 40]


def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, alpha: float) -> float:
    diff = y_true - y_pred
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def _tuned_battery():
    """DEFAULT_BATTERY with soft cyclic SoC enabled."""
    return replace(DEFAULT_BATTERY, cyclic_penalty=SOFT_CYCLIC_PENALTY)


def daily_backtest(
    pred: pd.Series,
    realized: pd.Series,
    idle_mask: pd.Series | None = None,
    battery=None,
) -> pd.DataFrame:
    if battery is None:
        battery = _tuned_battery()
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
                "buy_mwh": float(sched.charge_mw.sum() * sched.delta_h),
                "sell_mwh": float(sched.discharge_mw.sum() * sched.delta_h),
                "idle_mtus": int(im.sum()) if im is not None else 0,
            })
        except Exception as exc:
            print(f"  {d.date()} skipped: {exc}")
    return pd.DataFrame(rows).set_index("date")


def tune_idle_threshold(
    valid_pred: pd.Series, valid_real: pd.Series, valid_q05: pd.Series, valid_q95: pd.Series,
    battery,
) -> float:
    """Pick the spread-percentile threshold that maximises validation revenue."""
    spreads = (valid_q95 - valid_q05).values
    best_thr, best_rev = 0.0, -np.inf
    for pct in SPREAD_PCT_GRID:
        thr = float(np.percentile(spreads, pct)) if pct > 0 else 0.0
        idle = pd.Series((valid_q95 - valid_q05) < thr, index=valid_pred.index)
        bt = daily_backtest(valid_pred, valid_real, idle_mask=idle, battery=battery)
        rev = float(bt["realized_eur"].sum()) if len(bt) else -np.inf
        if rev > best_rev:
            best_rev, best_thr = rev, thr
    return best_thr


def main():
    # features_clean.parquet: strictly gate-close-feasible. All next-day
    # market-clearing outputs (gen_lignite_mw, load_hv_mw, volume_mainland_mwh,
    # res_share, ...) are replaced by their 24h lag. features_realistic still
    # contained those raw and was leaky for next-day forecasting.
    df = pd.read_parquet(PROCESSED_DIR / "features_clean.parquet")
    df = df.dropna(subset=[TARGET]).sort_index()
    end = df.index.max()
    test_start = end - pd.Timedelta(days=TEST_DAYS)
    valid_start = test_start - pd.Timedelta(days=30)
    train_pool = df.loc[df.index < test_start].copy()
    valid_df = df.loc[(df.index >= valid_start) & (df.index < test_start)].copy()
    test_df = df.loc[df.index >= test_start].copy()
    print(f"Train pool: {train_pool.index.min()} -> {train_pool.index.max()}  ({len(train_pool)} rows)")
    print(f"Valid:      {valid_df.index.min()} -> {valid_df.index.max()}  ({len(valid_df)} rows)")
    print(f"Test:       {test_df.index.min()} -> {test_df.index.max()}  ({len(test_df)} rows)")

    # ── TRAIN QUANTILES (q05/q95 standard, q50 ensemble with economic weighting) ─────
    print("\n[TRAIN] q05 / q50 (ensemble of 3) / q95")
    quant_models = {}
    for alpha in [0.05, 0.95]:
        key = f"q{int(alpha * 100):02d}"
        print(f"  training {key} (alpha={alpha}) ...")
        quant_models[key] = train_quantile(
            train_pool, alpha=alpha, valid_days=30, test_days=7,
            sample_weights=True,
            recency_halflife_days=RECENCY_HALFLIFE,
            seasonal_sigma_days=SEASONAL_SIGMA,
        )

    # q50 ensemble: 3 boosters with different bagging seeds. Bagging reduces
    # variance of the median forecast on volatile days — the bottom-quartile
    # capture-ratio days (where the mean lives) benefit most.
    print("  training q50 ensemble (3 seeds, economic weighted) ...")
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

    def _ensemble_predict(models, frame):
        preds = [
            pd.Series(m.model.predict(frame[m.feature_cols], num_iteration=m.model.best_iteration),
                      index=frame.index)
            for m in models
        ]
        return pd.concat(preds, axis=1).mean(axis=1)

    # ── PREDICT BOTH WINDOWS ────────────────────────────────────────────────
    valid_q = predict_interval({"q05": quant_models["q05"], "q95": quant_models["q95"]}, valid_df)
    valid_q.columns = ["q05", "q95"]
    valid_q["q50"] = _ensemble_predict(q50_seeds, valid_df)
    valid_q = valid_q[["q05", "q50", "q95"]]

    test_q = predict_interval({"q05": quant_models["q05"], "q95": quant_models["q95"]}, test_df)
    test_q.columns = ["q05", "q95"]
    test_q["q50"] = _ensemble_predict(q50_seeds, test_df)
    test_q = test_q[["q05", "q50", "q95"]]

    # Conformal calibration: shift each test quantile by the empirical
    # residual quantile measured on the validation window. Brings empirical
    # coverage from ~21/70/9 to closer to the nominal 5/90/5 — improves
    # idle-mask tuning and any spread-aware decision.
    test_q["q05"] = conformal_calibrate(valid_q["q05"], valid_df[TARGET], test_q["q05"], alpha=0.05)
    test_q["q50"] = conformal_calibrate(valid_q["q50"], valid_df[TARGET], test_q["q50"], alpha=0.50)
    test_q["q95"] = conformal_calibrate(valid_q["q95"], valid_df[TARGET], test_q["q95"], alpha=0.95)

    # Scenario blend: q50 carries most of the level; q05/q95 contribute spread
    # info that q50's MAE-style loss otherwise discards. The 0.6/0.2/0.2 mix
    # was the validation-sweep optimum.
    valid_disp = 0.6 * valid_q["q50"] + 0.2 * valid_q["q05"] + 0.2 * valid_q["q95"]
    test_disp  = 0.6 * test_q["q50"]  + 0.2 * test_q["q05"]  + 0.2 * test_q["q95"]

    # ── TUNE IDLE-MASK ON VALIDATION ────────────────────────────────────────
    print("\n[TUNE] idle-mask spread threshold on validation window")
    battery = _tuned_battery()
    thr = tune_idle_threshold(
        valid_disp, valid_df[TARGET], valid_q["q05"], valid_q["q95"],
        battery=battery,
    )
    print(f"  picked threshold: {thr:.2f} EUR/MWh")

    # ── BACKTEST TEST WINDOW ────────────────────────────────────────────────
    print("\n[BACKTEST] test window (with tuned idle mask)")
    test_idle = pd.Series((test_q["q95"] - test_q["q05"]) < thr, index=test_q.index)
    test_bt = daily_backtest(test_disp, test_df[TARGET], idle_mask=test_idle, battery=battery)
    test_bt = test_bt.round(2)

    # ── METRICS ─────────────────────────────────────────────────────────────
    y_true = test_df[TARGET].values
    q05_v, q50_v, q95_v = test_q["q05"].values, test_q["q50"].values, test_q["q95"].values
    disp_v = test_disp.values
    err = y_true - q50_v
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    point = {
        "MAE_eur_mwh": round(float(np.mean(np.abs(err))), 2),
        "RMSE_eur_mwh": round(float(np.sqrt(np.mean(err ** 2))), 2),
        "R2": round(1 - float(np.sum(err ** 2)) / ss_tot, 3) if ss_tot > 0 else None,
        "direction_acc_pct": round(float(np.mean(np.sign(np.diff(y_true)) == np.sign(np.diff(q50_v)))) * 100, 1),
        "mean_realized_price_eur_mwh": round(float(y_true.mean()), 2),
        "n": int(len(y_true)),
    }
    quant = {
        "pinball_q05": round(pinball_loss(y_true, q05_v, 0.05), 2),
        "pinball_q50": round(pinball_loss(y_true, q50_v, 0.50), 2),
        "pinball_q95": round(pinball_loss(y_true, q95_v, 0.95), 2),
        "coverage_below_q05_pct": round(float(np.mean(y_true < q05_v)) * 100, 1),
        "coverage_inside_pct": round(float(np.mean((y_true >= q05_v) & (y_true <= q95_v))) * 100, 1),
        "coverage_above_q95_pct": round(float(np.mean(y_true > q95_v)) * 100, 1),
        "mean_spread_eur_mwh": round(float(np.mean(q95_v - q05_v)), 2),
    }
    eco = {
        "days_tested": int(len(test_bt)),
        "mean_capture_ratio": round(float(test_bt["capture_ratio"].mean()), 3),
        "median_capture_ratio": round(float(test_bt["capture_ratio"].median()), 3),
        "min_capture_ratio": round(float(test_bt["capture_ratio"].min()), 3),
        "max_capture_ratio": round(float(test_bt["capture_ratio"].max()), 3),
        "std_capture_ratio": round(float(test_bt["capture_ratio"].std()), 3),
        "p10_capture_ratio": round(float(test_bt["capture_ratio"].quantile(0.10)), 3),
        "p90_capture_ratio": round(float(test_bt["capture_ratio"].quantile(0.90)), 3),
        "total_perfect_eur": round(float(test_bt["perfect_eur"].sum()), 2),
        "total_realized_eur": round(float(test_bt["realized_eur"].sum()), 2),
        "overall_capture_ratio": round(float(test_bt["realized_eur"].sum() / test_bt["perfect_eur"].sum()), 3),
        "mean_eur_per_day": round(float(test_bt["realized_eur"].mean()), 2),
        "total_buy_mwh": round(float(test_bt["buy_mwh"].sum()), 1),
        "total_sell_mwh": round(float(test_bt["sell_mwh"].sum()), 1),
        "mean_idle_mtus_per_day": round(float(test_bt["idle_mtus"].mean()), 1),
        "idle_threshold_eur_mwh": round(thr, 2),
        "soft_cyclic_penalty": SOFT_CYCLIC_PENALTY,
    }

    print("\n=== POINT ACCURACY (q50) ===")
    for k, v in point.items(): print(f"  {k:32s}  {v}")
    print("\n=== QUANTILE CALIBRATION ===")
    for k, v in quant.items(): print(f"  {k:32s}  {v}")
    print("\n=== ECONOMIC VALUE ===")
    for k, v in eco.items(): print(f"  {k:32s}  {v}")
    print("\n=== PER-DAY CAPTURE (worst 5) ===")
    print(test_bt.sort_values("capture_ratio").head(5).to_string())

    out = {
        "test_window_start": str(test_df.index.min()),
        "test_window_end": str(test_df.index.max()),
        "test_days": int(len(test_bt)),
        "n_train_rows": int(len(train_pool)),
        "config": {
            "recency_halflife_days": RECENCY_HALFLIFE,
            "seasonal_sigma_days": SEASONAL_SIGMA,
            "economic_weight_scale": ECONOMIC_WEIGHT_SCALE,
            "soft_cyclic_penalty": SOFT_CYCLIC_PENALTY,
            "spread_pct_grid": SPREAD_PCT_GRID,
        },
        "point_accuracy": point,
        "quantile_calibration": quant,
        "economic_value": eco,
    }
    (REPORTS_DIR / "validation_30d.json").write_text(json.dumps(out, indent=2, default=str))
    test_bt.to_csv(REPORTS_DIR / "validation_30d_daily.csv")
    print(f"\nsaved {REPORTS_DIR / 'validation_30d.json'}")


if __name__ == "__main__":
    main()
