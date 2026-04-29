# BESS Optimizer — Build Progress

## Architecture

```
ETW/
├── app.py                  # Streamlit dashboard (entry point)
├── config.py               # BatterySpec, paths, locations
├── requirements.txt        # All dependencies
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

## Phase 2 — Post-Hackathon (Not started)

| Task | Status | ETA |
|------|--------|-----|
| Replace PuLP with Pyomo + HiGHS | 🔲 | Week 1–2 |
| Piecewise-linear efficiency curves | 🔲 | Week 2 |
| Backtesting engine (rolling daily, gate-closure aware) | 🔲 | Week 3–4 |
| Balancing market co-optimisation | 🔲 | Week 5–6 |
| FastAPI service + multi-tenancy | 🔲 | Week 7–8 |

---

## How to Run

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

## Demo Pitch Flow

1. Open app → source badge shows **Demo (synthetic)**
2. Set battery: **100 MWh / 50 MW / 90% RTE / €5/MWh degradation**
3. Point to KPI row → explain Net Profit
4. Click a grey (idle) bar on the schedule plot → explain spread filter
5. Switch scenario to **Severe Degradation** → show how profit drops
6. Expand Feature Importance → explain Greek market features (EveningRamp, midday depression)

---

## Key Numbers for Pitch

| Metric | Value (demo) | Notes |
|--------|-------------|-------|
| Forecast MAE | ~8–12 €/MWh | Greek DAM typical range |
| Spread threshold | ~7–9 €/MWh | At 90% RTE, €5/MWh degradation |
| Idle MTUs | ~30–40% | System naturally cautious |
| Revenue capture vs perfect | ~65–75% | Forecast uncertainty penalty |
