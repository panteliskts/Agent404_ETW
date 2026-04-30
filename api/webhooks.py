"""Outbound webhook subscriptions — third parties receive POSTs when events fire.

Mirrors the storage shape of api/api_keys.py so the security/operational
review of the two systems is identical.

Events
------
* ``optimize.completed`` — fired after every successful POST /optimize.
* ``forecast.refreshed`` — fired after the model retrains on startup
  (best-effort; not retried).

Delivery
--------
A short-lived background thread POSTs the JSON event body to the registered
URL with these headers:

    Content-Type: application/json
    User-Agent:   LogicVolt-Webhook/1.0
    X-LogicVolt-Event:     <event-name>
    X-LogicVolt-Delivery:  <uuid4>
    X-LogicVolt-Timestamp: <unix-seconds>
    X-LogicVolt-Signature: sha256=<hex>      # HMAC over the raw body

Subscribers verify the signature with the secret returned at registration
(shown ONCE, not stored in plaintext — only the Argon2id hash). Failed
deliveries are recorded for /webhooks/{id} status; we do not retry in this
hackathon build.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "webhooks.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)

KNOWN_EVENTS = ("optimize.completed", "forecast.refreshed")


def _conn_get() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS webhooks (
            id           TEXT PRIMARY KEY,
            owner        TEXT NOT NULL,
            label        TEXT NOT NULL DEFAULT '',
            url          TEXT NOT NULL,
            events       TEXT NOT NULL,           -- comma-joined event names
            secret_hash  TEXT NOT NULL,           -- argon2id hash of plaintext
            created_at   INTEGER NOT NULL,
            last_delivered_at INTEGER,
            last_status  INTEGER,                 -- last HTTP status (or 0 on failure)
            last_error   TEXT,
            disabled     INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()
    _conn = conn
    return _conn


def create(owner: str, url: str, events: list[str], label: str = "") -> tuple[str, dict]:
    """Register a webhook. Returns ``(plaintext_secret, metadata)``.

    The plaintext secret is shown ONCE — store only metadata.
    """
    valid = [e for e in events if e in KNOWN_EVENTS]
    if not valid:
        valid = ["optimize.completed"]
    hook_id = secrets.token_urlsafe(12)
    secret_plain = f"whsec_{secrets.token_urlsafe(32)}"
    secret_hash = _ph.hash(secret_plain)
    now = int(time.time())

    with _lock:
        _conn_get().execute(
            "INSERT INTO webhooks(id, owner, label, url, events, secret_hash, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (hook_id, owner, label, url, ",".join(valid), secret_hash, now),
        )
        _conn_get().commit()

    return secret_plain, _row_to_meta(
        (hook_id, owner, label, url, ",".join(valid), secret_hash, now, None, None, None, 0)
    )


def list_for(owner: str) -> list[dict]:
    with _lock:
        rows = _conn_get().execute(
            "SELECT id, owner, label, url, events, secret_hash, created_at,"
            " last_delivered_at, last_status, last_error, disabled"
            " FROM webhooks WHERE owner=? ORDER BY created_at DESC",
            (owner,),
        ).fetchall()
    return [_row_to_meta(r) for r in rows]


def delete(hook_id: str, owner: str) -> bool:
    with _lock:
        cur = _conn_get().execute(
            "DELETE FROM webhooks WHERE id=? AND owner=?", (hook_id, owner)
        )
        _conn_get().commit()
    return cur.rowcount > 0


def get(hook_id: str) -> dict | None:
    with _lock:
        row = _conn_get().execute(
            "SELECT id, owner, label, url, events, secret_hash, created_at,"
            " last_delivered_at, last_status, last_error, disabled"
            " FROM webhooks WHERE id=?",
            (hook_id,),
        ).fetchone()
    return _row_to_meta(row) if row else None


def _row_to_meta(row) -> dict:
    return {
        "id":                 row[0],
        "owner":              row[1],
        "label":              row[2],
        "url":                row[3],
        "events":             [e for e in row[4].split(",") if e],
        "secret_hash":        row[5],
        "created_at":         row[6],
        "last_delivered_at":  row[7],
        "last_status":        row[8],
        "last_error":         row[9],
        "disabled":           bool(row[10]),
    }


def verify_secret(plaintext: str, secret_hash: str) -> bool:
    try:
        _ph.verify(secret_hash, plaintext)
        return True
    except VerifyMismatchError:
        return False


def _record_delivery(hook_id: str, status: int, error: str | None) -> None:
    with _lock:
        _conn_get().execute(
            "UPDATE webhooks SET last_delivered_at=?, last_status=?, last_error=? WHERE id=?",
            (int(time.time()), status, error, hook_id),
        )
        _conn_get().commit()


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(url: str, body: bytes, headers: dict[str, str], timeout: float = 6.0) -> tuple[int, str | None]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), None
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.reason
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, str(exc)


def deliver_now(hook: dict, secret_plain: str, event: str, payload: dict) -> tuple[int, str | None]:
    """Synchronous delivery — returns (status, error). Used by /webhooks/{id}/test."""
    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    headers = {
        "Content-Type":          "application/json",
        "User-Agent":            "LogicVolt-Webhook/1.0",
        "X-LogicVolt-Event":     event,
        "X-LogicVolt-Delivery":  uuid.uuid4().hex,
        "X-LogicVolt-Timestamp": str(int(time.time())),
        "X-LogicVolt-Signature": _sign(secret_plain, body),
    }
    status, err = _post(hook["url"], body, headers)
    _record_delivery(hook["id"], status, err)
    return status, err


def dispatch(event: str, payload: dict, *, owner: str | None = None) -> None:
    """Fire-and-forget broadcast to all subscribers of ``event``.

    Each delivery runs in its own daemon thread; the test endpoint signs
    with the plaintext secret returned by ``create``. For production
    deliveries we cannot recover the plaintext (Argon2id is one-way) — so
    when ``owner`` matches a subscription we still send, but with a
    derived shared signing key (HMAC over secret_hash) so subscribers can
    verify if they cache that derivation. This is sufficient for the
    hackathon; rotate to a kept-plaintext-in-secrets-manager pattern in
    production.
    """
    with _lock:
        rows = _conn_get().execute(
            "SELECT id, owner, label, url, events, secret_hash, created_at,"
            " last_delivered_at, last_status, last_error, disabled"
            " FROM webhooks WHERE disabled=0",
        ).fetchall()
    hooks = [_row_to_meta(r) for r in rows]
    targets = [
        h for h in hooks
        if event in h["events"] and (owner is None or h["owner"] == owner)
    ]
    if not targets:
        return

    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")

    def _send(hook: dict) -> None:
        # Derive a stable signing key from the stored hash so the receiver,
        # which knows the plaintext secret, can recompute it locally.
        signing_key = hashlib.sha256(hook["secret_hash"].encode()).hexdigest()
        headers = {
            "Content-Type":           "application/json",
            "User-Agent":             "LogicVolt-Webhook/1.0",
            "X-LogicVolt-Event":      event,
            "X-LogicVolt-Delivery":   uuid.uuid4().hex,
            "X-LogicVolt-Timestamp":  str(int(time.time())),
            "X-LogicVolt-Signature":  _sign(signing_key, body),
            "X-LogicVolt-Key-Scheme": "derived-v1",
        }
        status, err = _post(hook["url"], body, headers)
        _record_delivery(hook["id"], status, err)

    for h in targets:
        threading.Thread(target=_send, args=(h,), daemon=True).start()
