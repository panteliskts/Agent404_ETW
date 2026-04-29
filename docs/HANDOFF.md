# Project Handoff — Battery Optimization in the Greek Electricity Market

This document is a self-contained briefing for an LLM that has not seen the prior conversation. It contains the problem, the approach, what is built, what remains, and concrete next steps. Read it top to bottom before touching the repo.

---

## 1. The Problem (from the hackathon brief)

**Event:** Battery Optimization in the Greek Electricity Market.

**Context.** Greece's electricity market is in rapid transition: solar/wind growth → more curtailments, more intraday/day-ahead price volatility. Greece's first standalone batteries entered the Day-Ahead Market (DAM) in test mode in April 2026.

**Deliverable.** Propose a complete battery optimization solution that decides — for every market time unit (MTU) — whether a battery should **charge, discharge, or stay idle**, with the objective of **maximizing economic value** while respecting all technical/operational constraints. Participants must identify and collect their own data sources.

**Key market facts**
- Day-Ahead Market is operated by **HEnEx** (Hellenic Energy Exchange).
- Pricing was hourly until **2025-10-01**, then moved to **15-minute MTUs** (96 slots/day).
- Uniform marginal pricing — clearing price set by the last accepted offer needed to satisfy demand.
- The brief explicitly emphasizes **data scarcity**: real Greek standalone batteries only entered in April 2026, so there is **no rich historical battery telemetry**. Participants must build a robust optimization framework that produces feasible, profitable schedules with limited asset history.

**Solution shape.** A two-layer architecture:
1. **Price forecaster** — predicts next-day 15-min DAM prices from market/weather/fuels features.
2. **Battery scheduler** — optimizes charge/discharge given those prices + battery constraints. This is the *core* deliverable.

**Headline KPI** — *capture ratio* = realized revenue / perfect-foresight revenue. Compare a schedule produced from forecasted prices (and evaluated on realized prices) to a schedule that knew prices in advance.

---

## 2. Current Thinking & Strategic Decisions

These decisions have already been made in the conversation; do not relitigate them unless the user explicitly asks:

- **Approach: MILP for the scheduler, gradient-boosted ML for the forecaster.** MILP is convex over 96 15-min slots, solves in milliseconds, uses `pulp` + CBC. Forecaster is LightGBM baseline; user said "I will probably make a model and train it" — so the forecaster is *deliberately* a swappable scaffold.
- **Decouple forecaster and scheduler.** Forecaster outputs a price vector; scheduler is forecaster-agnostic. Judges reward this separation.
- **Battery params are assumed, not learned.** 50 MW / 100 MWh, 95%/95% η, 5–95% SoC, cyclic, 1.5 cycles/day, €2/MWh degradation. Sensitivity analysis is part of the robustness story for the judges.
- **Training window: 2024-01-01 → 2026-04-30 (28 months).** User explicitly chose this over the full 2021–2026 archive, because the gas-crisis era (2021–2023) had a wildly different price regime that would only confuse the model.
- **Granularity: native 15-min from Oct 2025 onward; hourly upsampled to 15-min before that.** A `mtu_15m_active` flag lets the model treat the two regimes differently if needed.
- **Data sources prioritized:** HEnEx (primary, scraped) > Open-Meteo (weather) > yfinance (fuels). ADMIE was deferred — its data overlaps with ENTSO-E. ENTSO-E is wired but blocked on API token approval.
- **No ADMIE scraper for now.** Reason: ENTSO-E covers the same data (load forecasts, RES forecasts) once the token arrives. The user agreed to defer this.
- **Capture ratio is the headline KPI.** Realized revenue from forecast-based schedule, divided by perfect-foresight schedule revenue.
- **Pre-Oct-2025 hourly data is upsampled to 15-min** by forward-fill on prices and time-interpolation on smooth quantities (load, generation, weather). Acceptable lossy compromise; the alternative (training only on Oct 2025+ for 7 months) was deemed too little data.

### Things explicitly NOT to do

- Don't build an ADMIE scraper unless the user asks (ENTSO-E will cover the same data via API).
- Don't try to scrape ICE TTF or EEX EUA directly — they are paywalled. The yfinance proxies (`TTF=F`, `CO2.L`) are the agreed pragmatic substitute.
- Don't train the forecaster on battery telemetry — there isn't enough. Treat battery params as assumed inputs and run sensitivity instead.
- Don't add features beyond what's there without strong justification — the dataset has 73 columns already, plenty for tree-based models on 80k rows.
- Don't expand the training window earlier than 2024 — already discussed and rejected.

---

## 3. Repository State (what is BUILT)

Project root: `C:\Users\varda\Documents\Hackathons\ETW` (Windows, bash + PowerShell available).

```
ETW/
├── HANDOFF.md                 # this file
├── Hackathon_final.docx.pdf   # original brief
├── requirements.txt
├── .env.example               # ENTSOE_API_KEY placeholder
├── config.py                  # paths, BatterySpec, weather locations, GR_TIMEZONE
├── src/
│   ├── data/
│   │   ├── entsoe_client.py   # DAM, load fcst, wind/solar fcst — needs API key
│   │   ├── henex.py           # HEnEx archive scraper — DONE, 5+ years downloaded
│   │   ├── weather.py         # Open-Meteo (no key) — DONE
│   │   └── fuels.py           # yfinance TTF + EUA — DONE
│   ├── features.py            # builds merged 15-min training dataset — DONE
│   ├── scheduler.py           # MILP optimizer (pulp + CBC) — DONE
│   ├── forecaster.py          # LightGBM scaffold — STUB, user will customize
│   ├── evaluate.py            # perfect-foresight vs forecast vs realized — DONE
│   └── __init__.py
├── scripts/
│   ├── 01_fetch_data.py       # wired for henex/weather/fuels/entsoe
│   ├── 02_build_features.py   # builds data/processed/features.parquet
│   ├── 03_train.py            # trains the LightGBM baseline
│   └── 04_backtest.py         # rolling-day backtest with capture ratio KPI
├── data/
│   ├── raw/
│   │   ├── henex/zips/        # cached yearly archives 2021-2025 (large)
│   │   ├── henex/xlsx/        # extracted daily Excel files
│   │   ├── henex_results_all.parquet     # 50,880 rows, 2021-2026
│   │   ├── weather_2024-01-01_2026-04-29.parquet  # 20,400 rows, hourly
│   │   └── fuels_2024-01-01_2026-04-30.parquet    # 597 rows, daily
│   └── processed/
│       └── features.parquet   # ★ TRAINING DATASET: 81,692 × 73, 15-min, 2024-2026
└── models/                    # populated by scripts/03_train.py
```

### What each module does

**`config.py`** — defines the `BatterySpec` dataclass (50 MW / 100 MWh defaults), the four weather observation cities (Athens, Thessaloniki, Patras, Crete), `GR_TIMEZONE = "Europe/Athens"`, `MTU_SWITCH_DATE = "2025-10-01"`, and creates required dirs.

**`src/data/henex.py`** — scrapes HEnEx publication and archive pages, downloads yearly ZIPs (containing daily Excel files), extracts only DAM files (skips intraday auctions IDA/CRIDA), parses ResultsSummary xlsx files. Parser is **section-aware** (works for both old hourly and new 15-min formats) and DST-tolerant. Picks latest version per date when duplicates exist. Output schema:

```
volume_mainland_mwh, dam_price_eur_mwh, dam_price_60min_idx_eur_mwh,
gen_lignite_mw, gen_gas_mw, gen_hydro_mw, gen_renewables_mw,
gen_crete_renewables_mw, gen_crete_conventional_mw, gen_bess_mw,
production_total_mw,
load_hv_mw, load_mv_mw, load_lv_mw, load_pump_mw,
system_losses_mw, load_crete_mw, demand_total_mw,
load_bess_mw, renewables_buy_mw
```

**`src/data/weather.py`** — Open-Meteo Archive API (no key). 7 vars × 4 cities = 28 columns. Fetches in UTC then converts to Athens TZ to dodge DST gaps. Hourly resolution.

**`src/data/fuels.py`** — yfinance proxies: `TTF=F` for Dutch TTF gas, `CO2.L` for EUA carbon. Daily settle close. Stored as `ttf_eur_mwh` and `eua_eur_t`. Note: a known yfinance MultiIndex/wide-format quirk was already fixed (we now extract `df["Close"]` defensively).

**`src/data/entsoe_client.py`** — wraps `entsoe-py` for DAM prices, load forecast, wind/solar forecast, actual load/generation. **BLOCKED on API token approval.** User must email `transparency@entsoe.eu` requesting Restful API access; approval comes within 24h, then a "Generate Token" button appears in account settings.

**`src/features.py`** — the merge pipeline:
1. Loads HEnEx, filters to `>= 2024-01-01`.
2. Resamples to uniform 15-min grid (ffill for prices, time-interp for smooth quantities).
3. Joins weather, fuels, ENTSO-E (if present), all on the 15-min grid.
4. Adds calendar features (sin/cos hour-of-day and day-of-year, dow, weekend, month).
5. Adds derived: `load_total_mw`, `res_share`, `net_export_mw`, `ccgt_srmc_eur_mwh = TTF*2 + EUA*0.37`.
6. Adds 7 lag features (15min, 1h, 2h, 6h, 12h, 1d, 1w) and 6 rolling stats (mean+std × 4/16/96).
7. Adds `mtu_15m_active` regime flag.
8. Drops columns with >70% NaN. Currently drops: `load_pump_mw`, `dam_price_60min_idx_eur_mwh`, `gen_bess_mw`.

**`src/scheduler.py`** — MILP via `pulp`/CBC. Variables per slot t: `ch[t]`, `dis[t]`, `soc[t]`, binary `z[t]` to forbid simultaneous charge+discharge. Constraints: SoC bounds, energy balance with η, optional terminal SoC, daily cycle cap. Objective: revenue − degradation. Returns a `Schedule` dataclass with charge/discharge/SoC arrays, revenue, degradation, objective, delta_h. Also has `realized_revenue(schedule, realized_prices)` to evaluate a schedule against actual prices.

**`src/forecaster.py`** — LightGBM baseline with time-based train/valid/test split (last 30 days = test, prior 30 = valid). Saves model + feature columns + metrics. **Intended to be replaced** with the user's custom model. Keep the `train()` signature and the `model.predict(features[feature_cols])` contract and the rest of the pipeline keeps working.

**`src/evaluate.py`** — for each day: solves perfect-foresight, solves with forecast prices, evaluates the forecast schedule on realized prices. Returns `capture_ratio = realized / perfect`. Also has `rolling_backtest()` and `summary()`.

### Final dataset summary

`data/processed/features.parquet` — **THE training-ready file**:
- 81,692 rows × 73 columns
- 2024-01-01 00:00:00+02:00 → 2026-04-30 23:45:00+03:00
- Uniform 15-min, Europe/Athens TZ
- Target: `dam_price_eur_mwh`
- Feature groups: 15 price (incl lags+rolls), 8 generation, 7 load, 28 weather, 3 fuels, 10 calendar, plus regime/derived

---

## 4. Pipeline Cheat Sheet

```bash
# Install
pip install -r requirements.txt

# Fetch all data (HEnEx scraper has been run; rerunning re-uses cache)
python scripts/01_fetch_data.py --skip-entsoe   # entsoe is blocked on token

# Build the 73-column 15-min training dataset
python scripts/02_build_features.py

# Train the baseline LightGBM (USER WILL LIKELY REPLACE THIS)
python scripts/03_train.py

# Backtest: capture-ratio per day vs perfect foresight
python scripts/04_backtest.py
```

---

## 5. What is PENDING (in priority order)

### High priority — needed for a complete submission

1. **Train a price forecaster.** The LightGBM baseline in `src/forecaster.py` is a placeholder. The user said they "will probably make a model and train it" — so they may want to try something fancier (LSTM, N-BEATS, ensemble, fundamental + ML residual). Whatever model goes here, it must produce a 15-min price series and conform to the `predict()` contract. **Validate by running `scripts/04_backtest.py`** afterwards and reporting capture ratio.

2. **Validate the MILP scheduler with a known-prices test.** Run `scheduler.optimize(realized_prices)` on a few sample days and visually sanity-check: SoC trajectory should ramp up at price troughs and discharge at peaks; daily cycles should respect the 1.5 cap. This is a 15-min smoke test before relying on the optimizer for the actual deliverable.

3. **Run end-to-end backtest** once a forecaster exists. Headline numbers to report to judges: **mean capture ratio**, mean realized revenue per day, total revenue over the test window, mean cycles/day. `04_backtest.py` already produces these.

### Medium priority — strengthens the submission

4. **ENTSO-E API integration.** User has emailed `transparency@entsoe.eu` for token. Once approved, set `ENTSOE_API_KEY` in `.env` and run `python scripts/01_fetch_data.py --skip-henex --skip-weather --skip-fuels`. This adds load forecasts, wind/solar forecasts, and actual generation as additional features. The features pipeline is already wired to consume them.

5. **Sensitivity analysis on battery params.** Run the backtest with different `BatterySpec` configs (smaller battery, lower efficiency, tighter cycle cap). Report how revenue scales. This is the "robustness under data scarcity" story the brief explicitly asks for.

6. **Forecast uncertainty / scenario robustness.** Generate forecast residual scenarios (e.g., bootstrap from historical errors), solve the MILP per scenario, report the variance. Or implement a simple stochastic MILP with N price scenarios. This directly addresses the brief's "data scarcity → robust framework" framing.

7. **Visualizations for the slide deck.** SoC trajectory + charge/discharge bars overlaid on price curve, for one good day and one bad day. Capture-ratio histogram. Feature importance chart from the model.

### Low priority — nice to have

8. **AggrCurves features.** HEnEx publishes aggregated bid curves (`AggrCurves` xlsx). Parsing them gives bid-stack steepness as a feature — strong predictor of price spikes. The HEnEx scraper already discovers these zips; only parsing logic is needed.

9. **Intraday rolling re-optimization.** Re-solve the MILP each MTU as new info arrives. Strong narrative for judges; mostly just calling `optimize()` in a sliding-window loop.

10. **ADMIE scraper.** Adds Greek-specific load/RES forecasts. Skip if ENTSO-E token arrives — they cover the same data.

---

## 6. Known Gotchas & Caveats

- **DST transitions** drop a handful of days from the HEnEx parser (~9 spring-forward Sundays across 2021–2025) due to the 23-hour day breaking the row-length invariant. Acceptable for now (<0.5% of data). Fix would be in `parse_results_summary` to handle row length 23/25.
- **`gen_bess_mw` is 99.6% NaN** because BESS only entered the market April 2026. We dropped it; this is correct.
- **Fuels are daily**, forward-filled to 15-min. Don't try to interpolate them — gas/carbon don't move in 15-min steps anyway.
- **Pre-Oct-2025 prices are hourly** repeated 4× per hour after upsampling. The `mtu_15m_active` flag tells the model when to expect within-hour variation.
- **`yfinance` returns `Close` as a wide DataFrame in newer versions.** The fuels module already defensively handles this; don't break it.
- **The HEnEx scraper caches downloads.** Re-running `henex.save([...])` is cheap. Zips live in `data/raw/henex/zips/`, extracted xlsx in `data/raw/henex/xlsx/`. If something looks wrong, deleting these forces a re-download.
- **Timezone is consistently Europe/Athens** throughout. Anything you add should be either in Athens TZ already or explicitly converted. Mixing TZs silently is the most likely source of bugs.
- **CBC is the MILP solver** (free, ships with pulp). 96 slots × 4 vars × 1 binary = solves in <1 second per day. No need to switch to commercial solvers.
- **The user is on Windows.** Use forward slashes in paths and `bash` (not PowerShell) syntax in shell commands; both shells are available.

---

## 7. User's Working Style (observed)

- Prefers concise updates, not narrated thinking.
- Wants quality over breadth — chose 28 months of clean data over 5 years of mixed-regime noise.
- Will iterate on the forecaster themselves; expects scaffolding, not a finished model.
- Comfortable with the MILP optimizer being the centerpiece — that's the deliverable, the forecaster is plumbing.
- Stops you and redirects when an approach is wrong; respect those redirects.

---

## 8. Immediate Next Action

The natural next step is to **train the baseline LightGBM** (`python scripts/03_train.py`) just to confirm the end-to-end pipeline runs cleanly and produces a sane MAE on the test window. This gives the user a benchmark to beat with whatever model they build next. It also surfaces any feature-quality issues before the user invests time in modeling.

After that: run the backtest (`scripts/04_backtest.py`) for an initial capture-ratio number.
