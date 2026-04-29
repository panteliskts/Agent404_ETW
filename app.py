"""
BESS Optimizer — Streamlit Dashboard
Pitch flow: load data → quantile forecast → LP dispatch → KPIs + 4 plots
Works fully offline using synthetic demo data.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from config import BatterySpec
from src.data_sources import load_market_data
from src.features import engineer_features
from src import forecaster, scheduler

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="BESS Optimizer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Cached heavy operations (run once per session)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Loading market data …")
def _load_data() -> tuple[pd.DataFrame, str]:
    df, source = load_market_data()
    df_feat = engineer_features(df)
    return df_feat, source


@st.cache_resource(show_spinner="Training quantile models (runs once) …")
def _get_models() -> dict:
    df_feat, _ = _load_data()
    # Try loading from disk first
    saved = forecaster.load_quantile_models()
    if saved is not None:
        return saved
    # Train on everything except the last 48 h (the forecast window)
    train_df = df_feat.dropna().iloc[:-48]
    return forecaster.train_all_quantiles(train_df, valid_days=30, test_days=7)


# ---------------------------------------------------------------------------
# Derating scenarios
# ---------------------------------------------------------------------------
DERATING_SCENARIOS = {
    "Base": {"eta_factor": 1.0, "cap_factor": 1.0},
    "Mild Degradation": {"eta_factor": 0.97, "cap_factor": 0.97},
    "Severe Degradation": {"eta_factor": 0.92, "cap_factor": 0.85},
}


def _apply_derating(base: BatterySpec, scenario: str) -> BatterySpec:
    s = DERATING_SCENARIOS[scenario]
    return BatterySpec(
        power_mw=base.power_mw * s["cap_factor"],
        energy_mwh=base.energy_mwh * s["cap_factor"],
        eta_charge=base.eta_charge * s["eta_factor"],
        eta_discharge=base.eta_discharge * s["eta_factor"],
        soc_min_frac=base.soc_min_frac,
        soc_max_frac=base.soc_max_frac,
        soc_init_frac=base.soc_init_frac,
        cyclic=base.cyclic,
        max_cycles_per_day=base.max_cycles_per_day,
        degradation_eur_per_mwh=base.degradation_eur_per_mwh,
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚡ BESS Optimizer")
    st.markdown("---")

    st.subheader("Battery Parameters")
    cap_mwh   = st.slider("Capacity (MWh)",              1.0,  200.0, 100.0, step=1.0)
    power_mw  = st.slider("Power (MW)",                  1.0,  100.0,  50.0, step=1.0)
    rte_pct   = st.slider("Round-trip efficiency (%)",  70.0,   99.0,  90.0, step=0.5)
    deg_cost  = st.slider("Degradation cost (€/MWh)",   0.5,   20.0,   5.0, step=0.5)
    init_soc  = st.slider("Initial SoC (%)",             5.0,   95.0,  50.0, step=5.0)

    st.markdown("---")
    st.subheader("Scenario")
    scenario = st.selectbox("Derating", list(DERATING_SCENARIOS.keys()))

    st.markdown("---")
    st.subheader("Data source")
    source_placeholder = st.empty()

# ---------------------------------------------------------------------------
# Build battery spec
# ---------------------------------------------------------------------------
eta = (rte_pct / 100) ** 0.5   # symmetric charge/discharge

base_spec = BatterySpec(
    power_mw=power_mw,
    energy_mwh=cap_mwh,
    eta_charge=eta,
    eta_discharge=eta,
    soc_min_frac=0.05,
    soc_max_frac=0.95,
    soc_init_frac=init_soc / 100,
    cyclic=True,
    max_cycles_per_day=1.5,
    degradation_eur_per_mwh=deg_cost,
)
battery = _apply_derating(base_spec, scenario)

# ---------------------------------------------------------------------------
# Load data + models
# ---------------------------------------------------------------------------
df_feat, source = _load_data()
models          = _get_models()

source_labels = {"live": "🟢 Live API", "cache": "🟡 Cache", "demo": "🔵 Demo (synthetic)"}
source_placeholder.markdown(f"**{source_labels.get(source, source)}**")

# ---------------------------------------------------------------------------
# Forecast & optimize over the last 48 h
# ---------------------------------------------------------------------------
forecast_window = df_feat.dropna().iloc[-48:].copy()
actual_prices   = forecast_window["dam_price_eur_mwh"]

q_preds = forecaster.predict_interval(models, forecast_window)
q10, q50, q90 = q_preds["q10"], q_preds["q50"], q_preds["q90"]

idle_mask = scheduler.compute_low_confidence_mask(q10, q90, battery=battery)

schedule = scheduler.optimize(
    q50,
    battery=battery,
    idle_mask=idle_mask,
    solver_msg=False,
)
sched_df = schedule.to_frame()

# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
gross_revenue = float(np.sum(actual_prices.values * (sched_df["discharge_mw"].values - sched_df["charge_mw"].values) * schedule.delta_h))
cycles_used   = float(np.sum(sched_df["discharge_mw"].values) * schedule.delta_h / battery.energy_mwh)

st.markdown("## Battery Dispatch Dashboard")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Net Profit",       f"€ {schedule.objective_eur:,.0f}")
k2.metric("Gross Revenue",    f"€ {gross_revenue:,.0f}")
k3.metric("Degradation Cost", f"€ {schedule.degradation_eur:,.0f}")
k4.metric("Cycles Used",      f"{cycles_used:.2f}")

st.markdown("---")

idle_count = int(idle_mask.sum())
total_mtus = len(idle_mask)
st.info(
    f"**Spread filter:** {idle_count}/{total_mtus} MTUs marked low-confidence → forced idle. "
    f"Threshold = {battery.degradation_eur_per_mwh:.1f} + (1 − √RTE) × mean_price"
)

# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------
COLORS = {
    "actual":   "#9ca3af",
    "q50":      "#3b82f6",
    "band":     "rgba(59,130,246,0.15)",
    "charge":   "#22c55e",
    "discharge":"#3b82f6",
    "net":      "#f97316",
    "soc":      "#14b8a6",
    "idle":     "rgba(156,163,175,0.35)",
    "bound":    "#ef4444",
}

ts = forecast_window.index

# ---------------------------------------------------------------------------
# Plot 1: Price Forecast
# ---------------------------------------------------------------------------
fig_price = go.Figure()

fig_price.add_trace(go.Scatter(
    x=ts, y=q90, mode="lines",
    line=dict(width=0), showlegend=False, hoverinfo="skip",
))
fig_price.add_trace(go.Scatter(
    x=ts, y=q10, mode="lines",
    fill="tonexty", fillcolor=COLORS["band"],
    line=dict(width=0), name="Q10–Q90 band",
))
fig_price.add_trace(go.Scatter(
    x=ts, y=actual_prices, mode="lines",
    line=dict(color=COLORS["actual"], width=1.5, dash="dot"),
    name="Actual",
))
fig_price.add_trace(go.Scatter(
    x=ts, y=q50, mode="lines",
    line=dict(color=COLORS["q50"], width=2),
    name="Q50 forecast",
))

fig_price.update_layout(
    title="Price Forecast — Q10 / Q50 / Q90",
    yaxis_title="€/MWh",
    xaxis_title="",
    legend=dict(orientation="h", y=1.12),
    height=340,
    margin=dict(t=60, b=20),
)
st.plotly_chart(fig_price, use_container_width=True)

# ---------------------------------------------------------------------------
# Plot 2: Charge / Discharge Schedule
# ---------------------------------------------------------------------------
fig_sched = go.Figure()

# Grey background for idle (low-confidence) MTUs
for i, (t, is_idle) in enumerate(idle_mask.items()):
    if is_idle:
        fig_sched.add_vrect(
            x0=t, x1=ts[min(i + 1, len(ts) - 1)],
            fillcolor=COLORS["idle"], layer="below", line_width=0,
        )

fig_sched.add_trace(go.Bar(
    x=ts, y=-sched_df["charge_mw"],
    name="Charging", marker_color=COLORS["charge"],
    opacity=0.85,
))
fig_sched.add_trace(go.Bar(
    x=ts, y=sched_df["discharge_mw"],
    name="Discharging", marker_color=COLORS["discharge"],
    opacity=0.85,
))
fig_sched.add_trace(go.Scatter(
    x=ts, y=sched_df["net_mw"], mode="lines",
    line=dict(color=COLORS["net"], width=2),
    name="Net Power",
))

fig_sched.update_layout(
    title="Dispatch Schedule  (grey = low-confidence idle)",
    yaxis_title="MW  (+ discharge, − charge)",
    barmode="overlay",
    legend=dict(orientation="h", y=1.12),
    height=320,
    margin=dict(t=60, b=20),
)
st.plotly_chart(fig_sched, use_container_width=True)

# ---------------------------------------------------------------------------
# Plot 3: SoC Trajectory
# ---------------------------------------------------------------------------
fig_soc = go.Figure()

fig_soc.add_hrect(
    y0=battery.soc_min, y1=battery.soc_max,
    fillcolor="rgba(20,184,166,0.08)", layer="below", line_width=0,
    annotation_text="Operating band", annotation_position="top right",
)
fig_soc.add_hline(
    y=battery.soc_min,
    line=dict(color=COLORS["bound"], dash="dash", width=1.5),
    annotation_text=f"Min SoC ({battery.soc_min_frac*100:.0f}%)",
    annotation_position="right",
)
fig_soc.add_hline(
    y=battery.soc_max,
    line=dict(color=COLORS["bound"], dash="dash", width=1.5),
    annotation_text=f"Max SoC ({battery.soc_max_frac*100:.0f}%)",
    annotation_position="right",
)
fig_soc.add_trace(go.Scatter(
    x=ts, y=sched_df["soc_mwh"],
    mode="lines", fill="tozeroy",
    fillcolor="rgba(20,184,166,0.15)",
    line=dict(color=COLORS["soc"], width=2.5),
    name="SoC (MWh)",
))

fig_soc.update_layout(
    title="State of Charge Trajectory",
    yaxis_title="MWh",
    height=300,
    legend=dict(orientation="h", y=1.12),
    margin=dict(t=60, b=20),
)
st.plotly_chart(fig_soc, use_container_width=True)

# ---------------------------------------------------------------------------
# Plot 4: Feature Importance (Q50 model)
# ---------------------------------------------------------------------------
with st.expander("Feature Importance (Q50 model)", expanded=False):
    try:
        q50_model = models["q50"].model
        feat_cols  = models["q50"].feature_cols
        importance = q50_model.feature_importance(importance_type="gain")
        imp_df = (
            pd.DataFrame({"feature": feat_cols, "gain": importance})
            .sort_values("gain", ascending=True)
            .tail(20)
        )
        fig_imp = go.Figure(go.Bar(
            x=imp_df["gain"], y=imp_df["feature"],
            orientation="h", marker_color=COLORS["q50"],
        ))
        fig_imp.update_layout(
            title="Top 20 Features by Gain",
            height=500,
            margin=dict(t=50, b=20, l=180),
        )
        st.plotly_chart(fig_imp, use_container_width=True)
    except Exception as exc:
        st.warning(f"Feature importance unavailable: {exc}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption(
    f"Scenario: **{scenario}** · Capacity: **{battery.energy_mwh:.0f} MWh** · "
    f"Power: **{battery.power_mw:.0f} MW** · RTE: **{(battery.eta_charge * battery.eta_discharge) * 100:.1f}%** · "
    f"Degradation: **€{battery.degradation_eur_per_mwh:.1f}/MWh**"
)
