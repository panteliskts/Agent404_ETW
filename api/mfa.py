"""
TOTP-based Multi-Factor Authentication (RFC 6238).

Flow
----
Phase 1 — login:
  POST /auth/login  →  credentials OK, MFA enabled
                   →  { "mfa_required": true, "mfa_token": "<short-lived token>" }

Phase 2 — MFA verify:
  POST /auth/mfa/verify  { "mfa_token": "...", "totp_code": "123456" }
                        →  full session cookie set, normal login response

Setup (admin self-service):
  GET  /auth/mfa/setup   →  { "secret": "...", "qr_svg": "<svg>..." }
  POST /auth/mfa/enable  { "totp_code": "..." }  →  MFA activated
"""
from __future__ import annotations

import io
import secrets
import sqlite3
import threading
import time
from pathlib import Path

import pyotp
import qrcode
import qrcode.image.svg

_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "mfa.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn

    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mfa_secrets (
            username    TEXT    PRIMARY KEY,
            totp_secret TEXT    NOT NULL,
            enabled     INTEGER NOT NULL DEFAULT 0,
            created_at  INTEGER NOT NULL
        )
        """
    )
    # Short-lived pre-auth token issued between password-ok and TOTP verification.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mfa_pending (
            token      TEXT    PRIMARY KEY,
            username   TEXT    NOT NULL,
            expires_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    _conn = conn
    return _conn


# ── secret management ────────────────────────────────────────────────────────

def provision(username: str) -> str:
    """Generate a new TOTP secret for *username*. Resets existing secret."""
    secret = pyotp.random_base32()
    with _lock:
        _get_conn().execute(
            "INSERT OR REPLACE INTO mfa_secrets(username, totp_secret, enabled, created_at)"
            " VALUES (?,?,0,?)",
            (username, secret, int(time.time())),
        )
        _get_conn().commit()
    return secret


def get_provisioning_uri(username: str, issuer: str = "BESS Optimizer") -> str | None:
    with _lock:
        row = _get_conn().execute(
            "SELECT totp_secret FROM mfa_secrets WHERE username=?", (username,)
        ).fetchone()
    if not row:
        return None
    return pyotp.TOTP(row[0]).provisioning_uri(name=username, issuer_name=issuer)


def get_qr_svg(username: str, issuer: str = "BESS Optimizer") -> str | None:
    """Return an inline SVG QR-code for the authenticator app setup screen."""
    uri = get_provisioning_uri(username, issuer)
    if not uri:
        return None
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


# ── state queries ─────────────────────────────────────────────────────────────

def is_enabled(username: str) -> bool:
    with _lock:
        row = _get_conn().execute(
            "SELECT enabled FROM mfa_secrets WHERE username=?", (username,)
        ).fetchone()
    return bool(row and row[0])


# ── verification ─────────────────────────────────────────────────────────────

def verify(username: str, totp_code: str) -> bool:
    """Verify a TOTP code.  valid_window=1 allows ±30 s clock skew."""
    with _lock:
        row = _get_conn().execute(
            "SELECT totp_secret FROM mfa_secrets WHERE username=?", (username,)
        ).fetchone()
    if not row:
        return False
    return pyotp.TOTP(row[0]).verify(totp_code.strip(), valid_window=1)


def enable(username: str, totp_code: str) -> bool:
    """Verify code and mark MFA as active.  Returns False if code is wrong."""
    if not verify(username, totp_code):
        return False
    with _lock:
        _get_conn().execute(
            "UPDATE mfa_secrets SET enabled=1 WHERE username=?", (username,)
        )
        _get_conn().commit()
    return True


def disable(username: str) -> None:
    with _lock:
        _get_conn().execute(
            "UPDATE mfa_secrets SET enabled=0 WHERE username=?", (username,)
        )
        _get_conn().commit()


# ── pending (pre-auth) tokens ─────────────────────────────────────────────────

def create_pending_token(username: str, ttl_seconds: int = 300) -> str:
    """
    Issue a short-lived token after password verification.
    The client must exchange it for a full session via /auth/mfa/verify.
    """
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + ttl_seconds
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM mfa_pending WHERE expires_at < ?", (int(time.time()),))
        conn.execute(
            "INSERT INTO mfa_pending(token, username, expires_at) VALUES (?,?,?)",
            (token, username, expires_at),
        )
        conn.commit()
    return token


def consume_pending_token(token: str) -> str | None:
    """
    Validate and consume a pending MFA token.
    Returns the associated username or None if expired / not found.
    """
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT username, expires_at FROM mfa_pending WHERE token=?", (token,)
        ).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM mfa_pending WHERE token=?", (token,))
        conn.commit()

    if int(time.time()) > row[1]:
        return None
    return row[0]
