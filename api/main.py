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
from api import audit, mfa as mfa_module, api_keys as api_keys_module  # noqa: E402
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
        "q10": [_json_float(value) for value in predictions["q10"].to_numpy()],
        "q50": [_json_float(value) for value in predictions["q50"].to_numpy()],
        "q90": [_json_float(value) for value in predictions["q90"].to_numpy()],
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

    q10 = predictions["q10"]
    q50 = predictions["q50"]
    q90 = predictions["q90"]
    idle_mask = scheduler.compute_low_confidence_mask(q10, q90, battery=battery)
    schedule = scheduler.optimize(q50, battery=battery, idle_mask=idle_mask, solver_msg=False)
    schedule_df = schedule.to_frame()

    delta_h = float(schedule.delta_h)
    net_mw = schedule_df["discharge_mw"].to_numpy() - schedule_df["charge_mw"].to_numpy()
    throughput_mwh = (schedule_df["charge_mw"].to_numpy() + schedule_df["discharge_mw"].to_numpy()) * delta_h
    gross_revenue = float(np.sum(q50.to_numpy() * net_mw * delta_h))
    degradation = float(np.sum(battery.degradation_eur_per_mwh * throughput_mwh))
    net_profit = gross_revenue - degradation
    cycles_used = float(np.sum(schedule_df["discharge_mw"].to_numpy()) * delta_h / battery.energy_mwh)
    idle_aligned = idle_mask.reindex(schedule_df.index).fillna(False)

    rows = []
    for ts, row in schedule_df.iterrows():
        rows.append(
            {
                "time": _iso(ts),
                "charge_mw": float(row["charge_mw"]),
                "discharge_mw": float(row["discharge_mw"]),
                "net_mw": float(row["net_mw"]),
                "soc_mwh": float(row["soc_mwh"]),
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
