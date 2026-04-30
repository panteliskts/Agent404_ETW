"""API subscription tiers — a tiny, file-backed billing surface.

Each API key is associated with a tier. The tier defines:

* ``rate_limit`` — requests per minute (per key).
* ``can_use_webhooks`` — whether the key can register / receive webhooks.
* ``can_use_optimize`` — gates the paid endpoint.
* ``monthly_call_quota`` — soft cap surfaced on the dashboard.

Storage: a JSON sidecar (``data/billing.json``) keyed by api_key id with
``{tier, monthly_calls, period_start}``. Counts roll over each calendar
month. This is enough for a demo/hackathon — production would back this
with a metered billing system (Stripe, Lago, Orb).
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "billing.json"
_lock = threading.Lock()


@dataclass(frozen=True)
class Tier:
    name: str
    label: str
    rate_limit: int             # requests / minute
    monthly_call_quota: int     # soft quota per calendar month
    can_use_optimize: bool
    can_use_webhooks: bool
    price_eur_month: int


TIERS: dict[str, Tier] = {
    "free": Tier(
        name="free", label="Free",
        rate_limit=10, monthly_call_quota=500,
        can_use_optimize=False, can_use_webhooks=False,
        price_eur_month=0,
    ),
    "payg": Tier(
        name="payg", label="Pay-as-you-go",
        rate_limit=60, monthly_call_quota=0,          # 0 = unlimited (metered)
        can_use_optimize=True, can_use_webhooks=False,
        price_eur_month=0,                            # €0 base + €0.08 / optimize call
    ),
    "pro": Tier(
        name="pro", label="Pro",
        rate_limit=120, monthly_call_quota=50_000,
        can_use_optimize=True, can_use_webhooks=True,
        price_eur_month=499,
    ),
    "enterprise": Tier(
        name="enterprise", label="Enterprise",
        rate_limit=600, monthly_call_quota=1_000_000,
        can_use_optimize=True, can_use_webhooks=True,
        price_eur_month=2_499,
    ),
}
DEFAULT_TIER = "free"

# Per-call price in EUR cents for metered tiers (key = tier name).
PAYG_PRICE_EUR_CENTS: dict[str, int] = {
    "payg": 8,   # €0.08 per /optimize call
}


def _period_key(now: int | None = None) -> str:
    t = time.gmtime(now if now is not None else int(time.time()))
    return f"{t.tm_year:04d}-{t.tm_mon:02d}"


def _load() -> dict:
    if not _DB_PATH.exists():
        return {}
    try:
        return json.loads(_DB_PATH.read_text() or "{}")
    except json.JSONDecodeError:
        return {}


def _save(data: dict) -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DB_PATH.write_text(json.dumps(data, indent=2, sort_keys=True))


def get(key_id: str) -> dict:
    """Return ``{tier, monthly_calls, period}`` for the key, defaulting to free."""
    with _lock:
        data = _load()
        record = data.get(key_id) or {}
    period = _period_key()
    monthly_calls = int(record.get("monthly_calls", 0)) if record.get("period") == period else 0
    return {
        "tier":          record.get("tier", DEFAULT_TIER),
        "monthly_calls": monthly_calls,
        "period":        period,
    }


def set_tier(key_id: str, tier: str) -> dict:
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    with _lock:
        data = _load()
        rec = data.get(key_id) or {}
        rec["tier"] = tier
        rec.setdefault("period", _period_key())
        rec.setdefault("monthly_calls", 0)
        data[key_id] = rec
        _save(data)
    return get(key_id)


def record_call(key_id: str) -> dict:
    """Increment the monthly counter, rolling over on month boundary."""
    period = _period_key()
    with _lock:
        data = _load()
        rec = data.get(key_id) or {"tier": DEFAULT_TIER, "period": period, "monthly_calls": 0}
        if rec.get("period") != period:
            rec["period"] = period
            rec["monthly_calls"] = 0
        rec["monthly_calls"] = int(rec.get("monthly_calls", 0)) + 1
        data[key_id] = rec
        _save(data)
    return {"tier": rec["tier"], "monthly_calls": rec["monthly_calls"], "period": period}


def tier_info(name: str) -> Tier:
    return TIERS.get(name, TIERS[DEFAULT_TIER])


def all_tiers() -> list[dict]:
    return [
        {
            "name": t.name,
            "label": t.label,
            "rate_limit": t.rate_limit,
            "monthly_call_quota": t.monthly_call_quota,
            "can_use_optimize": t.can_use_optimize,
            "can_use_webhooks": t.can_use_webhooks,
            "price_eur_month": t.price_eur_month,
            "payg_price_eur_cents": PAYG_PRICE_EUR_CENTS.get(t.name),
        }
        for t in TIERS.values()
    ]
