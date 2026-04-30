# LogicVolt — Production Setup

Battery dispatch optimization for the Greek Day-Ahead Market. Walk-forward
capture ratio **0.8743** (validated, 30-day rolling, leakage-free) with the
dynamic-horizon MPC stack. See `docs/HANDOFF.md` for the full model story.

This document covers **only deployment** of the cleaned repo.

---

## What's in the repo

```
api/                FastAPI backend (auth, optimize, webhooks, billing)
src/                ML modules (forecaster, scheduler, features, data sources)
scripts/            Roadmap of how the model was built (see "Showcase" below)
models/             Trained LightGBM artifacts — DO NOT retrain to ship
data/raw/           Input parquets (HEnEx, ENTSO-E, weather, fuels — 2024-04-30)
data/cache/         Live-fetch cache populated at runtime
data/processed/     features_clean.parquet — kept ONLY for the retrain script
frontend/           Next.js 14 dashboard (login, optimize UI, account, webhooks)
docs/               HANDOFF, DEPLOYMENT, RUNNING_APP, DOPPLER_GUIDE, assignment
nginx/              Reverse-proxy config sample
reports/            Validation evidence (walk-forward, MPC alpha, dynamic horizon)
config.py           Battery spec, paths, timezone, ENTSO-E key loader
render.yaml         Render.com one-click deploy
start_all.sh        Local "boot everything" helper
requirements.txt    Backend + scripts Python deps (no streamlit/plotly anymore)
api/requirements.txt FastAPI-specific deps (argon2, pyotp, qrcode, httpx)
```

## Models that ship

`api/main.py` boots `forecaster.load_quantile_models()` which reads
`models/`. The loader prefers the q50 ensemble (3 seeds) and falls back to
the single q50 booster if the seed files are missing.

| File pair (.txt + .json) | Role |
|---|---|
| `lgbm_q05` | 5th-percentile booster |
| `lgbm_q95` | 95th-percentile booster |
| `lgbm_q50_seed42`, `lgbm_q50_seed7`, `lgbm_q50_seed1337` | Median ensemble |
| `lgbm_q50` | Median single fallback |

These are pre-trained on data through 2026-04-30. **Do not retrain to ship**
— the API loads them as-is on startup.

---

## Backend setup

### 1. Python env

```sh
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r api/requirements.txt
```

### 2. Environment variables

Required (auth):
```
APP_AUTH_USERNAME=admin
APP_AUTH_PASSWORD=<choose a strong one>
APP_SECRET_KEY=<48-byte random; openssl rand -base64 48>
APP_COOKIE_SECURE=true             # set to true behind HTTPS
APP_ALLOWED_ORIGINS=https://your-frontend.example.com
APP_ALLOWED_HOSTS=your-api.example.com
```

Optional (auth hardening):
```
APP_AUTH_PASSWORD_HASH=pbkdf2_sha256$260000$...   # if set, replaces APP_AUTH_PASSWORD
APP_SESSION_SECONDS=28800
APP_RATE_LIMIT_REQUESTS=240
APP_RATE_LIMIT_WINDOW_SECONDS=60
```

Optional (data refresh — without it the API runs on the bundled cache):
```
ENTSOE_API_KEY=<from transparency.entsoe.eu account>
```

### 3. Run the API

```sh
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Production: put a reverse proxy (nginx config in `nginx/`) in front and
manage with systemd/Render/Fly. Example systemd unit:

```ini
[Service]
WorkingDirectory=/opt/logicvolt
EnvironmentFile=/opt/logicvolt/.env
ExecStart=/opt/logicvolt/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
```

### 4. First boot — what happens

1. `load_market_data()` tries live ENTSO-E (if `ENTSOE_API_KEY` set);
   otherwise falls back to `data/cache/market_cache.parquet`, then
   synthetic demo. The selected source is reported in `/status.source`.
2. `engineer_features()` builds the model feature matrix from the loaded
   raw data plus `data/raw/henex_results_all.parquet`.
3. `load_quantile_models()` loads the bundled artifacts. If any are
   missing (they shouldn't be) the API trains on demand in a thread.
4. The first `/optimize` call returns a 192-MTU dispatch using the
   dynamic-horizon LP (2–4 days, geometric discount 0.1×0.6ⁿ⁻¹).

Sanity-check after boot:
```sh
curl http://localhost:8000/health
curl http://localhost:8000/status -H "Cookie: bess_session=..."
```

---

## Frontend setup

```sh
cd frontend
npm install
echo "NEXT_PUBLIC_API_URL=https://your-api.example.com" > .env.local
npm run build
npm run start                       # or deploy to Vercel
```

Dev:
```sh
npm run dev                         # http://localhost:3000
```

Default admin login is whatever you set as `APP_AUTH_USERNAME` /
`APP_AUTH_PASSWORD` on the backend. After first login, register MFA from
the Account page.

---

## Data refresh (operational)

The bundled `data/raw/*` covers Jan 2024 → Apr 2026. To keep the model
predicting against fresh prices in production:

1. **Live tier** — set `ENTSOE_API_KEY` and the API will refresh DAM /
   load / wind+solar forecasts for the past 90 days on every startup.
2. **Bulk refresh** — run `scripts/01_fetch_data.py` to pull HEnEx + the
   six ENTSO-E series + weather + fuels into `data/raw/`, then
   `scripts/02_build_features.py` to rebuild `features_clean.parquet`.

The model artifacts only need to be retrained if a long stretch of new
data accumulates. To retrain:

```sh
python scripts/23_train_production.py
```

This trains the same recipe used in walk-forward (q05/q95 singles, q50
ensemble of 3 seeds, recency × seasonal × economic-impact weighting),
holds out only 14 days for early stopping, and overwrites `models/`.

---

## API surface (production)

Authenticated via session cookie (browser) or
`Authorization: Bearer bk_<prefix>_<secret>` (machine):

| Endpoint | Method | Role | Purpose |
|---|---|---|---|
| `/health` | GET | public | liveness |
| `/auth/login`, `/auth/logout`, `/auth/me` | POST/POST/GET | public/user | session |
| `/auth/mfa/*` | various | user | TOTP enrolment |
| `/status` | GET | viewer | model + data status |
| `/forecast` | GET | viewer | next-48h q10/q50/q90 |
| `/optimize` | POST | operator | dispatch + customer KPIs |
| `/feature-importance` | GET | viewer | top-20 model gains |
| `/data-feeds` | GET | viewer | per-source health |
| `/api-keys` | CRUD | admin | machine-key management |
| `/billing/tiers`, `/billing/keys` | GET | viewer/admin | plan catalog + per-key usage |
| `/billing/keys/{id}` | PATCH | admin | upgrade/downgrade tier |
| `/webhooks` | CRUD | admin | outbound webhook subscriptions |
| `/webhooks/{id}/test` | POST | admin | synchronous ping |
| `/audit` | GET | admin | append-only audit log |

`/optimize` returns customer KPIs the dashboard surfaces:
`net_profit_eur`, `daily_profit_eur`, `annualized_revenue_eur`,
`naive_baseline_eur`, `uplift_eur_day`, `annualized_uplift_eur`,
`capture_vs_naive`, `model_capture_ratio` (the validated 0.8743),
`cycles_used`, `energy_traded_mwh`.

After every successful `/optimize`, the webhook dispatcher fires
`optimize.completed` to subscribed URLs in a daemon thread, signed with
HMAC-SHA256 in `X-LogicVolt-Signature: sha256=<hex>`.

---

## Showcase — the pipeline that built the model

Every kept script earns its place in the story. Run order top to bottom:

| Script | Stage | What it shows |
|---|---|---|
| `scripts/01_fetch_data.py` | Ingestion | Pulls HEnEx, ENTSO-E, weather, fuels into `data/raw/`. Source of truth for all downstream work. |
| `scripts/02_build_features.py` | Features | Builds `features_clean.parquet` with 73 lag-safe features. Strict gate-close-feasible. |
| `scripts/16_validate_stack.py` | Baseline | One-shot 30-day held-out validation. Optimistic — kept as the "before walk-forward" reference. |
| `scripts/17_walkforward.py` | Honest baseline | 5 folds × 7 days walk-forward, weekly retrain. **The number to claim externally.** |
| `scripts/19_walkforward_mpc.py` | MPC test 1 | Fixed 2-day MPC at α=0.1 — shows the look-ahead idea works. |
| `scripts/20_mpc_alpha_search.py` | MPC test 2 | Sweeps α ∈ {0.0, 0.1, …, 1.0}. Finds α=0.1 optimal; full MPC (α=1.0) loses €7.5k / 30 days. |
| `scripts/21_roll_horizon_search.py` | Horizon sweep | Sweeps fixed 2–7 day horizons. Confirms 2-day is best in the fixed regime. |
| `scripts/22_dynamic_horizon.py` | Winner | Per-day horizon selection (2–4 days from forecast confidence) with geometric discount. **Overall capture 0.8743, €551,796 / 30 days.** |
| `scripts/23_train_production.py` | Ship | Trains the winning recipe on ALL data (only 14 days for early-stop). Persists to `models/`. |
| `scripts/18_live_loop.py` | Operations | `--tick` (15-min refresh) / `--forecast YYYY-MM-DD` / `--serve`. The cron entrypoint. |

Reports under `reports/` are the evidence each script produces:

| Report | Source |
|---|---|
| `walkforward_summary.json`, `walkforward_daily.csv` | `17_walkforward.py` |
| `walkforward_mpc_summary.json`, `walkforward_mpc_daily.csv` | `19_walkforward_mpc.py` |
| `mpc_alpha_search.json`, `mpc_alpha_weekly.csv` | `20_mpc_alpha_search.py` |
| `rolling_horizon_search.json`, `rolling_horizon_daily.csv` | `21_roll_horizon_search.py` |
| `dynamic_horizon_summary.json`, `dynamic_horizon_daily.csv` | `22_dynamic_horizon.py` (the winner) |

---

## Deployment quick paths

* **Render.com** — `render.yaml` is checked in. Push to GitHub, "New Web
  Service from Blueprint" → it provisions the API. Set the `APP_*` env
  vars in the dashboard. Frontend is a static deploy (Vercel preferred —
  `frontend/vercel.json` is configured).
* **Single VM** — clone, `pip install -r requirements.txt -r
  api/requirements.txt`, run `uvicorn api.main:app` behind nginx (see
  `nginx/`), build the frontend with `npm run build && npm run start`
  on a separate port, point nginx `/` at the frontend and `/api` at the
  uvicorn process.
* **Doppler** for secrets (optional) — see `docs/DOPPLER_GUIDE.md`.

---

## Known constraints

1. The bundled cache ends 2026-04-30. Without an `ENTSOE_API_KEY`, the
   API will keep predicting against that frozen window — fine for demo,
   stale for production.
2. The model expects HEnEx data through `data/raw/henex_results_all.parquet`.
   Refresh by re-running `scripts/01_fetch_data.py --source henex`.
3. SQLite stores (`data/audit.db`, `data/mfa.db`, `data/api_keys.db`,
   `data/webhooks.db`, `data/billing.json`) are created on first use.
   Back them up — they hold credentials, MFA secrets, and subscription
   state.
4. Argon2id secret hashing means webhook secrets are unrecoverable. The
   plaintext is shown **once** at registration; if lost, delete and
   recreate the subscription.
