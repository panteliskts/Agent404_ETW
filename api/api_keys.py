"""
API key management for machine-to-machine access (SCADA / external systems).

Security properties
-------------------
* Keys are shown to the user exactly once upon creation — the plaintext is never
  stored.  Only an Argon2id hash is persisted.
* Keys carry a role (defaulting to "viewer") that is enforced by RBAC.
* A short prefix (first 8 chars after "bk_") is stored in plain text to allow
  O(1) hash lookup without scanning all rows.
* Revoking a key sets revoked=1; the row is kept for audit purposes.

Usage (Authorization header):
    Authorization: Bearer bk_<prefix>_<secret>
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerifyMismatchError

_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "api_keys.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)
_PREFIX_LEN = 8


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn

    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id         TEXT    PRIMARY KEY,
            prefix     TEXT    NOT NULL,
            hash       TEXT    NOT NULL,
            owner      TEXT    NOT NULL,
            label      TEXT    NOT NULL DEFAULT '',
            role       TEXT    NOT NULL DEFAULT 'viewer',
            created_at INTEGER NOT NULL,
            last_used  INTEGER,
            revoked    INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prefix ON api_keys(prefix)")
    conn.commit()
    _conn = conn
    return _conn


def create(owner: str, label: str = "", role: str = "viewer") -> tuple[str, dict]:
    """
    Generate a new API key.

    Returns ``(plaintext_key, metadata)``.
    The plaintext key is shown ONCE — store only the returned metadata dict.
    """
    key_id = secrets.token_urlsafe(12)
    prefix = secrets.token_urlsafe(_PREFIX_LEN)[:_PREFIX_LEN]
    body   = secrets.token_urlsafe(32)
    plaintext = f"bk_{prefix}_{body}"
    key_hash  = _ph.hash(plaintext)
    now = int(time.time())

    with _lock:
        _get_conn().execute(
            "INSERT INTO api_keys(id, prefix, hash, owner, label, role, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (key_id, prefix, key_hash, owner, label, role, now),
        )
        _get_conn().commit()

    return plaintext, {
        "id":         key_id,
        "prefix":     f"bk_{prefix}_...",
        "owner":      owner,
        "label":      label,
        "role":       role,
        "created_at": now,
    }


def verify_key(plaintext_key: str) -> dict | None:
    """
    Validate an API key and return its metadata, or ``None`` if invalid/revoked.
    Updates ``last_used`` on success.
    """
    if not plaintext_key.startswith("bk_"):
        return None
    parts = plaintext_key.split("_", 2)
    if len(parts) < 3:
        return None
    prefix = parts[1]

    with _lock:
        rows = _get_conn().execute(
            "SELECT id, hash, owner, label, role, revoked FROM api_keys WHERE prefix=?",
            (prefix,),
        ).fetchall()

    for row in rows:
        key_id, key_hash, owner, label, role, revoked = row
        if revoked:
            continue
        try:
            _ph.verify(key_hash, plaintext_key)
        except VerifyMismatchError:
            continue

        with _lock:
            _get_conn().execute(
                "UPDATE api_keys SET last_used=? WHERE id=?",
                (int(time.time()), key_id),
            )
            _get_conn().commit()

        return {"id": key_id, "owner": owner, "label": label, "role": role}

    return None


def revoke(key_id: str, owner: str) -> bool:
    """Revoke a key.  Returns True if a row was updated."""
    with _lock:
        cur = _get_conn().execute(
            "UPDATE api_keys SET revoked=1 WHERE id=? AND owner=?",
            (key_id, owner),
        )
        _get_conn().commit()
    return cur.rowcount > 0


def list_keys(owner: str) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT id, prefix, label, role, created_at, last_used, revoked"
            " FROM api_keys WHERE owner=? ORDER BY created_at DESC",
            (owner,),
        ).fetchall()
    return [
        {
            "id":         r[0],
            "prefix":     f"bk_{r[1]}_...",
            "label":      r[2],
            "role":       r[3],
            "created_at": r[4],
            "last_used":  r[5],
            "revoked":    bool(r[6]),
        }
        for r in rows
    ]
