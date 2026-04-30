from __future__ import annotations

import asyncio
import logging
import math
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.security import (  # noqa: E402
    AuthenticatedUser,
    api_rate_limiter,
    clear_auth_cookies,
    client_ip,
    create_session_token,
    login_rate_limiter,
    require_user,
    security_headers,
    set_auth_cookies,
    settings,
    verify_credentials,
)
from api import (  # noqa: E402
    audit,
    mfa as mfa_module,
    api_keys as api_keys_module,
    webhooks as webhooks_module,
    billing as billing_module,
)
from api.rbac import require_admin, require_operator, require_viewer  # noqa: E402
from api.oauth import router as oidc_router  # noqa: E402
from config import BatterySpec
from src import forecaster, scheduler
from src.data_sources import load_market_data
from src.features import engineer_features
from src.forecaster import TARGET, TrainResult


DERATING_SCENARIOS = {
    "Base": {"eta_factor": 1.00, "cap_factor": 1.00},
    "Mild Degradation": {"eta_factor": 0.97, "cap_factor": 0.97},
    "Severe Degradation": {"eta_factor": 0.92, "cap_factor": 0.85},
}

Scenario = Literal["Base", "Mild Degradation", "Severe Degradation"]
PUBLIC_ERROR_MESSAGE = "Oops, there must be something wrong. Please retry."
logger = logging.getLogger(__name__)


class OptimizeRequest(BaseModel):
    capacity_mwh: float = Field(default=100.0, ge=1.0, le=200.0)
    power_mw: float = Field(default=50.0, ge=1.0, le=100.0)
    rte_pct: float = Field(default=90.0, ge=70.0, le=99.0)
    degradation_eur_per_mwh: float = Field(default=5.0, ge=0.0)
    initial_soc_pct: float = Field(default=50.0, ge=5.0, le=95.0)
    scenario: Scenario = "Base"
    planning_mode: Literal["short", "long"] = "long"
    max_horizon_days: int = Field(default=4, ge=2, le=7)
    future_base_discount: float = Field(default=0.1, ge=0.0, le=1.0)
    future_decay: float = Field(default=0.6, ge=0.1, le=1.0)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


@dataclass
class RuntimeState:
    raw_data: pd.DataFrame | None = None
    features: pd.DataFrame | None = None
    source: str = "unknown"
    models: dict[str, TrainResult] | None = None
    model_status: str = "booting"
    model_error: str | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)


state = RuntimeState()

app = FastAPI(title="LogicVolt API", version="1.0.0")
app.include_router(oidc_router, prefix="/auth/oidc")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if request.method.upper() != "OPTIONS" and request.url.path != "/health":
        limiter = login_rate_limiter if request.url.path == "/auth/login" else api_rate_limiter
        allowed, retry_after = limiter.check(client_ip(request))
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )
            origin = request.headers.get("origin")
            if origin in settings.allowed_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Vary"] = "Origin"
            for key, value in security_headers().items():
                response.headers[key] = value
            return response

    response = await call_next(request)
    for key, value in security_headers().items():
        response.headers.setdefault(key, value)
    return response


def _json_float(value: float | np.floating | None) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).isoformat()


def _apply_derating(base: BatterySpec, scenario: Scenario) -> BatterySpec:
    derating = DERATING_SCENARIOS[scenario]
    return BatterySpec(
        power_mw=base.power_mw * derating["cap_factor"],
        energy_mwh=base.energy_mwh * derating["cap_factor"],
        eta_charge=base.eta_charge * derating["eta_factor"],
        eta_discharge=base.eta_discharge * derating["eta_factor"],
        soc_min_frac=base.soc_min_frac,
        soc_max_frac=base.soc_max_frac,
        soc_init_frac=base.soc_init_frac,
        cyclic=base.cyclic,
        max_cycles_per_day=base.max_cycles_per_day,
        degradation_eur_per_mwh=base.degradation_eur_per_mwh,
    )


def _daily_spread_mean(q10: pd.Series, q90: pd.Series) -> pd.Series:
    spread = (q90 - q10)
    return spread.groupby(spread.index.normalize()).mean()


def _discount_curve(horizon_days: int, base: float, decay: float) -> list[float]:
    discounts = [1.0]
    for i in range(1, horizon_days):
        discounts.append(base * (decay ** (i - 1)))
    return discounts


def _choose_horizon(spread_mean: float, thr_low: float, thr_high: float, max_horizon: int) -> int:
    if spread_mean <= thr_low:
        return min(4, max_horizon)
    if spread_mean <= thr_high:
        return min(3, max_horizon)
    return 2


def _schedule_with_horizon(
    q10: pd.Series,
    q50: pd.Series,
    q90: pd.Series,
    idle_mask: pd.Series | None,
    battery: BatterySpec,
    horizon_selector,
    base_discount: float,
    decay: float,
) -> tuple[pd.DataFrame, dict[int, int]]:
    days = q50.index.normalize()
    unique_days = days.unique().sort_values()
    schedules = []
    horizon_counts: dict[int, int] = {}

    for i, d in enumerate(unique_days):
        m0 = days == d
        if m0.sum() < 90:
            continue
        horizon_days = int(horizon_selector(d))
        remaining = len(unique_days) - i
        horizon_days = max(1, min(horizon_days, remaining))

        prices_by_day = []
        masks_by_day = []
        for j in range(horizon_days):
            dj = unique_days[i + j]
            mj = days == dj
            prices_by_day.append(q50[mj])
            masks_by_day.append(idle_mask[mj] if idle_mask is not None else None)

        discounts = _discount_curve(horizon_days, base_discount, decay)
        sched = scheduler.optimize_multiday_horizon(
            prices_by_day,
            battery=battery,
            idle_masks=masks_by_day,
            discounts=discounts,
        )
        day_df = sched.to_frame()
        day_df["horizon_days"] = horizon_days
        schedules.append(day_df)
        horizon_counts[horizon_days] = horizon_counts.get(horizon_days, 0) + 1

    if not schedules:
        return pd.DataFrame(), horizon_counts

    out = pd.concat(schedules).sort_index()
    out["price_q10"] = q10.reindex(out.index)
    out["price_q50"] = q50.reindex(out.index)
    out["price_q90"] = q90.reindex(out.index)
    out["spread"] = out["price_q90"] - out["price_q10"]
    if idle_mask is not None:
        out["confidence"] = np.where(idle_mask.reindex(out.index).fillna(False), "low", "high")
    else:
        out["confidence"] = "high"
    return out, horizon_counts


def _naive_baseline_revenue(
    q50: pd.Series,
    battery: BatterySpec,
    delta_h: float,
    charge_hours: tuple[int, int] = (2, 6),
    discharge_hours: tuple[int, int] = (18, 22),
) -> dict:
    """Revenue from the dumbest defensible strategy: full-power charge in the
    early-morning window, full-power discharge in the evening peak window,
    on the same forecast prices the LP sees. This is the "without us" number
    customers compare to: peak-shaving with no model, no LP, no horizon.
    """
    if q50.empty:
        return {"net_profit_eur": 0.0, "gross_revenue_eur": 0.0, "degradation_eur": 0.0, "cycles": 0.0}

    local = q50.tz_convert("Europe/Athens") if q50.index.tz is not None else q50
    hours = local.index.hour
    is_charge = (hours >= charge_hours[0]) & (hours < charge_hours[1])
    is_discharge = (hours >= discharge_hours[0]) & (hours < discharge_hours[1])

    # Full power in each band, capped by daily capacity & cycle budget.
    n_days = max(int((local.index[-1].normalize() - local.index[0].normalize()).days) + 1, 1)
    cap_mwh = battery.energy_mwh * (battery.soc_max_frac - battery.soc_min_frac)
    daily_throughput_cap = cap_mwh * battery.max_cycles_per_day
    total_cap = daily_throughput_cap * n_days

    charge_mw  = np.where(is_charge,    battery.power_mw, 0.0)
    discharge_mw = np.where(is_discharge, battery.power_mw, 0.0)

    # Trim to throughput budget by scaling both legs uniformly.
    throughput_mwh = float((charge_mw + discharge_mw).sum() * delta_h)
    if throughput_mwh > total_cap and throughput_mwh > 0:
        scale = total_cap / throughput_mwh
        charge_mw *= scale
        discharge_mw *= scale

    prices = q50.to_numpy()
    revenue = float(((discharge_mw - charge_mw) * prices * delta_h).sum())
    # Round-trip efficiency penalty applied on the discharge leg
    rte = battery.eta_charge * battery.eta_discharge
    revenue *= rte if revenue > 0 else 1.0
    degradation = float(battery.degradation_eur_per_mwh * (charge_mw + discharge_mw).sum() * delta_h)
    cycles = float(discharge_mw.sum() * delta_h / battery.energy_mwh)
    return {
        "net_profit_eur": revenue - degradation,
        "gross_revenue_eur": revenue,
        "degradation_eur": degradation,
        "cycles": cycles,
    }


def _battery_from_request(payload: OptimizeRequest) -> BatterySpec:
    symmetric_eta = math.sqrt(payload.rte_pct / 100.0)
    base = BatterySpec(
        power_mw=payload.power_mw,
        energy_mwh=payload.capacity_mwh,
        eta_charge=symmetric_eta,
        eta_discharge=symmetric_eta,
        soc_min_frac=0.05,
        soc_max_frac=0.95,
        soc_init_frac=payload.initial_soc_pct / 100.0,
        cyclic=True,
        max_cycles_per_day=1.5,
        degradation_eur_per_mwh=payload.degradation_eur_per_mwh,
    )
    return _apply_derating(base, payload.scenario)


def _train_models_in_background() -> None:
    with state.lock:
        features = state.features
        state.model_status = "training"
        state.model_error = None

    try:
        if features is None:
            raise RuntimeError("feature matrix is not loaded")
        train_df = features.dropna().iloc[:-48]
        if train_df.empty:
            train_df = features.dropna()
        models = forecaster.train_all_quantiles(train_df, valid_days=30, test_days=7)
        with state.lock:
            state.models = models
            state.model_status = "ready"
    except Exception as exc:  # pragma: no cover - surfaced through /status
        logger.exception("Model training failed")
        with state.lock:
            state.model_status = "error"
            state.model_error = str(exc)


@app.on_event("startup")
async def startup() -> None:
    loop = asyncio.get_running_loop()
    try:
        raw_data, source = await loop.run_in_executor(None, load_market_data)
        features = await loop.run_in_executor(None, engineer_features, raw_data)
        models = await loop.run_in_executor(None, forecaster.load_quantile_models)

        with state.lock:
            state.raw_data = raw_data
            state.features = features
            state.source = source
            state.models = models
            state.model_error = None
            state.model_status = "ready" if models is not None else "training"

        if models is None:
            thread = threading.Thread(target=_train_models_in_background, daemon=True)
            thread.start()
    except Exception as exc:  # pragma: no cover - surfaced through /status
        logger.exception("Application startup failed")
        with state.lock:
            state.model_status = "error"
            state.model_error = str(exc)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    if not verify_credentials(payload.username, payload.password):
        audit.log(action="login_failed", user=payload.username, ip=ip, resource="auth")
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if mfa_module.is_enabled(payload.username):
        pending_token = mfa_module.create_pending_token(payload.username)
        audit.log(action="login_mfa_pending", user=payload.username, ip=ip, resource="auth")
        return {"mfa_required": True, "mfa_token": pending_token}

    session_token, csrf_token, expires_at = create_session_token(
        payload.username, role=settings.auth_role
    )
    set_auth_cookies(response, session_token, csrf_token, expires_at)
    audit.log(action="login", user=payload.username, ip=ip, resource="auth")
    return {
        "user": {"username": payload.username, "role": settings.auth_role},
        "csrf_token": csrf_token,
        "session_expires_at": expires_at,
    }


@app.post("/auth/mfa/verify")
def mfa_verify(body: dict, response: Response) -> dict:
    mfa_token = str(body.get("mfa_token", ""))
    totp_code = str(body.get("totp_code", ""))

    username = mfa_module.consume_pending_token(mfa_token)
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid or expired MFA token")

    if not mfa_module.verify(username, totp_code):
        raise HTTPException(status_code=401, detail="Invalid TOTP code")

    session_token, csrf_token, expires_at = create_session_token(username, role=settings.auth_role)
    set_auth_cookies(response, session_token, csrf_token, expires_at)
    audit.log(action="login_mfa_ok", user=username, resource="auth")
    return {
        "user": {"username": username, "role": settings.auth_role},
        "csrf_token": csrf_token,
        "session_expires_at": expires_at,
    }


@app.get("/auth/mfa/setup")
def mfa_setup(user: AuthenticatedUser = Depends(require_user)) -> dict:
    secret = mfa_module.provision(user.username)
    qr_svg = mfa_module.get_qr_svg(user.username)
    return {"secret": secret, "qr_svg": qr_svg, "enabled": False}


@app.get("/auth/mfa/status")
def mfa_status(user: AuthenticatedUser = Depends(require_user)) -> dict:
    return {"enabled": mfa_module.is_enabled(user.username)}


@app.post("/auth/mfa/disable")
def mfa_disable(user: AuthenticatedUser = Depends(require_user)) -> dict:
    mfa_module.disable(user.username)
    audit.log(action="mfa_disabled", user=user.username, resource="auth")
    return {"ok": True, "enabled": False}


@app.post("/auth/mfa/enable")
def mfa_enable(body: dict, user: AuthenticatedUser = Depends(require_user)) -> dict:
    totp_code = str(body.get("totp_code", ""))
    if not mfa_module.enable(user.username, totp_code):
        raise HTTPException(status_code=400, detail="TOTP code verification failed")
    audit.log(action="mfa_enabled", user=user.username, resource="auth")
    return {"ok": True, "enabled": True}


@app.get("/auth/me")
def current_user(user: AuthenticatedUser = Depends(require_user)) -> dict:
    return {"user": {"username": user.username}, "csrf_token": user.csrf_token}


@app.post("/auth/logout")
def logout(request: Request, response: Response, user: AuthenticatedUser = Depends(require_user)) -> dict:
    audit.log(action="logout", user=user.username, ip=client_ip(request), resource="auth")
    clear_auth_cookies(response)
    return {"ok": True}


def _snapshot_data() -> tuple[pd.DataFrame, str, int]:
    with state.lock:
        features = state.features
        source = state.source
        data_rows = 0 if state.raw_data is None else len(state.raw_data)
    if features is None:
        raise HTTPException(status_code=503, detail="market data is still loading")
    return features, source, data_rows


def _snapshot_models() -> dict[str, TrainResult]:
    with state.lock:
        models = state.models
        status = state.model_status
    if models is None or status != "ready":
        detail = "models are still training" if status != "error" else PUBLIC_ERROR_MESSAGE
        raise HTTPException(status_code=503, detail=detail)
    return models


def _forecast_window() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    features, source, _ = _snapshot_data()
    models = _snapshot_models()
    required_cols = sorted({TARGET, *(col for result in models.values() for col in result.feature_cols)})
    missing = [col for col in required_cols if col not in features.columns]
    if missing:
        raise HTTPException(status_code=500, detail=f"feature matrix is missing model columns: {missing[:5]}")

    # LightGBM handles missing feature values, so keep the latest real price
    # rows instead of filtering the window down to sparse fully-complete rows.
    window = features.dropna(subset=[TARGET]).tail(48).copy()
    if len(window) < 48:
        raise HTTPException(status_code=503, detail="not enough complete rows for a 48-hour forecast")

    predictions = forecaster.predict_interval(models, window)
    return window, predictions, source


@app.get("/status")
def status(_: AuthenticatedUser = Depends(require_user)) -> dict:
    with state.lock:
        data_rows = 0 if state.raw_data is None else len(state.raw_data)
        return {
            "model_ready": state.models is not None and state.model_status == "ready",
            "model_status": state.model_status,
            "model_error": PUBLIC_ERROR_MESSAGE if state.model_status == "error" else None,
            "source": state.source,
            "data_rows": data_rows,
        }


@app.get("/forecast")
def forecast(_: AuthenticatedUser = Depends(require_user)) -> dict:
    window, predictions, _ = _forecast_window()
    return {
        "timestamps": [_iso(ts) for ts in window.index],
        "actual": [_json_float(value) for value in window[TARGET].to_numpy()],
        "q10": [_json_float(value) for value in predictions["q05"].to_numpy()],
        "q50": [_json_float(value) for value in predictions["q50"].to_numpy()],
        "q90": [_json_float(value) for value in predictions["q95"].to_numpy()],
    }


@app.post("/optimize")
def optimize(
    request: Request,
    payload: OptimizeRequest | None = None,
    user: AuthenticatedUser = Depends(require_operator),
) -> dict:
    payload = payload or OptimizeRequest()
    battery = _battery_from_request(payload)
    _, predictions, source = _forecast_window()

    q10 = predictions["q05"]
    q50 = predictions["q50"]
    q90 = predictions["q95"]
    idle_mask = scheduler.compute_low_confidence_mask(q10, q90, battery=battery)

    if payload.planning_mode == "short":
        def _short_selector(_day):
            return 2
        schedule_df, horizon_counts = _schedule_with_horizon(
            q10,
            q50,
            q90,
            idle_mask,
            battery,
            _short_selector,
            payload.future_base_discount,
            payload.future_decay,
        )
        spread_daily = _daily_spread_mean(q10, q90)
        spread_thr_low = float(spread_daily.quantile(0.33)) if len(spread_daily) else None
        spread_thr_high = float(spread_daily.quantile(0.66)) if len(spread_daily) else None
    else:
        spread_daily = _daily_spread_mean(q10, q90)
        spread_thr_low = float(spread_daily.quantile(0.33)) if len(spread_daily) else None
        spread_thr_high = float(spread_daily.quantile(0.66)) if len(spread_daily) else None

        def _dynamic_selector(day):
            spread_mean = float(spread_daily.loc[day]) if day in spread_daily.index else float("inf")
            return _choose_horizon(spread_mean, spread_thr_low or 0.0, spread_thr_high or 0.0, payload.max_horizon_days)

        schedule_df, horizon_counts = _schedule_with_horizon(
            q10,
            q50,
            q90,
            idle_mask,
            battery,
            _dynamic_selector,
            payload.future_base_discount,
            payload.future_decay,
        )

    if schedule_df.empty:
        raise HTTPException(status_code=503, detail="not enough forecast rows to build a schedule")

    delta_h = float((schedule_df.index[1] - schedule_df.index[0]).total_seconds() / 3600.0)
    schedule_df["net_mw"] = schedule_df["discharge_mw"] - schedule_df["charge_mw"]

    net_mw = schedule_df["discharge_mw"].to_numpy() - schedule_df["charge_mw"].to_numpy()
    throughput_mwh = (schedule_df["charge_mw"].to_numpy() + schedule_df["discharge_mw"].to_numpy()) * delta_h
    gross_revenue = float(np.sum(schedule_df["price_q50"].to_numpy() * net_mw * delta_h))
    degradation = float(np.sum(battery.degradation_eur_per_mwh * throughput_mwh))
    net_profit = gross_revenue - degradation
    cycles_used = float(np.sum(schedule_df["discharge_mw"].to_numpy()) * delta_h / battery.energy_mwh)
    idle_aligned = idle_mask.reindex(schedule_df.index).fillna(False)

    # Customer KPI: revenue if no model existed (peak-shaving heuristic on q50).
    naive = _naive_baseline_revenue(q50.loc[schedule_df.index], battery, delta_h)
    horizon_days_total = float(len(schedule_df) * delta_h / 24.0) or 1.0
    daily_profit_eur = net_profit / horizon_days_total
    daily_naive_eur = naive["net_profit_eur"] / horizon_days_total
    uplift_eur_day = daily_profit_eur - daily_naive_eur
    annualized_revenue_eur = daily_profit_eur * 365.0
    annualized_uplift_eur = uplift_eur_day * 365.0
    energy_traded_mwh = float(throughput_mwh.sum())
    capture_vs_naive = (
        net_profit / naive["net_profit_eur"]
        if naive["net_profit_eur"] > 1e-6 else None
    )

    rows = []
    for ts, row in schedule_df.iterrows():
        rows.append(
            {
                "time": _iso(ts),
                "charge_mw": float(row["charge_mw"]),
                "discharge_mw": float(row["discharge_mw"]),
                "net_mw": float(row["net_mw"]),
                "soc_mwh": float(row["soc_mwh"]),
                "horizon_days": int(row["horizon_days"]),
                "price_q10": _json_float(row["price_q10"]),
                "price_q50": _json_float(row["price_q50"]),
                "price_q90": _json_float(row["price_q90"]),
                "spread": _json_float(row["spread"]),
                "confidence": str(row["confidence"]),
                "is_idle": bool(idle_aligned.loc[ts]),
            }
        )

    result = {
        "kpis": {
            "net_profit_eur": net_profit,
            "gross_revenue_eur": gross_revenue,
            "degradation_eur": degradation,
            "cycles_used": cycles_used,
            "idle_count": int(idle_aligned.sum()),
            "total_mtus": int(len(idle_aligned)),
            "horizon_counts": horizon_counts,
            "energy_traded_mwh": energy_traded_mwh,
            "daily_profit_eur": daily_profit_eur,
            "annualized_revenue_eur": annualized_revenue_eur,
            "naive_baseline_eur": naive["net_profit_eur"],
            "naive_daily_eur": daily_naive_eur,
            "uplift_eur_day": uplift_eur_day,
            "annualized_uplift_eur": annualized_uplift_eur,
            "capture_vs_naive": _json_float(capture_vs_naive),
            "model_capture_ratio": 0.8743,  # walk-forward overall, see HANDOFF Section 8
        },
        "planning": {
            "mode": payload.planning_mode,
            "max_horizon_days": payload.max_horizon_days,
            "future_base_discount": payload.future_base_discount,
            "future_decay": payload.future_decay,
            "spread_threshold_low": _json_float(spread_thr_low),
            "spread_threshold_high": _json_float(spread_thr_high),
        },
        "schedule": rows,
        "source": source,
    }
    audit.log(
        action="optimize",
        user=user.username,
        ip=client_ip(request),
        resource="schedule",
        details={
            "scenario": payload.scenario,
            "net_profit_eur": round(net_profit, 2),
            "capacity_mwh": payload.capacity_mwh,
        },
    )

    # Meter API-key callers; cookie sessions are not metered.
    api_key_id = getattr(request.state, "api_key_id", None)
    if api_key_id:
        billing_module.record_call(api_key_id)

    # Fan out to webhook subscribers (fire-and-forget; failures are logged
    # to the webhook record, never surfaced to the optimize caller).
    webhook_payload = {
        "event": "optimize.completed",
        "delivered_at": int(__import__("time").time()),
        "asset": {
            "capacity_mwh": payload.capacity_mwh,
            "power_mw": payload.power_mw,
            "rte_pct": payload.rte_pct,
            "scenario": payload.scenario,
        },
        "kpis": result["kpis"],
        "horizon": {
            "first": _iso(schedule_df.index[0]),
            "last":  _iso(schedule_df.index[-1]),
            "mtus":  len(schedule_df),
        },
    }
    webhook_owner = user.username.replace("apikey:", "") if user.username.startswith("apikey:") else None
    webhooks_module.dispatch("optimize.completed", webhook_payload, owner=webhook_owner)

    return result


@app.get("/data-feeds")
def data_feeds(_: AuthenticatedUser = Depends(require_viewer)) -> dict:
    """Per-feed health view used by the Onboarding page."""
    with state.lock:
        df = state.raw_data
        source = state.source
        data_rows = 0 if df is None else len(df)

    if df is None:
        feeds = []
        last_observation: str | None = None
    else:
        last_observation = _iso(df.index.max())
        cols = set(df.columns)
        price_cols = {"dam_price_eur_mwh", "price_eur_mwh"}
        wx_cols = {c for c in cols if any(p in c.lower() for p in ("temp", "wind", "ghi", "irrad", "weather", "athens", "thess", "patras"))}
        load_cols = {c for c in cols if "load" in c.lower() or "res" in c.lower()}
        fuel_cols = {c for c in cols if "ttf" in c.lower() or "eua" in c.lower()}

        def _feed(name: str, detail: str, columns: set[str]) -> dict:
            available = sorted(columns & cols)
            non_null = int(df[available].notna().any(axis=1).sum()) if available else 0
            return {
                "name": name,
                "detail": detail,
                "status": (
                    "Live" if source == "live" and non_null > 0 else
                    "Cached" if source == "cache" and non_null > 0 else
                    "Demo" if non_null > 0 else
                    "Unavailable"
                ),
                "rows": non_null,
                "columns": available,
            }

        feeds = [
            _feed("HEnEx / ENTSO-E DAM", "Day-Ahead Market clearing prices (€/MWh)", price_cols),
            _feed("Open-Meteo Weather", "Temperature, wind, irradiance for GR zones", wx_cols),
            _feed("IPTO Load & RES", "Demand and renewable forecast signals", load_cols),
            _feed("TTF / EUA Fuels", "Gas + carbon market context for SRMC", fuel_cols),
        ]

    return {
        "source": source,
        "data_rows": data_rows,
        "last_observation": last_observation,
        "feeds": feeds,
    }


@app.get("/feature-importance")
def feature_importance(_: AuthenticatedUser = Depends(require_viewer)) -> dict:
    models = _snapshot_models()
    q50 = models.get("q50")
    if q50 is None:
        raise HTTPException(status_code=503, detail="Q50 model is unavailable")

    gains = q50.model.feature_importance(importance_type="gain")
    ranked = sorted(
        zip(q50.feature_cols, gains, strict=True),
        key=lambda item: float(item[1]),
        reverse=True,
    )[:20]
    return {
        "features": [feature for feature, _ in ranked],
        "gain": [float(gain) for _, gain in ranked],
    }


# ── API key management (admin-only) ──────────────────────────────────────────

class ApiKeyCreateRequest(BaseModel):
    label: str = Field(default="", max_length=120)
    role: str = Field(default="viewer", pattern="^(viewer|operator|admin)$")


@app.get("/api-keys")
def list_api_keys(user: AuthenticatedUser = Depends(require_admin)) -> dict:
    return {"keys": api_keys_module.list_keys(user.username)}


@app.post("/api-keys", status_code=201)
def create_api_key(body: ApiKeyCreateRequest, request: Request, user: AuthenticatedUser = Depends(require_admin)) -> dict:
    plaintext, meta = api_keys_module.create(user.username, label=body.label, role=body.role)
    audit.log(
        action="api_key_created",
        user=user.username,
        ip=client_ip(request),
        resource="api_key",
        details={"key_id": meta["id"], "label": body.label, "role": body.role},
    )
    # New keys default to the free tier; admin can upgrade via PATCH /billing.
    billing_module.set_tier(meta["id"], billing_module.DEFAULT_TIER)
    return {"key": plaintext, "metadata": meta}


@app.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: str, request: Request, user: AuthenticatedUser = Depends(require_admin)) -> dict:
    if not api_keys_module.revoke(key_id, user.username):
        raise HTTPException(status_code=404, detail="API key not found")
    audit.log(
        action="api_key_revoked",
        user=user.username,
        ip=client_ip(request),
        resource="api_key",
        details={"key_id": key_id},
    )
    return {"ok": True}


# ── audit log viewer (admin-only) ─────────────────────────────────────────────

@app.get("/audit")
def get_audit_log(
    user_filter: str | None = None,
    action_filter: str | None = None,
    since: int | None = None,
    limit: int = 200,
    _: AuthenticatedUser = Depends(require_admin),
) -> dict:
    entries = audit.query(user=user_filter, action=action_filter, since=since, limit=limit)
    return {"entries": entries, "count": len(entries)}


# ── webhook subscriptions (admin-only) ───────────────────────────────────────

class WebhookCreateRequest(BaseModel):
    url: str = Field(min_length=8, max_length=400, pattern=r"^https?://")
    events: list[str] = Field(default_factory=lambda: ["optimize.completed"])
    label: str = Field(default="", max_length=120)


def _webhook_public(meta: dict) -> dict:
    return {
        "id":                meta["id"],
        "label":             meta["label"],
        "url":               meta["url"],
        "events":            meta["events"],
        "created_at":        meta["created_at"],
        "last_delivered_at": meta["last_delivered_at"],
        "last_status":       meta["last_status"],
        "last_error":        meta["last_error"],
        "disabled":          meta["disabled"],
    }


@app.get("/webhooks")
def list_webhooks(user: AuthenticatedUser = Depends(require_admin)) -> dict:
    items = [_webhook_public(h) for h in webhooks_module.list_for(user.username)]
    return {"webhooks": items, "known_events": list(webhooks_module.KNOWN_EVENTS)}


@app.post("/webhooks", status_code=201)
def create_webhook(
    body: WebhookCreateRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
) -> dict:
    secret, meta = webhooks_module.create(
        owner=user.username, url=body.url, events=body.events, label=body.label,
    )
    audit.log(
        action="webhook_created",
        user=user.username,
        ip=client_ip(request),
        resource="webhook",
        details={"hook_id": meta["id"], "url": body.url, "events": meta["events"]},
    )
    return {"secret": secret, "metadata": _webhook_public(meta)}


@app.delete("/webhooks/{hook_id}")
def delete_webhook(
    hook_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
) -> dict:
    if not webhooks_module.delete(hook_id, user.username):
        raise HTTPException(status_code=404, detail="webhook not found")
    audit.log(
        action="webhook_deleted",
        user=user.username,
        ip=client_ip(request),
        resource="webhook",
        details={"hook_id": hook_id},
    )
    return {"ok": True}


@app.post("/webhooks/{hook_id}/test")
def test_webhook(
    hook_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
) -> dict:
    hook = webhooks_module.get(hook_id)
    if hook is None or hook["owner"] != user.username:
        raise HTTPException(status_code=404, detail="webhook not found")
    payload = {
        "event": "ping",
        "delivered_at": int(__import__("time").time()),
        "message": "LogicVolt webhook test ping",
    }
    # Synchronous so the admin sees the immediate delivery status. We sign
    # with the *derived* signing key (SHA-256 of secret_hash), matching the
    # production dispatch path so subscribers can verify with the same code.
    derived = __import__("hashlib").sha256(hook["secret_hash"].encode()).hexdigest()
    status, error = webhooks_module.deliver_now(hook, derived, "ping", payload)
    audit.log(
        action="webhook_test",
        user=user.username,
        ip=client_ip(request),
        resource="webhook",
        details={"hook_id": hook_id, "status": status, "error": error},
    )
    return {"status": status, "error": error}


# ── billing / API plan ───────────────────────────────────────────────────────

class BillingUpdateRequest(BaseModel):
    tier: str = Field(pattern="^(free|pro|enterprise)$")


@app.get("/billing/tiers")
def list_tiers(_: AuthenticatedUser = Depends(require_viewer)) -> dict:
    return {"tiers": billing_module.all_tiers()}


@app.get("/billing/keys")
def billing_for_keys(user: AuthenticatedUser = Depends(require_admin)) -> dict:
    """Per-key billing snapshot: tier, monthly call counter, plan limits."""
    keys = api_keys_module.list_keys(user.username)
    out = []
    for key in keys:
        snapshot = billing_module.get(key["id"])
        tier = billing_module.tier_info(snapshot["tier"])
        out.append({
            "key_id":             key["id"],
            "prefix":             key["prefix"],
            "label":              key["label"],
            "role":               key["role"],
            "tier":               tier.name,
            "tier_label":         tier.label,
            "rate_limit":         tier.rate_limit,
            "monthly_call_quota": tier.monthly_call_quota,
            "monthly_calls":      snapshot["monthly_calls"],
            "period":             snapshot["period"],
            "can_use_webhooks":   tier.can_use_webhooks,
            "price_eur_month":    tier.price_eur_month,
        })
    return {"keys": out}


@app.patch("/billing/keys/{key_id}")
def update_key_tier(
    key_id: str,
    body: BillingUpdateRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
) -> dict:
    keys = api_keys_module.list_keys(user.username)
    if not any(k["id"] == key_id for k in keys):
        raise HTTPException(status_code=404, detail="API key not found")
    snapshot = billing_module.set_tier(key_id, body.tier)
    audit.log(
        action="billing_tier_changed",
        user=user.username,
        ip=client_ip(request),
        resource="billing",
        details={"key_id": key_id, "tier": body.tier},
    )
    return {"key_id": key_id, **snapshot}
