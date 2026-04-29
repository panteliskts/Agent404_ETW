# BESS Optimizer — Build Progress

## Architecture

```
ETW/
├── app.py                  # Streamlit dashboard (entry point)
├── api/
│   ├── main.py             # FastAPI service + all endpoints
│   ├── security.py         # HMAC session tokens, CSRF, rate limiter, password hashing
│   ├── rbac.py             # Role-Based Access Control (viewer / operator / admin)
│   ├── audit.py            # WORM append-only SQLite audit log
│   ├── mfa.py              # TOTP / RFC 6238 MFA with QR code provisioning
│   ├── api_keys.py         # Argon2id-hashed API keys for SCADA integration
│   ├── encryption.py       # AES-256-GCM encryption for secrets at rest
│   ├── oauth.py            # OAuth 2.0 / OIDC SSO (Microsoft Entra + Google)
│   └── requirements.txt    # API-only deps: fastapi, uvicorn, pydantic + security libs
├── nginx/
│   └── nginx.conf          # TLS 1.3-only reverse proxy, HSTS, WSS, rate-limit zones
├── config.py               # BatterySpec, paths, locations
├── requirements.txt        # All dependencies
├── frontend/               # Next.js 14 + TypeScript + Tailwind + Recharts app
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx        # Main BESS optimizer dashboard
│   │   └── globals.css
│   ├── lib/api.ts          # Typed API client
│   ├── types/api.ts        # Shared frontend API response/request types
│   └── package.json
├── data/
│   ├── raw/                # Source parquets (weather fetched, ENTSO-E pending)
│   ├── cache/              # Live-fetch cache (auto-written by data_sources.py)
│   ├── demo/               # Synthetic demo parquet (auto-generated)
│   └── processed/          # Engineered feature parquet (from scripts/02)
├── models/                 # Saved LightGBM models (lgbm_q10/q50/q90)
├── notebooks/              # EDA notebooks
├── reports/                # Backtest CSVs + summary JSON
├── scripts/
│   ├── 01_fetch_data.py    # Pull ENTSO-E + weather + fuels → data/raw/
│   ├── 02_build_features.py
│   ├── 03_train.py
│   └── 04_backtest.py
└── src/
    ├── data_sources.py     # 3-tier fallback: live → cache → demo
    ├── features.py         # build_dataset() + engineer_features(df)
    ├── forecaster.py       # LightGBM point + quantile (q10/q50/q90)
    ├── scheduler.py        # PuLP LP + spread-filter idle mask
    ├── evaluate.py         # Day-by-day backtest + capture ratio
    └── data/
        ├── entsoe_client.py
        ├── fuels.py        # TTF + EUA via yfinance
        └── weather.py      # Open-Meteo archive + forecast
```

---

## Phase 0 — Environment & Data

| Task | Status | Notes |
|------|--------|-------|
| Repo structure (`src/`, `data/demo/`, `data/cache/`, `notebooks/`) | ✅ | All dirs created |
| `requirements.txt` pinned | ✅ | Added `streamlit`, `plotly`, `joblib` |
| venv with all deps | ✅ | `venv/` in root; install with `pip install -r requirements.txt` |
| Real weather data | ✅ | `data/raw/weather_2024-01-01_2026-04-29.parquet` (20 400 rows, 28 cols) |
| Synthetic demo dataset | ✅ | Auto-generated on first app launch → `data/demo/market_demo.parquet` |
| `src/data_sources.py` — 3-tier fallback | ✅ | live API → cache → demo; returns `(df, source_label)` |
| ENTSO-E DAM prices (real) | ⏳ | Needs `ENTSOE_API_KEY` in `.env`; run `scripts/01_fetch_data.py` |
| TTF / EUA prices (real) | ⏳ | Fetched by `src/data/fuels.py` via yfinance when online |

---

## Phase 1 — Hackathon MVP

### Hours 0–6: Feature Engineering

| Task | Status | Notes |
|------|--------|-------|
| `build_dataset()` — loads from raw parquets | ✅ | Original pipeline |
| `engineer_features(df)` — works on any DataFrame | ✅ | Added to `src/features.py` |
| Calendar features (hour, dow, sin/cos cyclical) | ✅ | |
| Lag features (lag-1/4/8/24/48/96/672) | ✅ | 15-min period lags |
| Rolling mean/std (windows 4/16/96) | ✅ | |
| Residual load + Greek midday/evening windows | ✅ | EveningRamp feature included |
| CCGT SRMC proxy (`ttf * 2.0 + eua * 0.37`) | ✅ | |

### Hours 6–14: Forecasting

| Task | Status | Notes |
|------|--------|-------|
| LightGBM point-estimate model | ✅ | `src/forecaster.py` — `train()` |
| Time-based train/valid/test split (no leakage) | ✅ | `time_split()` |
| Quantile models q10 / q50 / q90 | ✅ | `train_quantile()`, `train_all_quantiles()` |
| Save models to `models/lgbm_q*.txt` | ✅ | `TrainResult.save()` |
| Load pre-trained models from disk | ✅ | `load_quantile_models()` |
| `predict_interval(models, features)` → q10/q50/q90 | ✅ | Returns DataFrame |
| MAE logged on test set | ✅ | Stored in `metrics` dict |

### Hours 14–24: Optimizer

| Task | Status | Notes |
|------|--------|-------|
| PuLP LP with binary no-simultaneous-charge/discharge | ✅ | `src/scheduler.py` |
| SoC transition constraint | ✅ | |
| Cyclic terminal SoC constraint | ✅ | Hard equality (relaxable) |
| Max cycles/day constraint | ✅ | |
| **Spread filter** — `compute_low_confidence_mask()` | ✅ | Threshold = deg_cost + (1−√RTE)×mean_price |
| `idle_mask` parameter in `optimize()` | ✅ | Forces ch=dis=0 on low-confidence MTUs |
| `realized_revenue()` for backtest | ✅ | |

### Hours 24–34: Dashboard

| Task | Status | Notes |
|------|--------|-------|
| Streamlit `app.py` — full dashboard | ✅ | |
| Sidebar: battery sliders + data-source badge | ✅ | |
| KPI row: Net Profit / Gross Revenue / Degradation / Cycles | ✅ | |
| Price forecast plot (actual + q50 + q10/q90 band) | ✅ | Plotly |
| Schedule plot (charge/discharge/net + grey idle bars) | ✅ | Spread-filter visualised |
| SoC trajectory (min/max bounds as dashed lines) | ✅ | |
| Feature importance (expandable) | ✅ | Q50 model, top 20 by gain |
| Works fully offline (demo data) | ✅ | `@st.cache_data` + `@st.cache_resource` |

### Hours 34–42: Robustness

| Task | Status | Notes |
|------|--------|-------|
| Derating scenarios (Base / Mild / Severe) | ✅ | Sidebar dropdown; reruns optimizer |
| Internet-disconnect test | ⏳ | Test manually before demo |
| Offline demo smoke test | ⏳ | Run `streamlit run app.py` with no `.env` |

---

## Phase 2 — FastAPI + React Web App

### Backend API

| Task | Status | Notes |
|------|--------|-------|
| `api/main.py` FastAPI app | ✅ | Imports existing `src/` logic without modifying Python core |
| CORS for frontend dev port | ✅ | Allows all origins during development |
| Startup data cache | ✅ | Calls `load_market_data()` then `engineer_features()` once at startup |
| Model loading on startup | ✅ | Uses `load_quantile_models()` when saved Q10/Q50/Q90 models exist |
| Background training fallback | ✅ | If models are missing, `train_all_quantiles()` runs in a daemon thread |
| `/status` endpoint | ✅ | Returns `model_ready`, `model_status`, `source`, `data_rows`, `model_error` |
| `/forecast` endpoint | ✅ | Returns 48 timestamps plus actual/Q10/Q50/Q90 arrays |
| `/optimize` endpoint | ✅ | Accepts optional battery/scenario payload, applies derating + spread filter |
| `/feature-importance` endpoint | ✅ | Returns Q50 top 20 LightGBM gain features |
| API request validation | ✅ | Pydantic v2 model bounds for capacity, power, RTE, SoC, scenario |
| Hot-path KPI correction | ✅ | API recomputes degradation/net profit from request battery because `src.scheduler.optimize()` reports degradation using `DEFAULT_BATTERY` internally |

### Frontend

| Task | Status | Notes |
|------|--------|-------|
| Next.js 14 app scaffold | ✅ | `frontend/` with App Router, TypeScript, Tailwind |
| Typed API client | ✅ | `frontend/lib/api.ts`; default API URL is `http://localhost:8000` |
| Fixed desktop sidebar + mobile top layout | ✅ | Sidebar collapses naturally to top bar below `md` breakpoint |
| Source badge | ✅ | Live/cache/demo colour states; always visible |
| Model status indicator | ✅ | Spinner shown while booting/training |
| Battery sliders | ✅ | Capacity, power, RTE, degradation, initial SoC |
| Scenario select | ✅ | Base / Mild / Severe; scenario change triggers optimization immediately |
| Debounced optimization | ✅ | Slider changes debounce 400 ms before POST `/optimize` |
| Initial polling behavior | ✅ | Polls `/status` every 3 s until model is ready, then auto-runs default optimization |
| KPI cards | ✅ | Net Profit, Gross Revenue, Degradation, Cycles Used |
| Spread-filter info banner | ✅ | Shows idle MTUs and formula |
| Price forecast chart | ✅ | Recharts Q10/Q90 band, Q50 line, actual dashed line |
| Dispatch chart | ✅ | Charge/discharge bars, net line, grey idle overlays with tooltip explanation |
| SoC chart | ✅ | Teal area with min/max dashed reference lines |
| Feature importance chart | ✅ | Collapsible horizontal bar chart from `/feature-importance` |
| Full-page first-load skeleton | ✅ | Shown until first forecast/optimization data arrives |
| Locale number formatting | ✅ | Currency and decimal formatting for KPI values |

### Verification Completed

| Check | Status | Notes |
|------|--------|-------|
| API Python syntax/import | ✅ | `python3 -m py_compile api/main.py`; `import api.main` |
| FastAPI smoke test | ✅ | `/status`, `/forecast`, `/optimize`, `/feature-importance` all returned successfully |
| API demo response shape | ✅ | 48 forecast rows, 48 schedule rows, source `demo`, model ready |
| Frontend type check | ✅ | `npm run typecheck` |
| Frontend production build | ✅ | `npm run build` |
| Local dev servers | ✅ | API on `127.0.0.1:8000`; frontend on `127.0.0.1:3000` |
| Git hygiene for frontend outputs | ✅ | `.gitignore` updated for `frontend/node_modules/`, `.next/`, TS build info; package JSON files explicitly unignored |

---

## Phase 3 — Enterprise Security Layer

### Transport & Network Security

| Task | Status | Notes |
|------|--------|-------|
| TLS 1.3 enforcement | ✅ | `nginx/nginx.conf` — `ssl_protocols TLSv1.3` only; HTTP→HTTPS redirect |
| HSTS (HTTP Strict Transport Security) | ✅ | nginx: `max-age=31536000; includeSubDomains; preload`; Next.js: injected in production builds |
| WSS (WebSocket Secure) | ✅ | nginx `/ws/` location with `Upgrade` header passthrough and 3600 s keepalive |
| OCSP stapling | ✅ | `ssl_stapling on` in nginx |

### Authentication & Identity

| Task | Status | Notes |
|------|--------|-------|
| Session tokens (HMAC-signed, HTTP-only cookies) | ✅ | `api/security.py` — custom signed tokens with `exp`, `iat`, `sub`, `rol`, `csrf` claims |
| CSRF double-submit tokens | ✅ | `X-CSRF-Token` header required for all unsafe methods; JS-readable cookie |
| Password hashing (PBKDF2-SHA256) | ✅ | `password_hash_for_env()` helper; `APP_AUTH_PASSWORD_HASH` env var |
| TOTP / MFA (RFC 6238) | ✅ | `api/mfa.py` — pyotp; QR code via `qrcode[svg]`; two-phase login with short-lived `mfa_token` |
| MFA endpoints | ✅ | `GET /auth/mfa/setup`, `POST /auth/mfa/enable`, `POST /auth/mfa/verify` |
| OAuth 2.0 / OIDC SSO | ✅ | `api/oauth.py` — Microsoft Entra ID + Google Workspace; email domain allow-list |
| OIDC endpoints | ✅ | `GET /auth/oidc/login?provider=microsoft\|google`, `GET /auth/oidc/callback/{provider}` |
| RBAC (Role-Based Access Control) | ✅ | `api/rbac.py` — viewer / operator / admin hierarchy; `require_role()` FastAPI dependency |
| Role encoded in session token | ✅ | `"rol"` claim in token payload; `AuthenticatedUser.role` field |
| Endpoint role enforcement | ✅ | `/optimize` → operator+; `/api-keys`, `/audit` → admin only |

### API & Integration Security

| Task | Status | Notes |
|------|--------|-------|
| API key management (Argon2id hashed) | ✅ | `api/api_keys.py` — plaintext shown once, prefix stored for O(1) lookup, `bk_<prefix>_<secret>` format |
| API key CRUD endpoints | ✅ | `GET /api-keys`, `POST /api-keys`, `DELETE /api-keys/{id}` — all admin-gated |
| Rate limiting (in-memory sliding window) | ✅ | General: 240 req/60 s; login: 8 req/60 s — both enforced in FastAPI middleware and nginx zones |
| CORS strict allow-list | ✅ | `APP_ALLOWED_ORIGINS` env var; `TrustedHostMiddleware` |

### Application-Level Security (OWASP)

| Task | Status | Notes |
|------|--------|-------|
| Content Security Policy (CSP) | ✅ | FastAPI: `default-src 'none'`; Next.js: per-environment CSP in `next.config.mjs` |
| CSRF tokens | ✅ | Double-submit pattern; `POST /optimize` and all state-changing endpoints protected |
| Input sanitization / validation | ✅ | Pydantic v2 `Field(ge=, le=, pattern=)` on all request models |
| Security headers | ✅ | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy` |

### Data at Rest & Auditing

| Task | Status | Notes |
|------|--------|-------|
| AES-256-GCM encryption | ✅ | `api/encryption.py` — `cryptography` lib; nonce prepended to ciphertext; key from `APP_ENCRYPTION_KEY` |
| WORM audit log | ✅ | `api/audit.py` — SQLite with `set_authorizer` blocking UPDATE/DELETE at driver level; schema-first init |
| Audit log fields | ✅ | `id`, `timestamp`, `user_id`, `action`, `resource`, `ip_address`, `details` (JSON) |
| Audit log on key events | ✅ | login, login_failed, login_mfa_ok, logout, optimize, mfa_enabled, api_key_created, api_key_revoked |
| Audit log viewer | ✅ | `GET /audit?user_filter=&action_filter=&since=&limit=` — admin only |

### Security Verification

| Check | Status | Notes |
| ------ | -------- | ------- |
| AES-256-GCM round-trip | ✅ | `encrypt(decrypt(x)) == x` verified in smoke test |
| WORM authorizer blocks UPDATE | ✅ | `DatabaseError` raised on `UPDATE audit_log ...` — confirmed |
| Role claim in token | ✅ | `decode_session_token()` returns `payload["rol"]` correctly |
| Argon2id key hash/verify | ✅ | `verify_key(plaintext)` returns correct metadata after `create()` |
| All new security imports | ✅ | `rbac`, `audit`, `mfa`, `api_keys`, `encryption`, `oauth` all import cleanly |
| New security deps installed | ✅ | `argon2-cffi`, `cryptography`, `pyotp`, `qrcode`, `httpx` in venv |

---

## Phase 4 — Missing / Next Work

| Task | Status | Notes |
|------|--------|-------|
| Browser visual QA | 🔲 | Use Playwright/in-app browser screenshots on desktop + mobile to catch chart overlap and responsive issues |
| Automated API tests | 🔲 | Add pytest coverage for status/forecast/optimize/feature-importance and model-training fallback |
| Security unit tests | 🔲 | Pytest for RBAC deny cases, WORM integrity, MFA flow, OIDC domain block |
| Frontend MFA flow UI | 🔲 | Login page needs to handle `{ mfa_required: true, mfa_token }` response and show TOTP input |
| Frontend API key manager UI | 🔲 | Admin page to create/list/revoke API keys; show plaintext key once in modal |
| Better API lifecycle | 🔲 | Migrate from deprecated `@app.on_event("startup")` to FastAPI lifespan context |
| Docker / deployment | 🔲 | Dockerfiles or compose for API + frontend + nginx, health checks, process supervision |
| OIDC state param persistence | 🔲 | `oauth.py` comment notes state should be stored server-side (Redis TTL) to prevent CSRF on callback |
| Live ENTSO-E path | ⏳ | Needs `ENTSOE_API_KEY`; verify live source and cache writes end to end |
| Real fuels path | ⏳ | Verify yfinance TTF/EUA fetch when online and fallback behavior when offline |
| Visual idle-rate tuning | ⏳ | Current smoke-test default returned `idle_count = 0`; demo pitch may need parameters/data window that clearly shows grey idle bars |
| OpenAPI generated types | 🔲 | Optional: generate TS types from FastAPI schema instead of maintaining duplicate frontend types |
| Replace PuLP with Pyomo + HiGHS | 🔲 | Later optimizer hardening |
| Piecewise-linear efficiency curves | 🔲 | Later battery model fidelity |
| Backtesting engine, gate-closure aware | 🔲 | Later product analytics |
| Balancing market co-optimisation | 🔲 | Later market expansion |

---

## How to Run

### Streamlit MVP

```bash
# 1. Install dependencies
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. (Optional) set ENTSO-E key for live data
cp .env.example .env
# edit .env: ENTSOE_API_KEY=<your token>

# 3. Launch dashboard
streamlit run app.py

# 4. (Optional) full pipeline with real data
python scripts/01_fetch_data.py
python scripts/02_build_features.py
python scripts/03_train.py
python scripts/04_backtest.py
```

### FastAPI + Next.js Web App

```bash
# 1. Backend dependencies
source venv/bin/activate
pip install -r requirements.txt
pip install -r api/requirements.txt

# 2. Frontend dependencies
cd frontend
npm install
cd ..

# 3. Start API
uvicorn api.main:app --reload --reload-dir api --reload-dir src

# 4. Start frontend in another shell
cd frontend
npm run dev
```

Default local URLs:

| Service | URL |
|---------|-----|
| FastAPI | `http://127.0.0.1:8000` |
| Next.js dashboard | `http://127.0.0.1:3000` |
| OpenAPI docs | `http://127.0.0.1:8000/docs` |

## Demo Pitch Flow

### Streamlit

1. Open app → source badge shows **Demo (synthetic)**
2. Set battery: **100 MWh / 50 MW / 90% RTE / €5/MWh degradation**
3. Point to KPI row → explain Net Profit
4. Click a grey (idle) bar on the schedule plot → explain spread filter
5. Switch scenario to **Severe Degradation** → show how profit drops
6. Expand Feature Importance → explain Greek market features (EveningRamp, midday depression)

### Web App

1. Start FastAPI and Next.js → open `http://127.0.0.1:3000`
2. Confirm source badge is visible, usually **Demo synthetic** without `ENTSOE_API_KEY`
3. Wait for model status to show **Model ready**
4. Use KPI row to explain forecast-driven arbitrage value
5. Use the dispatch chart grey overlays to explain the spread filter / forced-idle differentiator
6. Change degradation scenario and watch the optimization rerun
7. Expand Feature Importance to connect forecasts back to market/weather/residual-load drivers

---

## Key Numbers for Pitch

| Metric | Value (demo) | Notes |
|--------|-------------|-------|
| Forecast MAE | ~8–12 €/MWh | Greek DAM typical range |
| Spread threshold | ~7–9 €/MWh | At 90% RTE, €5/MWh degradation |
| Idle MTUs | ~30–40% | System naturally cautious |
| Revenue capture vs perfect | ~65–75% | Forecast uncertainty penalty |

Recent API smoke-test values with default parameters:

| Metric | Value | Notes |
|--------|-------|-------|
| Data source | `demo` | No ENTSO-E key set |
| Data rows | 20 400 | Demo/weather-aligned history |
| Forecast rows | 48 | Last complete 48-hour window |
| Schedule rows | 48 | One row per MTU/hour |
| Net profit | ~€17 215 | Based on Q50 forecast schedule |
| Gross revenue | ~€20 215 | Before degradation |
| Degradation | ~€3 000 | Recomputed in API from requested degradation cost |
| Cycles used | ~2.84 | Default 100 MWh / 50 MW battery |
| Idle MTUs | 0 / 48 | Needs follow-up for a more visually demonstrative demo case |
