"""
OAuth 2.0 / OpenID Connect (OIDC) SSO integration.

Supported identity providers
-----------------------------
* Microsoft Entra ID (Azure AD) — enterprise default
* Google Workspace

Required environment variables (per provider)
---------------------------------------------
Microsoft:
    AZURE_TENANT_ID       e.g. "contoso.onmicrosoft.com" or tenant GUID
    AZURE_CLIENT_ID       Application (client) ID from Entra App Registration
    AZURE_CLIENT_SECRET   Client secret from Entra App Registration

Google:
    GOOGLE_CLIENT_ID      OAuth 2.0 client ID from Google Cloud Console
    GOOGLE_CLIENT_SECRET  OAuth 2.0 client secret

Common:
    APP_PUBLIC_URL        Base URL of the API server, e.g. "https://api.bess.example.com"
    APP_FRONTEND_URL      Where to redirect after successful login, e.g. "https://bess.example.com"
    OIDC_ALLOWED_DOMAINS  Comma-separated list of permitted email domains, e.g. "example.com,partner.com"
    OIDC_DEFAULT_ROLE     Role assigned to SSO users: "viewer" | "operator" | "admin"  (default: viewer)

Mounting
--------
    from api.oauth import router as oidc_router
    app.include_router(oidc_router, prefix="/auth/oidc")

Then direct enterprise users to:
    GET /auth/oidc/login?provider=microsoft
    GET /auth/oidc/login?provider=google
"""
from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.responses import RedirectResponse

from api.security import create_session_token, set_auth_cookies

router = APIRouter(tags=["oidc"])


# ── provider configs ──────────────────────────────────────────────────────────

def _microsoft_cfg() -> dict:
    tenant = os.getenv("AZURE_TENANT_ID", "common")
    return {
        "client_id":     os.getenv("AZURE_CLIENT_ID", ""),
        "client_secret": os.getenv("AZURE_CLIENT_SECRET", ""),
        "auth_url":      f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token_url":     f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "userinfo_url":  "https://graph.microsoft.com/v1.0/me",
        "scopes":        "openid profile email User.Read",
    }


def _google_cfg() -> dict:
    return {
        "client_id":     os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
        "auth_url":      "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url":     "https://oauth2.googleapis.com/token",
        "userinfo_url":  "https://www.googleapis.com/oauth2/v3/userinfo",
        "scopes":        "openid profile email",
    }


_PROVIDERS: dict[str, object] = {
    "microsoft": _microsoft_cfg,
    "google":    _google_cfg,
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _callback_uri(request: Request, provider: str) -> str:
    base = os.getenv("APP_PUBLIC_URL", str(request.base_url).rstrip("/"))
    return f"{base}/auth/oidc/callback/{provider}"


def _extract_email(info: dict, provider: str) -> str:
    if provider == "microsoft":
        return info.get("mail") or info.get("userPrincipalName") or info.get("email", "")
    return info.get("email", "")


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/login")
def oidc_login(provider: str, request: Request) -> RedirectResponse:
    """Redirect the browser to the IdP authorization endpoint."""
    if provider not in _PROVIDERS:
        raise HTTPException(400, detail=f"Unknown provider. Valid: {list(_PROVIDERS)}")

    cfg = _PROVIDERS[provider]()  # type: ignore[operator]
    if not cfg["client_id"]:
        raise HTTPException(503, detail=f"Provider '{provider}' is not configured")

    # In production: persist *state* in a short-lived server-side store
    # (e.g. Redis TTL=10 min) to validate the callback and prevent CSRF.
    state = secrets.token_urlsafe(16)

    params = {
        "client_id":     cfg["client_id"],
        "response_type": "code",
        "redirect_uri":  _callback_uri(request, provider),
        "scope":         cfg["scopes"],
        "state":         state,
        "prompt":        "select_account",
    }
    return RedirectResponse(f"{cfg['auth_url']}?{urlencode(params)}")


@router.get("/callback/{provider}")
async def oidc_callback(
    provider: str,
    code: str,
    state: str,
    request: Request,
    response: Response,
) -> RedirectResponse:
    """Exchange the authorization code for tokens and create a session."""
    if provider not in _PROVIDERS:
        raise HTTPException(400, detail="Unknown provider")

    cfg = _PROVIDERS[provider]()  # type: ignore[operator]

    # ── token exchange ───────────────────────────────────────────────────────
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            cfg["token_url"],
            data={
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  _callback_uri(request, provider),
                "client_id":     cfg["client_id"],
                "client_secret": cfg["client_secret"],
            },
            headers={"Accept": "application/json"},
        )
    if not token_resp.is_success:
        raise HTTPException(502, detail="Token exchange with IdP failed")

    access_token = token_resp.json().get("access_token", "")

    # ── user-info ────────────────────────────────────────────────────────────
    async with httpx.AsyncClient(timeout=15) as client:
        info_resp = await client.get(
            cfg["userinfo_url"],
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if not info_resp.is_success:
        raise HTTPException(502, detail="User-info fetch from IdP failed")

    info  = info_resp.json()
    email = _extract_email(info, provider)
    if not email:
        raise HTTPException(502, detail="IdP did not return an email address")

    # ── domain allow-list ────────────────────────────────────────────────────
    allowed_raw = os.getenv("OIDC_ALLOWED_DOMAINS", "")
    if allowed_raw:
        allowed = {d.strip() for d in allowed_raw.split(",") if d.strip()}
        domain  = email.split("@")[-1]
        if domain not in allowed:
            raise HTTPException(403, detail="Your organisation is not permitted to access this platform")

    # ── session ──────────────────────────────────────────────────────────────
    role = os.getenv("OIDC_DEFAULT_ROLE", "viewer")
    session_token, csrf_token, expires_at = create_session_token(email, role=role)
    set_auth_cookies(response, session_token, csrf_token, expires_at)

    frontend_url = os.getenv("APP_FRONTEND_URL", "/")
    return RedirectResponse(frontend_url, status_code=302)
