from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable

from fastapi import HTTPException, Request
from starlette.responses import Response

SESSION_COOKIE = "bess_session"
CSRF_COOKIE = "bess_csrf"
CSRF_HEADER = "x-csrf-token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class AuthenticatedUser:
    username: str
    csrf_token: str


@dataclass(frozen=True)
class SecuritySettings:
    username: str
    password: str
    password_hash: str
    secret_key: str
    session_seconds: int
    cookie_secure: bool
    allowed_origins: list[str]
    allowed_hosts: list[str]
    rate_limit_requests: int
    rate_limit_window_seconds: int
    login_rate_limit_requests: int
    login_rate_limit_window_seconds: int


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def load_security_settings() -> SecuritySettings:
    secret_key = os.getenv("APP_SECRET_KEY", "")
    if not secret_key:
        secret_key = secrets.token_urlsafe(48)

    return SecuritySettings(
        username=os.getenv("APP_AUTH_USERNAME", "admin"),
        password=os.getenv("APP_AUTH_PASSWORD", "admin"),
        password_hash=os.getenv("APP_AUTH_PASSWORD_HASH", ""),
        secret_key=secret_key,
        session_seconds=int(os.getenv("APP_SESSION_SECONDS", str(8 * 60 * 60))),
        cookie_secure=os.getenv("APP_COOKIE_SECURE", "false").lower() == "true",
        allowed_origins=_split_csv(
            os.getenv("APP_ALLOWED_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000")
        ),
        allowed_hosts=_split_csv(os.getenv("APP_ALLOWED_HOSTS", "127.0.0.1,localhost")),
        rate_limit_requests=int(os.getenv("APP_RATE_LIMIT_REQUESTS", "240")),
        rate_limit_window_seconds=int(os.getenv("APP_RATE_LIMIT_WINDOW_SECONDS", "60")),
        login_rate_limit_requests=int(os.getenv("APP_LOGIN_RATE_LIMIT_REQUESTS", "8")),
        login_rate_limit_window_seconds=int(os.getenv("APP_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60")),
    )


settings = load_security_settings()


class InMemoryRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        window_start = now - self.window_seconds
        timestamps = self._requests[key]

        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        if len(timestamps) >= self.max_requests:
            retry_after = max(1, int(timestamps[0] + self.window_seconds - now))
            return False, retry_after

        timestamps.append(now)
        return True, 0


api_rate_limiter = InMemoryRateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds)
login_rate_limiter = InMemoryRateLimiter(
    settings.login_rate_limit_requests,
    settings.login_rate_limit_window_seconds,
)


def client_ip(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


def security_headers() -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        "Cache-Control": "no-store",
    }
    if settings.cookie_secure:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _sign(value: str) -> str:
    signature = hmac.new(settings.secret_key.encode("utf-8"), value.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(signature)


def create_session_token(username: str) -> tuple[str, str, int]:
    now = int(time.time())
    expires_at = now + settings.session_seconds
    csrf_token = secrets.token_urlsafe(32)
    payload = {
        "csrf": csrf_token,
        "exp": expires_at,
        "iat": now,
        "sub": username,
    }
    payload_segment = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{payload_segment}.{_sign(payload_segment)}", csrf_token, expires_at


def decode_session_token(token: str | None) -> dict | None:
    if not token:
        return None

    try:
        payload_segment, signature_segment = token.split(".", 1)
    except ValueError:
        return None

    expected_signature = _sign(payload_segment)
    if not hmac.compare_digest(signature_segment, expected_signature):
        return None

    try:
        payload = json.loads(_b64decode(payload_segment))
    except (ValueError, binascii.Error, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    if int(payload.get("exp", 0)) < int(time.time()):
        return None

    username = payload.get("sub")
    csrf_token = payload.get("csrf")
    if not isinstance(username, str) or not isinstance(csrf_token, str):
        return None
    return payload


def set_auth_cookies(response: Response, session_token: str, csrf_token: str, expires_at: int) -> None:
    max_age = max(0, expires_at - int(time.time()))
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        httponly=True,
        max_age=max_age,
        path="/",
        samesite="lax",
        secure=settings.cookie_secure,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        max_age=max_age,
        path="/",
        samesite="lax",
        secure=settings.cookie_secure,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax", secure=settings.cookie_secure)
    response.delete_cookie(CSRF_COOKIE, path="/", samesite="lax", secure=settings.cookie_secure)


def password_hash_for_env(password: str, iterations: int = 260_000) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def _verify_password_hash(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = encoded_hash.split("$", 3)
        iterations = int(iterations_raw)
    except (ValueError, binascii.Error):
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    try:
        salt = _b64decode(salt_raw)
        expected_digest = _b64decode(digest_raw)
    except ValueError:
        return False

    actual_digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual_digest, expected_digest)


def verify_credentials(username: str, password: str) -> bool:
    if not hmac.compare_digest(username, settings.username):
        return False
    if settings.password_hash:
        return _verify_password_hash(password, settings.password_hash)
    return hmac.compare_digest(password, settings.password)


def require_user(request: Request) -> AuthenticatedUser:
    payload = decode_session_token(request.cookies.get(SESSION_COOKIE))
    if payload is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    if request.method.upper() in UNSAFE_METHODS:
        csrf_header = request.headers.get(CSRF_HEADER, "")
        csrf_token = str(payload.get("csrf", ""))
        if not csrf_header or not hmac.compare_digest(csrf_header, csrf_token):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")

    return AuthenticatedUser(username=str(payload["sub"]), csrf_token=str(payload["csrf"]))


def set_headers(response: Response, headers: Iterable[tuple[str, str]] | dict[str, str]) -> None:
    items = headers.items() if isinstance(headers, dict) else headers
    for key, value in items:
        response.headers[key] = value
