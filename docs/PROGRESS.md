# BESS Optimizer — Build Progress

## Architecture

```
ETW/
├── app.py                  # Streamlit dashboard (entry point)
├── api/
│   ├── main.py             # FastAPI service wrapper around existing src/ logic
│   └── requirements.txt    # API-only deps: fastapi, uvicorn, pydantic
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

## Phase 3 — Missing / Next Work

| Task | Status | ETA |
|------|--------|-----|
| Browser visual QA | 🔲 | Use Playwright/in-app browser screenshots on desktop + mobile to catch chart overlap and responsive issues |
| Automated API tests | 🔲 | Add pytest coverage for status/forecast/optimize/feature-importance and model-training fallback |
| Frontend interaction tests | 🔲 | Add tests for polling, debounce, scenario immediate rerun, error states |
| Better API lifecycle | 🔲 | Migrate from deprecated `@app.on_event("startup")` to FastAPI lifespan context |
| Production config | 🔲 | Add `.env.local.example` for `NEXT_PUBLIC_API_URL`; document prod API URL setup |
| Docker / deployment | 🔲 | Dockerfiles or compose for API + frontend, health checks, process supervision |
| Live ENTSO-E path | ⏳ | Needs `ENTSOE_API_KEY`; verify live source and cache writes end to end |
| Real fuels path | ⏳ | Verify yfinance TTF/EUA fetch when online and fallback behavior when offline |
| Visual idle-rate tuning | ⏳ | Current smoke-test default returned `idle_count = 0`; demo pitch may need parameters/data window that clearly shows grey idle bars |
| Security/audit follow-up | ⏳ | Latest Next 14 is installed, but `npm audit` still reports advisories whose automated fix jumps to Next 16 |
| Auth / tenancy | 🔲 | Not implemented; needed before exposing customer data or multi-user deployments |
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
