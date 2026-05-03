# LogicVolt

Battery energy storage dispatch optimisation — Greek DAM / ENTSO-E edition.
Walk-forward capture ratio **0.8743** (validated, 30-day rolling, leakage-free) with the dynamic-horizon MPC stack.

## Repo structure

```
api/                FastAPI backend (auth, optimize, webhooks, billing)
src/                ML modules (forecaster, scheduler, features, data sources)
scripts/            Pipeline scripts — fetch → features → validate → train
models/             Trained LightGBM artifacts — DO NOT retrain to ship
data/raw/           Input parquets (HEnEx, ENTSO-E, weather, fuels — to 2026-04-30)
data/cache/         Live-fetch cache populated at runtime
data/processed/     features_clean.parquet — kept only for the retrain script
frontend/           Next.js 14 dashboard (login, optimise UI, account, webhooks)
docs/               Guides: RUNNING_APP, ONBOARDING, DOPPLER, CHATBOT_KNOWLEDGE_BASE
nginx/              Reverse-proxy config sample
reports/            Validation evidence (walk-forward, MPC alpha, dynamic horizon)
config.py           Battery spec, paths, timezone, ENTSO-E key loader
render.yaml         Render.com one-click deploy
start_all.sh        Local "boot everything" helper
requirements.txt    Backend + scripts Python deps
api/requirements.txt  FastAPI-specific deps (argon2, pyotp, qrcode, httpx)
```

---

## Quick start (local)

Run the full stack from the repo root:

```sh
./start_all.sh
```

The launcher wraps itself with Doppler when the CLI is present, injecting `GROQ_API_KEY` and other secrets automatically. Without Doppler the chatbot is disabled but everything else works.

Then open <http://127.0.0.1:3000>.

Default local login: `admin` / `admin` (override with `APP_AUTH_USERNAME` / `APP_AUTH_PASSWORD`).

### Pages

| Path          | Description                                                |
| ------------- | ---------------------------------------------------------- |
| `/`           | Landing page                                               |
| `/dashboard`  | Optimisation dashboard — forecast, dispatch schedule, KPIs |
| `/onboarding` | Asset setup, data integration hub, scenario sandbox        |
| `/account`    | Session, MFA, API keys, billing tiers, webhooks, audit log |
| `/pricing`    | Public subscription and pricing page                       |

---

## Backend setup

### 1. Python environment

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
APP_AUTH_PASSWORD_HASH=pbkdf2_sha256$260000$...   # replaces APP_AUTH_PASSWORD if set
APP_SESSION_SECONDS=28800
APP_RATE_LIMIT_REQUESTS=240
APP_RATE_LIMIT_WINDOW_SECONDS=60
```

Optional (live data — without it the API runs on the bundled cache):

```
ENTSOE_API_KEY=<from transparency.entsoe.eu account>
```

### 3. Run the API

```sh
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

For production, put a reverse proxy (nginx config in `nginx/`) in front. Example systemd unit:

```ini
[Service]
WorkingDirectory=/opt/logicvolt
EnvironmentFile=/opt/logicvolt/.env
ExecStart=/opt/logicvolt/.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
```

### 4. First boot — what happens

1. `load_market_data()` tries live ENTSO-E (if `ENTSOE_API_KEY` set); otherwise falls back to `data/cache/market_cache.parquet`, then synthetic demo. Source is reported in `/status.source`.
2. `engineer_features()` builds the model feature matrix.
3. `load_quantile_models()` loads the bundled artifacts (trains on demand in a thread if any are missing).
4. The first `/optimize` call returns a 192-MTU dispatch using the dynamic-horizon LP (2–4 days, geometric discount 0.1×0.6ⁿ⁻¹).

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

Dev mode:

```sh
cd frontend
npm run dev                         # http://localhost:3000
```

---

## Models that ship

`api/main.py` boots `forecaster.load_quantile_models()` which reads `models/`. The loader prefers the q50 ensemble (3 seeds) and falls back to the single q50 booster if seed files are missing.

| File pair (.txt + .json)                              | Role                    |
| ----------------------------------------------------- | ----------------------- |
| `lgbm_q05`                                            | 5th-percentile booster  |
| `lgbm_q95`                                            | 95th-percentile booster |
| `lgbm_q50_seed42`, `lgbm_q50_seed7`, `lgbm_q50_seed1337` | Median ensemble     |
| `lgbm_q50`                                            | Median single fallback  |

Pre-trained on data through 2026-04-30. **Do not retrain to ship** — the API loads them as-is on startup.

---

## API surface

Authenticated via session cookie (browser) or `Authorization: Bearer bk_<prefix>_<secret>` (machine):

| Endpoint                                       | Method        | Role          | Purpose                          |
| ---------------------------------------------- | ------------- | ------------- | -------------------------------- |
| `/health`                                      | GET           | public        | liveness                         |
| `/auth/login`, `/auth/logout`, `/auth/me`      | POST/POST/GET | public / user | session                          |
| `/auth/mfa/*`                                  | various       | user          | TOTP enrolment                   |
| `/status`                                      | GET           | viewer        | model + data status              |
| `/forecast`                                    | GET           | viewer        | next-48h q10/q50/q90             |
| `/optimize`                                    | POST          | operator      | dispatch + customer KPIs         |
| `/feature-importance`                          | GET           | viewer        | top-20 model gains               |
| `/data-feeds`                                  | GET           | viewer        | per-source health                |
| `/api-keys`                                    | CRUD          | admin         | machine-key management           |
| `/billing/tiers`, `/billing/keys`              | GET           | viewer / admin| plan catalog + per-key usage     |
| `/billing/keys/{id}`                           | PATCH         | admin         | upgrade / downgrade tier         |
| `/webhooks`                                    | CRUD          | admin         | outbound webhook subscriptions   |
| `/webhooks/{id}/test`                          | POST          | admin         | synchronous ping                 |
| `/audit`                                       | GET           | admin         | append-only audit log            |

`/optimize` returns: `net_profit_eur`, `daily_profit_eur`, `annualized_revenue_eur`, `naive_baseline_eur`, `uplift_eur_day`, `annualized_uplift_eur`, `capture_vs_naive`, `model_capture_ratio` (0.8743), `cycles_used`, `energy_traded_mwh`.

After every successful `/optimize`, the webhook dispatcher fires `optimize.completed` signed with HMAC-SHA256 (`X-LogicVolt-Signature: sha256=<hex>`).

---

## Data refresh (operational)

The bundled `data/raw/*` covers Jan 2024 → Apr 2026.

1. **Live tier** — set `ENTSOE_API_KEY` and the API refreshes DAM / load / wind+solar forecasts for the past 90 days on every startup.
2. **Bulk refresh** — run `scripts/01_fetch_data.py` then `scripts/02_build_features.py`.

To retrain the model on new data:

```sh
python scripts/23_train_production.py
```

---

## Deployment quick paths

- **Render.com** — `render.yaml` is checked in. Push to GitHub → "New Web Service from Blueprint" → set `APP_*` env vars in the dashboard. Frontend deploys to Vercel (`frontend/vercel.json` is configured).
- **Single VM** — clone, install deps, run `uvicorn api.main:app` behind nginx (`nginx/`), build the frontend with `npm run build && npm run start` on a separate port.
- **Doppler** for secrets (optional) — see [docs/DOPPLER\_GUIDE.md](docs/DOPPLER_GUIDE.md).

---

## Showcase — pipeline that built the model

| Script                            | Stage            | What it shows                                                                                    |
| --------------------------------- | ---------------- | ------------------------------------------------------------------------------------------------ |
| `scripts/01_fetch_data.py`        | Ingestion        | Pulls HEnEx, ENTSO-E, weather, fuels into `data/raw/`.                                           |
| `scripts/02_build_features.py`    | Features         | Builds `features_clean.parquet` with 73 lag-safe, gate-close-feasible features.                 |
| `scripts/16_validate_stack.py`    | Baseline         | One-shot 30-day held-out validation — the "before walk-forward" reference.                      |
| `scripts/17_walkforward.py`       | Honest baseline  | 5 folds × 7 days walk-forward, weekly retrain. **The number to claim externally.**              |
| `scripts/19_walkforward_mpc.py`   | MPC test 1       | Fixed 2-day MPC at α=0.1 — shows the look-ahead idea works.                                    |
| `scripts/20_mpc_alpha_search.py`  | MPC test 2       | Sweeps α ∈ {0.0 … 1.0}. Finds α=0.1 optimal; full MPC (α=1.0) loses €7.5k / 30 days.          |
| `scripts/21_roll_horizon_search.py` | Horizon sweep  | Sweeps fixed 2–7 day horizons. Confirms 2-day best in the fixed regime.                         |
| `scripts/22_dynamic_horizon.py`   | **Winner**       | Per-day horizon selection (2–4 days) with geometric discount. **Capture 0.8743, €551,796 / 30d.**|
| `scripts/23_train_production.py`  | Ship             | Trains winning recipe on ALL data (14 days for early-stop). Persists to `models/`.              |
| `scripts/18_live_loop.py`         | Operations       | `--tick` (15-min refresh) / `--forecast YYYY-MM-DD` / `--serve`. The cron entrypoint.           |

Reports under `reports/` are the evidence each script produces (`walkforward_summary.json`, `mpc_alpha_search.json`, `dynamic_horizon_summary.json`, etc.).

---

## Known constraints

1. The bundled cache ends 2026-04-30. Without `ENTSOE_API_KEY`, predictions run against the frozen window — fine for demo, stale for production.
2. The model expects HEnEx data through `data/raw/henex_results_all.parquet`. Refresh with `scripts/01_fetch_data.py --source henex`.
3. SQLite stores (`data/audit.db`, `data/mfa.db`, `data/api_keys.db`, `data/webhooks.db`, `data/billing.json`) are created on first use. Back them up — they hold credentials, MFA secrets, and subscription state.
4. Argon2id webhook secret hashing is one-way. The plaintext is shown **once** at registration; if lost, delete and recreate the subscription.

---

## Further reading

| Doc                                                                | Purpose                            |
| ------------------------------------------------------------------ | ---------------------------------- |
| [docs/RUNNING\_APP.md](docs/RUNNING_APP.md)                        | Full local startup instructions    |
| [docs/ONBOARDING\_GUIDE.md](docs/ONBOARDING_GUIDE.md)              | Operator onboarding guide          |
| [docs/DOPPLER\_GUIDE.md](docs/DOPPLER_GUIDE.md)                    | Secret management with Doppler     |
| [docs/CHATBOT\_KNOWLEDGE\_BASE.md](docs/CHATBOT_KNOWLEDGE_BASE.md) | In-app AI assistant knowledge base |
