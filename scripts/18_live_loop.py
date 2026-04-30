"""Live operational loop: data refresh -> forecast -> dispatch -> evaluate.

Loop architecture
-----------------
The Greek DAM clears once a day at ~12:00 D-1, so the *forecast* cycle is
daily, not 15-minute. The 15-minute cadence is for INGESTION (HEnEx publishes
ResultsSummary after delivery, ENTSO-E publishes load/RES forecasts hourly,
weather forecasts refresh ~hourly) and for INTRADAY MARKET signals.

Tick (every 15 min or on cron):
  1. Fetch any new ResultsSummary / ENTSO-E / weather data since last tick.
  2. Append to raw parquets (idempotent, dedup on index).
  3. Rebuild features (incremental).
  4. If we already have a forecast for today and yesterday's results are in,
     compute realised capture for yesterday and append to a rolling KPI log.

Forecast cycle (run at ~11:00 D-1):
  1. Run inference with the current production model on D-day's 96 MTUs.
  2. Submit DAM bids based on that forecast (or hand off to the bidding desk).
  3. Persist forecast for later evaluation.

Retrain cycle (weekly, e.g. Friday 14:00):
  1. Train q05/q50/q95 + q50 ensemble + spike-likelihood-aware features.
  2. Run walk-forward backtest on the latest 30 days.
  3. If new model beats the deployed model on rolling capture, promote it.

This script implements the tick + forecast cycle. Retraining is via
`scripts/06_train_final.py` which is wired to features_clean.parquet.

Usage:
  python scripts/18_live_loop.py --tick           # one tick (data refresh + KPI update)
  python scripts/18_live_loop.py --forecast 2026-05-01   # forecast a specific day
  python scripts/18_live_loop.py --serve          # run continuously, ticking every 15 min
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from copy import replace
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import DEFAULT_BATTERY, GR_TIMEZONE, PROCESSED_DIR, RAW_DIR, REPORTS_DIR
from src.data import fuels, henex, weather
from src import features as F
from src.forecaster import (
    QUANTILE_ALPHAS,
    TARGET,
    conformal_calibrate,
    predict_interval,
    train_quantile,
)
from src.scheduler import optimize, realized_revenue


KPI_LOG = REPORTS_DIR / "live_kpi_log.csv"
FORECAST_LOG_DIR = REPORTS_DIR / "forecasts"
FORECAST_LOG_DIR.mkdir(exist_ok=True)


# ── Data layer ─────────────────────────────────────────────────────────────
def refresh_data(cheap_only: bool = True) -> dict:
    """Fetch any new data since last tick. Returns counts of new rows ingested.

    cheap_only: if True, only refresh the fast / free sources (HEnEx + weather)
    each tick. ENTSO-E (rate-limited) and fuels (yfinance) are refreshed by
    daily cron, not per-tick.
    """
    today = datetime.now(tz=pd.Timestamp.now(tz=GR_TIMEZONE).tz)
    end = today.strftime("%Y-%m-%d")
    counts = {}

    # HEnEx: scrapes the live page; ResultsSummary becomes available next day.
    try:
        before = _henex_row_count()
        henex.save([today.year])
        counts["henex_new_rows"] = _henex_row_count() - before
    except Exception as exc:
        counts["henex_error"] = str(exc)[:120]

    # Weather forecast (1-7 days ahead)
    try:
        before = _count(RAW_DIR.glob("weather_*.parquet"))
        weather.save("2024-01-01", end)  # archive endpoint covers historical+today
        counts["weather_refreshed"] = True
    except Exception as exc:
        counts["weather_error"] = str(exc)[:120]

    if not cheap_only:
        try:
            from src.data import entsoe_client
            entsoe_client.save_all("2024-01-01", end)
            counts["entsoe_refreshed"] = True
        except Exception as exc:
            counts["entsoe_error"] = str(exc)[:120]
        try:
            fuels.save("2024-01-01", end)
            counts["fuels_refreshed"] = True
        except Exception as exc:
            counts["fuels_error"] = str(exc)[:120]

    # Rebuild processed features
    try:
        F.save()
        counts["features_rebuilt"] = True
    except Exception as exc:
        counts["features_error"] = str(exc)[:120]
    return counts


def _count(it):
    return sum(1 for _ in it)


def _henex_row_count() -> int:
    files = list(RAW_DIR.glob("henex_results*.parquet"))
    if not files:
        return 0
    return int(len(pd.read_parquet(files[-1])))


# ── Forecast cycle ─────────────────────────────────────────────────────────
def forecast_day(target_date: pd.Timestamp, retrain: bool = True) -> pd.DataFrame:
    """Forecast 96 MTUs for `target_date` using the full stack.

    If retrain=True, models are fit fresh on data strictly before target_date
    (production behaviour). If False, loads pre-saved models from models/.
    """
    df = pd.read_parquet(PROCESSED_DIR / "features_clean.parquet").dropna(subset=[TARGET]).sort_index()
    target_date = pd.Timestamp(target_date).tz_localize(GR_TIMEZONE) if pd.Timestamp(target_date).tzinfo is None else pd.Timestamp(target_date)
    target_date = target_date.normalize()

    train_pool = df.loc[df.index < target_date].copy()
    valid_df = df.loc[(df.index >= target_date - pd.Timedelta(days=30)) & (df.index < target_date)].copy()
    test_df = df.loc[(df.index >= target_date) & (df.index < target_date + pd.Timedelta(days=1))].copy()
    if len(test_df) < 90:
        raise RuntimeError(f"feature row count too low for {target_date.date()}: {len(test_df)}")

    if retrain:
        quant = {}
        for a in [0.05, 0.95]:
            quant[f"q{int(a*100):02d}"] = train_quantile(
                train_pool, alpha=a, valid_days=30, test_days=7,
                sample_weights=True, recency_halflife_days=90, seasonal_sigma_days=30,
            )
        seeds = []
        for seed in [42, 7, 1337]:
            seeds.append(train_quantile(
                train_pool, alpha=0.5, valid_days=30, test_days=7,
                sample_weights=True, recency_halflife_days=90, seasonal_sigma_days=30,
                economic_weight=True, economic_weight_scale=25,
                hparams=dict(learning_rate=0.05, num_leaves=63, min_data_in_leaf=30,
                             feature_fraction=0.85, bagging_fraction=0.85,
                             bagging_seed=seed, feature_fraction_seed=seed),
            ))
        def ens(frame):
            return pd.concat([
                pd.Series(m.model.predict(frame[m.feature_cols], num_iteration=m.model.best_iteration),
                          index=frame.index)
                for m in seeds
            ], axis=1).mean(axis=1)
        valid_q = predict_interval(quant, valid_df); valid_q.columns = ["q05", "q95"]; valid_q["q50"] = ens(valid_df)
        test_q  = predict_interval(quant, test_df);  test_q.columns  = ["q05", "q95"]; test_q["q50"]  = ens(test_df)
        for c, a in [("q05", 0.05), ("q50", 0.50), ("q95", 0.95)]:
            test_q[c] = conformal_calibrate(valid_q[c], valid_df[TARGET], test_q[c], alpha=a)
    else:
        from src.forecaster import load_quantile_models
        m = load_quantile_models()
        if m is None:
            raise RuntimeError("Saved quantile models missing; pass retrain=True or run scripts/06_train_final.py")
        test_q = predict_interval(m, test_df); test_q.columns = ["q05", "q50", "q95"]

    test_q["dispatch"] = 0.6 * test_q["q50"] + 0.2 * test_q["q05"] + 0.2 * test_q["q95"]
    bat = replace(DEFAULT_BATTERY, cyclic_penalty=3.0)
    sched = optimize(test_q["dispatch"], battery=bat)
    f = sched.to_frame()
    f["q05"] = test_q["q05"]; f["q50"] = test_q["q50"]; f["q95"] = test_q["q95"]
    f["dispatch_price"] = test_q["dispatch"]
    f["spread"] = f["q95"] - f["q05"]

    # Persist
    out = FORECAST_LOG_DIR / f"forecast_{target_date.date()}.csv"
    f.to_csv(out)
    print(f"saved {out}")
    return f


# ── Evaluation cycle ───────────────────────────────────────────────────────
def evaluate_yesterday() -> dict | None:
    """If yesterday's forecast exists and yesterday's prices have been ingested,
    compute realised capture and append to KPI log."""
    today = pd.Timestamp.now(tz=GR_TIMEZONE).normalize()
    yesterday = today - pd.Timedelta(days=1)
    fcst_path = FORECAST_LOG_DIR / f"forecast_{yesterday.date()}.csv"
    if not fcst_path.exists():
        return None
    fcst = pd.read_csv(fcst_path, index_col=0, parse_dates=True)
    if fcst.index.tz is None:
        fcst.index = fcst.index.tz_localize(GR_TIMEZONE)

    df = pd.read_parquet(PROCESSED_DIR / "features_clean.parquet").dropna(subset=[TARGET])
    realised = df.loc[(df.index >= yesterday) & (df.index < today), TARGET]
    if len(realised) < 90:
        return None  # not yet published

    realised = realised.reindex(fcst.index)
    if realised.isna().mean() > 0.1:
        return None
    bat = replace(DEFAULT_BATTERY, cyclic_penalty=3.0)
    perf = optimize(realised, battery=bat)
    sched = optimize(fcst["dispatch_price"], battery=bat)
    real_rev = realized_revenue(sched, realised, battery=bat)
    cap = real_rev / perf.objective_eur if perf.objective_eur > 0 else 0.0

    rec = {
        "date": str(yesterday.date()),
        "perfect_eur": round(perf.objective_eur, 2),
        "realized_eur": round(real_rev, 2),
        "capture_ratio": round(cap, 3),
        "spread_mean": round(float(fcst["spread"].mean()), 2),
        "evaluated_at": pd.Timestamp.now(tz=GR_TIMEZONE).isoformat(),
    }
    df_log = pd.DataFrame([rec])
    if KPI_LOG.exists():
        existing = pd.read_csv(KPI_LOG)
        if rec["date"] in set(existing["date"].astype(str)):
            return rec  # already logged
        df_log = pd.concat([existing, df_log], ignore_index=True)
    df_log.to_csv(KPI_LOG, index=False)

    # Rolling 30-day mean
    if len(df_log) >= 5:
        recent = df_log.tail(30)
        print(f"[KPI] yesterday capture={cap:.3f}, rolling-30d mean={recent['capture_ratio'].mean():.3f}")
    return rec


# ── Tick ───────────────────────────────────────────────────────────────────
def tick(forecast_target_date: str | None = None, full_refresh: bool = False) -> dict:
    """One operational tick: refresh, evaluate yesterday, optionally forecast next day."""
    out = {"ts": pd.Timestamp.now(tz=GR_TIMEZONE).isoformat()}
    out["refresh"] = refresh_data(cheap_only=not full_refresh)
    out["eval_yesterday"] = evaluate_yesterday()
    if forecast_target_date:
        forecast_day(forecast_target_date)
        out["forecast_target"] = forecast_target_date
    return out


def serve(interval_minutes: int = 15, daily_forecast_hour: int = 11):
    """Run forever, tick every `interval_minutes`. At daily_forecast_hour, also
    produce the next-day forecast (DA gate close is at 12:00, so 11:00 is the
    operational sweet spot)."""
    print(f"[serve] interval={interval_minutes} min, daily forecast at {daily_forecast_hour:02d}:00 Athens")
    last_forecast_day = None
    while True:
        now = pd.Timestamp.now(tz=GR_TIMEZONE)
        target = None
        if now.hour == daily_forecast_hour and now.date() != last_forecast_day:
            target = (now + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            last_forecast_day = now.date()
        try:
            out = tick(forecast_target_date=target, full_refresh=(now.hour == daily_forecast_hour))
            print(json.dumps(out, default=str)[:200])
        except Exception as exc:
            print(f"[serve] tick failed: {exc}")
        time.sleep(interval_minutes * 60)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tick", action="store_true", help="run one tick (refresh + KPI update)")
    p.add_argument("--forecast", help="produce a forecast for YYYY-MM-DD")
    p.add_argument("--full-refresh", action="store_true", help="include slow sources (ENTSO-E + fuels)")
    p.add_argument("--serve", action="store_true", help="run forever, tick every 15 minutes")
    args = p.parse_args()

    if args.serve:
        serve()
    else:
        out = tick(forecast_target_date=args.forecast, full_refresh=args.full_refresh)
        print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
