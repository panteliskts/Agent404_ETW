from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import BatterySpec, DEFAULT_BATTERY
from src.scheduler import Schedule, optimize, realized_revenue


@dataclass
class DayResult:
    date: pd.Timestamp
    perfect_revenue: float
    forecast_revenue: float
    realized_revenue: float
    capture_ratio: float
    cycles: float


def cycles_done(schedule: Schedule, battery: BatterySpec) -> float:
    throughput_mwh = float(np.sum(schedule.discharge_mw) * schedule.delta_h)
    return throughput_mwh / battery.energy_mwh


def evaluate_day(
    realized_prices: pd.Series,
    forecast_prices: pd.Series,
    battery: BatterySpec = DEFAULT_BATTERY,
) -> DayResult:
    common = realized_prices.index.intersection(forecast_prices.index)
    realized_prices = realized_prices.loc[common]
    forecast_prices = forecast_prices.loc[common]

    perfect = optimize(realized_prices, battery=battery)
    fcst = optimize(forecast_prices, battery=battery)
    realized = realized_revenue(fcst, realized_prices, battery=battery)

    return DayResult(
        date=realized_prices.index[0].normalize(),
        perfect_revenue=perfect.objective_eur,
        forecast_revenue=fcst.objective_eur,
        realized_revenue=realized,
        capture_ratio=(realized / perfect.objective_eur) if perfect.objective_eur > 0 else 0.0,
        cycles=cycles_done(fcst, battery),
    )


def rolling_backtest(
    realized: pd.Series,
    forecast: pd.Series,
    battery: BatterySpec = DEFAULT_BATTERY,
) -> pd.DataFrame:
    realized = realized.sort_index()
    forecast = forecast.sort_index()
    days = pd.unique(realized.index.normalize())
    rows = []
    for d in days:
        day_real = realized.loc[realized.index.normalize() == d]
        day_fcst = forecast.loc[forecast.index.normalize() == d]
        if day_real.empty or day_fcst.empty:
            continue
        try:
            r = evaluate_day(day_real, day_fcst, battery=battery)
            rows.append(r.__dict__)
        except Exception as exc:
            print(f"[backtest] {d.date()} failed: {exc}")
    return pd.DataFrame(rows).set_index("date")


def summary(results: pd.DataFrame) -> dict:
    return {
        "days": len(results),
        "total_perfect_eur": float(results["perfect_revenue"].sum()),
        "total_realized_eur": float(results["realized_revenue"].sum()),
        "mean_capture_ratio": float(results["capture_ratio"].mean()),
        "mean_cycles_per_day": float(results["cycles"].mean()),
        "eur_per_mwh_capacity_per_day": float(
            results["realized_revenue"].mean() / DEFAULT_BATTERY.energy_mwh
        ),
    }
