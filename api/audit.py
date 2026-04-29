"""
WORM audit log backed by SQLite.

Tamper-resistance is enforced at two levels:
  1. A SQLite authorizer (set_authorizer) that rejects UPDATE and DELETE at the
     Python driver level for the connection returned by _get_conn().
  2. The SQLite file is opened without WAL journaling to prevent easy rollback.

For production deployments that require stronger guarantees (e.g. REMIT/MAD
compliance), mirror entries to an immutable object-store (S3 Object Lock,
Azure Immutable Blob) or a managed audit service such as AWS CloudTrail.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "audit.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

# SQLite action codes that are safe for a write-once log.
_PERMITTED_ACTIONS = {
    sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_TRANSACTION,
    sqlite3.SQLITE_ATTACH,
    sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_SCHEMA,
    sqlite3.SQLITE_PRAGMA,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}


def _worm_authorizer(action: int, *_: Any) -> int:
    return sqlite3.SQLITE_OK if action in _PERMITTED_ACTIONS else sqlite3.SQLITE_DENY


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn

    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)

    # Schema bootstrap — run before attaching the WORM authorizer because
    # CREATE TABLE / CREATE INDEX internally write to sqlite_master.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         INTEGER NOT NULL,
            user_id    TEXT    NOT NULL,
            action     TEXT    NOT NULL,
            resource   TEXT    NOT NULL DEFAULT '',
            ip_address TEXT    NOT NULL DEFAULT '',
            details    TEXT    NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts   ON audit_log(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)")
    conn.commit()

    # Attach WORM authorizer after schema is ready — blocks UPDATE / DELETE
    # for all subsequent runtime queries.
    conn.set_authorizer(_worm_authorizer)

    _conn = conn
    return _conn


def log(
    *,
    action: str,
    user: str,
    ip: str = "",
    resource: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    """Append a tamper-resistant audit entry (INSERT-only)."""
    entry = json.dumps(details or {}, separators=(",", ":"))
    with _lock:
        _get_conn().execute(
            "INSERT INTO audit_log(ts, user_id, action, resource, ip_address, details)"
            " VALUES (?,?,?,?,?,?)",
            (int(time.time()), user, action, resource, ip, entry),
        )
        _get_conn().commit()


def query(
    *,
    user: str | None = None,
    action: str | None = None,
    since: int | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Read audit entries (SELECT-only). Returns newest-first."""
    clauses: list[str] = []
    params: list[Any] = []

    if user:
        clauses.append("user_id = ?")
        params.append(user)
    if action:
        clauses.append("action = ?")
        params.append(action)
    if since:
        clauses.append("ts >= ?")
        params.append(since)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        f"SELECT id, ts, user_id, action, resource, ip_address, details"
        f" FROM audit_log {where} ORDER BY ts DESC LIMIT ?"
    )
    params.append(max(1, min(limit, 5000)))

    with _lock:
        rows = _get_conn().execute(sql, params).fetchall()

    return [
        {
            "id": r[0],
            "timestamp": r[1],
            "user": r[2],
            "action": r[3],
            "resource": r[4],
            "ip": r[5],
            "details": json.loads(r[6]),
        }
        for r in rows
    ]
