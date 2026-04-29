<<<<<<< HEAD
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pulp

from config import BatterySpec, DEFAULT_BATTERY


def compute_price_thresholds(
    battery: BatterySpec,
    mean_price: float,
) -> tuple[float, float]:
    """
    Derive price floor (min discharge) and ceiling (max charge) from battery economics.

    min_discharge_price: discharge must at least cover its own degradation cost.
    max_charge_price:    charging only makes sense if the expected round-trip return
                         (stored energy × rte × mean_price) exceeds the charge cost
                         plus both-way degradation.  We use mean_price as a proxy for
                         the future discharge price.
    """
    rte = battery.eta_charge * battery.eta_discharge
    min_dis = battery.degradation_eur_per_mwh
    max_ch = mean_price * rte - 2 * battery.degradation_eur_per_mwh
    return min_dis, max_ch


def compute_low_confidence_mask(
    q10: pd.Series,
    q90: pd.Series,
    battery: BatterySpec = DEFAULT_BATTERY,
    mean_price: float | None = None,
) -> pd.Series:
    """
    Returns a boolean Series where True = low-confidence → force battery idle.

    Threshold = degradation_cost + (1 - sqrt(rte)) * mean_price
    Any MTU where the forecast spread (q90 - q10) < threshold is flagged.
    """
    rte = battery.eta_charge * battery.eta_discharge
    if mean_price is None:
        mean_price = float(((q10 + q90) / 2).mean())
    threshold = battery.degradation_eur_per_mwh + (1 - np.sqrt(rte)) * mean_price
    spread = q90 - q10
    return (spread < threshold).rename("low_confidence")


@dataclass
class Schedule:
    timestamps: pd.DatetimeIndex
    charge_mw: np.ndarray
    discharge_mw: np.ndarray
    soc_mwh: np.ndarray
    revenue_eur: float
    degradation_eur: float
    objective_eur: float
    delta_h: float

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "charge_mw": self.charge_mw,
                "discharge_mw": self.discharge_mw,
                "net_mw": self.discharge_mw - self.charge_mw,
                "soc_mwh": self.soc_mwh,
            },
            index=self.timestamps,
        )


def optimize(
    prices: pd.Series,
    battery: BatterySpec = DEFAULT_BATTERY,
    delta_h: float | None = None,
    soc_init: float | None = None,
    soc_final: float | None = None,
    idle_mask: pd.Series | None = None,
    solver_msg: bool = False,
) -> Schedule:
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("prices must be indexed by DatetimeIndex")
    prices = prices.sort_index()
    if delta_h is None:
        delta_h = (prices.index[1] - prices.index[0]).total_seconds() / 3600.0
    n = len(prices)
    p = prices.values.astype(float)

    soc0 = battery.soc_init if soc_init is None else soc_init
    if battery.cyclic and soc_final is None:
        soc_final = soc0

    ramp_limit = battery.ramp_mw if battery.ramp_mw is not None else battery.power_mw

    model = pulp.LpProblem("battery_dispatch", pulp.LpMaximize)

    ch = [pulp.LpVariable(f"ch_{t}", lowBound=0, upBound=battery.power_mw) for t in range(n)]
    dis = [pulp.LpVariable(f"dis_{t}", lowBound=0, upBound=battery.power_mw) for t in range(n)]
    soc = [pulp.LpVariable(f"soc_{t}", lowBound=battery.soc_min, upBound=battery.soc_max) for t in range(n)]
    z = [pulp.LpVariable(f"z_{t}", cat="Binary") for t in range(n)]
    y = [pulp.LpVariable(f"y_{t}", cat="Binary") for t in range(n)]

    revenue_terms = [p[t] * (dis[t] - ch[t]) * delta_h for t in range(n)]
    deg_terms = [battery.degradation_eur_per_mwh * (ch[t] + dis[t]) * delta_h for t in range(n)]

    soc_dev = None
    if battery.cyclic and battery.cyclic_penalty > 0 and soc_final is not None:
        soc_dev = pulp.LpVariable("soc_dev", lowBound=0)

    objective = pulp.lpSum(revenue_terms) - pulp.lpSum(deg_terms)
    if soc_dev is not None:
        objective -= battery.cyclic_penalty * soc_dev
    model += objective

    idle = np.zeros(n, dtype=int)
    if idle_mask is not None:
        idle_aligned = idle_mask.reindex(prices.index).fillna(False)
        idle = idle_aligned.values.astype(int)

    no_dis = np.zeros(n, dtype=int)
    if battery.min_discharge_price is not None:
        no_dis = (p < battery.min_discharge_price).astype(int)

    no_ch = np.zeros(n, dtype=int)
    if battery.max_charge_price is not None:
        no_ch = (p > battery.max_charge_price).astype(int)

    for t in range(n):
        prev_soc = soc0 if t == 0 else soc[t - 1]

        model += soc[t] == prev_soc + (battery.eta_charge * ch[t] - dis[t] / battery.eta_discharge) * delta_h
        model += z[t] + y[t] <= 1
        model += ch[t] <= battery.power_mw * z[t]
        model += dis[t] <= battery.power_mw * y[t]

        if battery.min_power_mw > 0:
            model += ch[t] >= battery.min_power_mw * z[t]
            model += dis[t] >= battery.min_power_mw * y[t]

        if ramp_limit < battery.power_mw and t > 0:
            net_t = dis[t] - ch[t]
            net_prev = dis[t - 1] - ch[t - 1]
            model += net_t - net_prev <= ramp_limit
            model += net_prev - net_t <= ramp_limit

        if idle[t]:
            model += ch[t] == 0
            model += dis[t] == 0

        if no_dis[t]:
            model += y[t] == 0

        if no_ch[t]:
            model += z[t] == 0

    if soc_final is not None:
        if soc_dev is not None:
            model += soc_dev >= soc[n - 1] - soc_final
            model += soc_dev >= soc_final - soc[n - 1]
        else:
            model += soc[n - 1] == soc_final

    if battery.max_cycles_per_day is not None:
        hours_per_day = 24
        cap_mwh_per_day = battery.max_cycles_per_day * battery.energy_mwh
        days = max(1, int(round(n * delta_h / hours_per_day)))
        model += pulp.lpSum([(ch[t] + dis[t]) * delta_h for t in range(n)]) <= 2 * cap_mwh_per_day * days

    solver = pulp.PULP_CBC_CMD(msg=solver_msg)
    status = model.solve(solver)
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"Solver did not converge: {pulp.LpStatus[status]}")

    ch_v = np.array([v.value() for v in ch])
    dis_v = np.array([v.value() for v in dis])
    soc_v = np.array([v.value() for v in soc])

    rev = float(np.sum(p * (dis_v - ch_v) * delta_h))
    deg = float(np.sum(battery.degradation_eur_per_mwh * (ch_v + dis_v) * delta_h))

    return Schedule(
        timestamps=prices.index,
        charge_mw=ch_v,
        discharge_mw=dis_v,
        soc_mwh=soc_v,
        revenue_eur=rev,
        degradation_eur=deg,
        objective_eur=rev - deg,
        delta_h=delta_h,
    )


def realized_revenue(
    schedule: Schedule,
    realized_prices: pd.Series,
    battery: BatterySpec = DEFAULT_BATTERY,
) -> float:
    p = realized_prices.reindex(schedule.timestamps).values.astype(float)
    rev = float(np.sum(p * (schedule.discharge_mw - schedule.charge_mw) * schedule.delta_h))
    deg = float(
        np.sum(battery.degradation_eur_per_mwh * (schedule.charge_mw + schedule.discharge_mw) * schedule.delta_h)
    )
    return rev - deg
