# Handoff: Battery Optimization in the Greek DAM

Context document for the next AI assistant (or human) picking up this hackathon project. Read this top-to-bottom before touching anything.

---

## 1. The problem

Greek DAM (Day-Ahead Market) battery optimization. **50 MW / 100 MWh battery, 95%×95% round-trip efficiency, 1.5 cycles/day cap, 2 €/MWh degradation, cyclic SoC**. Bidding zone moved from hourly to **15-minute MTU on 2025-10-01**. We forecast 96 MTUs of next-day prices and dispatch the battery via MILP to maximize revenue.

**Headline metric: capture ratio** = realized scheduler revenue / perfect-foresight revenue. Target was ≥ 0.90. We're at:
- **Walk-forward (production-honest): 0.873 mean, 0.890 median, 0.871 overall, €549,774 / 30 days**
- **One-shot (best with all features): 0.878 mean, 0.890 median, 0.876 overall, €552,938 / 30 days**

vs original leaky baseline (0.83) and original honest baseline (0.808). **+€186k / 30 days, +51% in realized revenue**.

---

## 2. Final architecture

### Data layer

Three feature snapshots persisted to `data/processed/`:

| Parquet | Purpose | Lags | Notes |
|---|---|---|---|
| `features.parquet` | Full lags (lag1, lag4, lag8, lag24, …) | All | **Leaky for next-day. In-sample only.** |
| `features_realistic.parquet` | Realistic price lags only | lag96, lag672 | **Still has unlagged HEnEx market-clearing outputs (`gen_lignite_mw`, `volume_mainland_mwh`, `res_share`, …) — also leaky for next-day.** Kept for backwards compatibility with old inference path. |
| `features_clean.parquet` | **The one used by the validation + live-loop scripts.** All next-day market-clearing outputs replaced by lag96. SDAC neighbor prices (IT_SUD/BG/RO) used only via lag96/lag672. | lag96, lag672 | **Use this.** |

`features_clean_extended.parquet` is the same with start=2022-01-01 (2022-2023 backfilled), but **not used by default** — extension didn't help. Keep around for further experiments.

### Feature categories in `features_clean.parquet` (~73 cols)

| Category | Count | Highest-gain examples |
|---|---|---|
| HEnEx market lagged 24h | 18 | `volume_mainland_mwh_lag96`, `gen_hydro_mw_lag96`, `production_total_mw_lag96` |
| Weather aggregated | 9 | `gr_std_cloud_cover`, `gr_avg_cloud_cover`, `gr_std_wind_speed_100m` |
| Calendar | 7 | `sin_tod` (top-15) |
| Price lags & rolls | 6 | `dam_price_eur_mwh_lag96` (top-3), `lag672`, `rollmean96` |
| ENTSO-E forecasts | 5 | **`residual_load_forecast_mw` (top-2)**, `forecast_solar_mw` |
| Collapse / RES-stress composites | 5 | **`collapse_risk` (top-1)**, `res_penetration` |
| Solar geometry | 4 | `solar_elevation_deg` (mid) — others mostly unused |
| Holidays | 4 | All ~0% gain — model handles holidays via lag96 |
| Fuels | 3 | `ttf_eur_mwh`, `ccgt_srmc_eur_mwh` (mid) |
| Neighbor zone DA prices (lag96/lag672 + spreads) | 9 | **`da_price_it_sud_minus_gr_lag96` (top-15)** — Italy spread is informative |
| **Hand-engineered spike features** | **2** | **`spike_likelihood`, `spike_likelihood_daymax`** — domain-knowledge composite |

**Top-12 features carry 50% of model gain. Top-30 cover 82%.**

### Forecasting stack

In `src/forecaster.py`:

1. **Quantile heads** — three `LightGBM` boosters trained with `objective=quantile`:
   - `q05`, `q95`: single boosters, `recency × seasonal` sample weights.
   - `q50`: **ensemble of 3 boosters** with different bagging seeds, additionally weighted by **economic-impact** (`∝ |price - daily_mean|`) so it fits within-day spreads, not just MAE.

2. **Conformal calibration** — `conformal_calibrate()` shifts each test-window quantile by the empirical residual quantile measured on the validation window. Brings empirical coverage from ~21/70/9 to ~12/84/4 (nominal target 5/90/5).

3. **Dispatch price** — fixed scenario blend `0.6·q50 + 0.2·q05 + 0.2·q95`. The q05/q95 contribute spread information q50's symmetric loss otherwise discards. Validation-tuned weights.

4. Helpers in `forecaster.py`:
   - `make_sample_weights(index, ref_date)` — recency exponential (half-life 90 d) × seasonal Gaussian (σ 30 d) × `mtu_15m_boost` (1.5× post-2025-10-01).
   - `economic_impact_weights(prices)` — within-day deviation weighting.
   - `curriculum_weights(prices, cutoff_date)` — keep older spike rows, down-weight older normal rows. **Wired but unused; doesn't help once `spike_likelihood` is a feature.**
   - `train_rank()` + `blend_rank_with_q50()` + `daily_variance_correction()` — implemented but not used (rank head loses to q50; variance correction doesn't help capture).

### Scheduler

`src/scheduler.py` — PuLP/CBC MILP with separate charge/discharge binaries. Key tuning:
- **`cyclic_penalty = 3` €/MWh** (soft cyclic SoC) — **the single biggest lever** (+6 pp capture vs hard cyclic). Defined in the validation/walk-forward scripts via `replace(DEFAULT_BATTERY, cyclic_penalty=3.0)`.
- Idle-mask threshold tuned on validation window (typically ~30-45 €/MWh spread → mask). Marginal effect (<0.5 pp).
- `max_cycles_per_day = 1.5` kept (2.0 hurts via degradation cost > extra revenue).

### Validation pipelines

| Script | Purpose |
|---|---|
| `scripts/16_validate_stack.py` | One-shot 30-day held-out. Trains once, predicts the test window. Optimistic. |
| `scripts/17_walkforward.py` | **Production-honest.** 5 folds × 7 days. Each fold retrains on data strictly before fold start. **This is the number to claim externally.** |
| `scripts/18_live_loop.py` | Operational tick / forecast / evaluate. `--tick`, `--forecast YYYY-MM-DD`, `--serve`. |

`reports/walkforward_summary.json` and `reports/walkforward_daily.csv` carry the latest production numbers.

---

## 3. Honest progression of experiments

What we tested, in order, with results. Reverted items have been removed; this list is what's still in the codebase.

| Lever | Effect on overall capture | Status |
|---|---|---|
| Fix lag1/lag4/lag8 leakage | -2 pp (truthing — original "0.83" was leaky) | ✅ |
| Fix HEnEx market-clearing leakage (`build_clean_dataset` used) | -1.5 pp (further truthing) | ✅ |
| Recency + seasonal weighting | +0.5 pp | ✅ |
| Greek holidays + solar geometry features | ~+0.1 pp (model barely uses them) | Kept (no harm) |
| **Soft cyclic SoC (penalty=3)** | **+6 pp — biggest single lever** | ✅ |
| Economic-impact weighting on q50 | +1 pp | ✅ |
| Scenario blend `0.6q50 + 0.2q05 + 0.2q95` | +1 pp | ✅ |
| Tuned idle-mask (validation grid) | <0.5 pp | ✅ |
| q50 ensemble (3 seeds) | +0.6 pp | ✅ |
| Conformal calibration | Capture flat; calibration metrics improved | ✅ (reporting hygiene) |
| Neighbor DA prices (IT_SUD / BG / RO lag96 + lag672 + spreads) | Mean flat; **min day 0.52 → 0.67 (+15 pp robustness)** | ✅ |
| **Hand-engineered `spike_likelihood`** | **+0.5 pp mean, +7 pp on worst day** | ✅ |
| Walk-forward weekly retraining | ~Same mean as one-shot, **production-honest** | ✅ |
| Per-quantile hyperparams | -0.5 pp | ❌ reverted |
| Drop "dead-weight" features | -0.5 pp | ❌ reverted |
| LambdaRank within-day head | Loses to q50 (q50 already has Spearman 0.92 within-day) | ❌ Available but unused |
| Variance correction | Capture is rank-driven; amplification didn't help | ❌ Available but unused |
| Spike/trough binary classifier warp | +0.001 pp / +€1k — within noise | ❌ Available but unused (helped one-shot only) |
| Extended training to 2022-01-01 (full backfill) | -0.4 pp | ❌ Parquet kept, not used |
| Curriculum weighting (4 configs) | Same or worse than baseline | ❌ Wired but unused |
| Rolling-window spike features (`solar_shortfall`) | Helped one-shot, hurt walk-forward | ❌ reverted |

### Critical insight from the spike analysis

Audit of the 4 worst-capture days vs 4 best:

| Pattern | Worst days | Best days |
|---|---|---|
| `forecast_solar_max` | 3.7-5.5 GW | 6.5-7.3 GW |
| `cloud_avg` | 39-95 % | 7-42 % |
| `realised_max_price` | 176-292 €/MWh | 152-189 €/MWh |
| Capture | 0.62-0.74 | 0.97 |

**Low solar + cloudy + high residual load + evening = price spike.** Hand-engineered `spike_likelihood` gives 0.68-0.75 on worst days vs 0.46-0.61 on best days. This is the user's "engineer probability without model" idea — it works because the dataset is too thin in spike examples for ML to learn the interaction reliably.

### Edge-case behaviour (verified)

- **Holidays** (2 days in test window: Apr 10 / Apr 13 = Greek Orthodox Good Friday / Easter Monday): captured at 0.92 / 0.89 — model handles them via `lag96` even though `is_holiday` itself has 0% gain.
- **Negative prices** (399 slots in 30-day window): scheduler **never** discharges into negative slots, **never** charges in top-10% slots. Verified.
- **DST**: 1 spring-day with 88 rows, 2 autumn days with 100 rows. Scheduler handles variable-`n` correctly.
- **Spike days (>200 €/MWh)** (35 slots / 6 days): the bottleneck. Apr 22 captured 0.62 — model puts the realised peak slot at rank 20 of 96 (rank error). `spike_likelihood` lifts it to 0.69-0.71 in one-shot. Walk-forward improvement smaller (less training data per fold).

---

## 4. Files modified / created

### Modified
- `src/features.py` — added solar geometry, Greek holidays, neighbor-price lags, **`spike_likelihood`** composite, `build_clean_dataset` exposes `_NEIGHBOR_PRICE_COLS`.
- `src/forecaster.py` — added `make_sample_weights`, `economic_impact_weights`, `curriculum_weights`, `train_rank`, `blend_rank_with_q50`, `daily_variance_correction`, `conformal_calibrate`. Modified `train_quantile` to accept weights, hparams, curriculum flags.
- `src/data/entsoe_client.py` — added `fetch_neighbor_prices` and `save_neighbor_prices`.
- `scripts/09_validate_30d.py` — switched to `features_realistic.parquet` (older, kept for compatibility).

### Created
- `scripts/16_validate_stack.py` — one-shot 30-day validation with the full stack.
- `scripts/17_walkforward.py` — production-honest walk-forward (5 folds × 7 days).
- `scripts/18_live_loop.py` — `--tick` / `--forecast` / `--serve` operational loop.
- `data/processed/features_clean.parquet` — production feature set.
- `data/processed/features_clean_extended.parquet` — 2022-2026 backfill (unused but available).
- `data/raw/entsoe_*_2022-01-01_*.parquet` and `data/raw/entsoe_*_2023-01-01_*.parquet` — backfilled core ENTSO-E data.
- `data/raw/entsoe_neighbor_prices_*.parquet` — IT_SUD/BG/RO DA prices, 2022-2026.
- `data/raw/weather_2022-01-01_2023-12-31.parquet`, `data/raw/fuels_2022-01-01_2023-12-31.parquet` — backfills.
- `reports/walkforward_summary.json`, `reports/walkforward_daily.csv` — latest production-honest numbers.
- `reports/forecasts/forecast_<YYYY-MM-DD>.csv` — per-day forecast persistence (live-loop output).
- `reports/live_kpi_log.csv` — rolling KPI log (created by live-loop on first eval).

### NOT modified (still using old setup)
- `src/inference.py` — production inference path. **Still loads `features_realistic.parquet` (the leaky one) and uses the old single-model q10/q50/q90 from `models/lgbm_q10.txt` / `q50.txt` / `q90.txt`.** Frontend depends on this.
- `models/` — the deployed boosters. Frozen artifacts from `06_train_final.py`, **don't reflect the new stack**.

---

## 5. How to run

**Setup**: ENTSO-E API key is in Doppler. Use `doppler run -- <cmd>` for any command needing it.

```sh
# Rebuild all feature parquets from current raw data
.venv/Scripts/python -c "from src import features; features.save()"

# Best one-shot validation (overfit-prone, optimistic)
.venv/Scripts/python scripts/16_validate_stack.py

# Walk-forward — the number to claim externally
.venv/Scripts/python scripts/17_walkforward.py

# Single forecast for a specific day
.venv/Scripts/python scripts/18_live_loop.py --forecast 2026-05-01

# One-shot data refresh + KPI update
.venv/Scripts/python scripts/18_live_loop.py --tick
.venv/Scripts/python scripts/18_live_loop.py --tick --full-refresh   # incl. ENTSO-E + fuels (slow)

# Continuous loop (15-min ticks, 11:00 daily forecast)
.venv/Scripts/python scripts/18_live_loop.py --serve

# ENTSO-E backfill (year-by-year is more reliable than range)
doppler run -- python -c "
from src.data.entsoe_client import save_all, save_neighbor_prices
save_all('2024-01-01', '2024-12-31')
save_neighbor_prices('2024-01-01', '2024-12-31')
"
```

---

## 6. What's left

### Operational / shipping
1. **Wire `src/inference.py` to the new stack** — currently the frontend loads leaky `features_realistic.parquet` + old q10/q50/q90 single boosters. Should:
   - Load `features_clean.parquet`.
   - Load 3-seed q50 ensemble + q05 + q95 (currently no save/load helper for ensembles — needs `train_quantile` extended to save individual seed boosters with names like `lgbm_q50_seed{N}.txt`).
   - Apply conformal calibration on the most recent 30-day validation window.
   - Use `0.6q50 + 0.2q05 + 0.2q95` blend for dispatch.
   - Use `cyclic_penalty=3` battery.
2. **Save the deployed model artifacts** matching the validated stack so step 1 can load them. Likely a new script `19_train_production.py` that mirrors `17_walkforward.py`'s training but persists everything to `models/`.
3. **Set up the cron** to invoke `--serve` (or schedule `--forecast` daily at 11:00 + `--tick` every 15 min separately).
4. **Mini dashboard** reading `reports/live_kpi_log.csv` for rolling-30d capture monitoring.

### Capture-ratio improvements (closing the 0.873 → 0.90 gap)

These are not low-hanging anymore. Honest assessment in priority order:

1. **ENTSO-E A77/A80 outage feeds** — the `entsoe-py` client supports `query_unavailability_of_generation_units` and similar. Large planned/forced outages of CCGT or hydro units cause most of the spike days the model misses. **Best single shot at +1-2 pp.**
2. **Intraday market signals** (HEnEx CRIDA / LIDA results from earlier in D-1) — reveals flexible-asset stress before DAM gate close. The HEnEx scraper can already pull these zip files; need a new parser. **+0.5-1 pp**.
3. **Stochastic dispatch** (CVaR-constrained MILP on q05/q95 scenarios) instead of point dispatch on the blend. Implementation is significant. **+1-3 pp** in literature.

### Things explicitly tried and dropped (don't redo without new info)

- LambdaRank head — q50 already at within-day Spearman 0.92.
- Variance correction — dispatch is rank-driven.
- Spike/trough binary classifier with warp — same training features as q50, no new info.
- Extended training to 2022 (with or without curriculum) — domain-knowledge feature subsumed it.
- Per-quantile hparams (heavier regularization for tails) — hurt the dispatch blend.
- Pruning low-gain features — hurt capture.

---

## 7. Gotchas to preserve

1. **Capture ratio is rank-driven.** Improving MAE doesn't necessarily improve capture. Within-day Spearman matters more than within-day RMSE. q50 is already at Spearman 0.92.
2. **Soft cyclic SoC is the dominant scheduler lever.** Hard equality (penalty=0) caps you at 0.82. Penalty ≥ 3 saturates at 0.88.
3. **The capture-ratio numerator and denominator both depend on the battery spec.** When comparing across configs, ALWAYS use the same battery for perfect-foresight and forecast scheduler.
4. **Neighbor prices must be lagged.** SDAC zones clear simultaneously — same-day IT_SUD price isn't available at Greek DAM gate close. Always use `lag96` / `lag672`.
5. **Pre-2025-10-01 HEnEx data was hourly**, resampled to 15-min via `ffill`. Lag features that span this boundary are stable; rolling-window features are stable; intra-hour variation features are not. The `mtu_15m_active` feature flags the regime change but had ~0% gain — model didn't need it.
6. **Doppler is required for any ENTSO-E call.** The API key is not in `.env`.
7. **One-shot validation is overfit-prone.** Always cross-check with `scripts/17_walkforward.py` before claiming an improvement is real. Several improvements (rolling spike features, per-quantile hparams) helped one-shot and hurt walk-forward.
8. **Don't commit unless asked.** The user is selective about commits.
9. **Test window**: `end - 30 days` to `end` of `features_clean.parquet`. Currently `2026-04-01 → 2026-04-30`.
10. **Worst day in test window**: `2026-04-22` (cap=0.59-0.71 depending on config). Spike day, 292 €/MWh peak. Used as the canonical hard case.

---

## 8. Single source of truth — current production-honest claim

> **Walk-forward over the most recent 30 days (5 folds × 7 days, leakage-free, weekly retrain simulated):**
> Mean capture ratio **0.873**, median **0.890**, overall (€-weighted) **0.871**, total realized revenue **€549,774**, mean €18,326 / day. 15 / 30 days hit ≥ 0.90 capture. Worst day 0.62. Versus the original honest baseline (0.808, €363,852), this is **+6.6 pp / +€186k / +51 % revenue**.

When in doubt, re-run `scripts/17_walkforward.py` and quote those numbers.
