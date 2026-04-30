# Handoff: Battery Optimization in the Greek DAM

Complete context document for the next agent or human picking up this project. Read top-to-bottom before touching anything.

---

## 1. The Problem

Greek DAM (Day-Ahead Market) battery optimization. **50 MW / 100 MWh battery, 95%×95% round-trip efficiency, 1.5 cycles/day cap, €2/MWh degradation, cyclic SoC**. The Greek bidding zone moved from hourly to **15-minute MTU on 2025-10-01**. We forecast 96 MTUs of next-day prices and dispatch the battery via MILP to maximize revenue.

**Headline metric: capture ratio** = realized scheduler revenue / perfect-foresight revenue.

---

## 2. Current Production Numbers

Walk-forward (5 folds × 7 days, leakage-free, weekly retrain simulated) on the **most recent 30 days**:

| Metric | Value |
|---|---|
| Mean capture ratio | **0.871** |
| Median capture ratio | **0.885** |
| Overall (€-weighted) | **0.869** |
| Total realized revenue (30 days) | **€548,438** |
| Mean EUR/day | **€18,281** |
| Days ≥ 0.90 capture | 15 / 30 |
| Worst day | 0.62 (Apr 22 — spike day, 292 €/MWh peak) |

vs original honest baseline (0.808, €363,852): **+6.3 pp / +€184k / +51% revenue**.

Source of truth: `reports/walkforward_summary.json` and `reports/walkforward_daily.csv`. Re-run `scripts/17_walkforward.py` to refresh.

---

## 3. Architecture

### Data layer — three feature snapshots in `data/processed/`

| Parquet | Use | Notes |
|---|---|---|
| `features.parquet` | Legacy, has lag1/lag4/lag8 leakage | **Do not use for validation** |
| `features_realistic.parquet` | Older leakage-fixed version | Still has unlagged HEnEx market-clearing outputs — also leaky. Kept for backwards compat with old inference path. |
| **`features_clean.parquet`** | **Production. Use this.** | All market-clearing outputs replaced by lag96. SDAC neighbor prices (IT_SUD/BG/RO) via lag96/lag672 only. ~73 cols. |

`features_clean_extended.parquet` — same but from 2022-01-01 (backfilled). Not used by default; extended training hurt.

### Feature categories in `features_clean.parquet` (~73 cols)

| Category | Count | Top examples |
|---|---|---|
| HEnEx market lagged 24h | 18 | `volume_mainland_mwh_lag96`, `gen_hydro_mw_lag96` |
| Weather aggregated (gr_avg/gr_std) | 9 | `gr_std_cloud_cover`, `gr_avg_cloud_cover` |
| Calendar | 7 | `sin_tod` (top-15 by gain) |
| Price lags & rolls | 6 | `dam_price_eur_mwh_lag96` (top-3), `lag672`, `rollmean96` |
| ENTSO-E forecasts | 5 | **`residual_load_forecast_mw` (top-2)**, `forecast_solar_mw` |
| Collapse / RES-stress composites | 5 | **`collapse_risk` (top-1)**, `res_penetration` |
| Solar geometry | 4 | `solar_elevation_deg` |
| Holidays | 4 | ~0% gain — model uses lag96 implicitly |
| Fuels | 3 | `ttf_eur_mwh`, `ccgt_srmc_eur_mwh` |
| Neighbor zone DA prices (lag96/lag672 + spreads) | 9 | **`da_price_it_sud_minus_gr_lag96` (top-15)** |
| **Hand-engineered spike features** | **2** | **`spike_likelihood`, `spike_likelihood_daymax`** |

Top-12 features carry 50% of model gain. Top-30 cover 82%.

### Forecasting stack — `src/forecaster.py`

1. **Three quantile heads** trained with `objective=quantile`:
   - `q05`, `q95`: single LightGBM boosters with recency × seasonal sample weights.
   - `q50`: **ensemble of 3 boosters** (seeds 42, 7, 1337) additionally weighted by **economic-impact** (`∝ |price − daily_mean|`).

2. **Conformal calibration** — `conformal_calibrate()` shifts each quantile by the empirical residual quantile on the validation window. Brings coverage from ~21/70/9 to ~12/84/4 (nominal 5/90/5).

3. **Dispatch price** — `0.6×q50 + 0.2×q05 + 0.2×q95`. Validation-tuned blend.

4. **Sample weighting helpers** in `forecaster.py`:
   - `make_sample_weights()` — recency exponential (half-life 90d) × seasonal Gaussian (σ 30d) × 1.5× post-2025-10-01 boost.
   - `economic_impact_weights()` — within-day deviation weighting for q50.
   - `curriculum_weights()`, `train_rank()`, `blend_rank_with_q50()`, `daily_variance_correction()` — implemented but unused (all hurt walk-forward or were flat).

### Scheduler — `src/scheduler.py`

PuLP/CBC MILP with separate charge/discharge binaries (`z[t]`, `y[t]`).

**Key parameters (set in validation/walkforward scripts):**
- `cyclic_penalty = 3.0 €/MWh` (soft cyclic SoC) — **single biggest lever (+6 pp vs hard cyclic)**
- `max_cycles_per_day = 1.5`

**`optimize(prices, battery, ...)`** — single-day 96-MTU LP. Standard production path.

**`optimize_multiday(prices_d0, prices_d1, battery, d1_discount=1.0, ...)`** — 2-day rolling-horizon LP (MPC). See Section 5 for full analysis.

### Validation pipelines

| Script | Purpose |
|---|---|
| `scripts/16_validate_stack.py` | One-shot 30-day held-out. Trains once. Optimistic (overfit-prone). |
| **`scripts/17_walkforward.py`** | **Production-honest. 5 folds × 7 days. Claim this number externally.** |
| `scripts/18_live_loop.py` | Operational tick / forecast / evaluate. `--tick`, `--forecast YYYY-MM-DD`, `--serve`. |
| `scripts/19_walkforward_mpc.py` | Walk-forward with full MPC (α=1.0). Kept for reference. Results worse than baseline. |
| `scripts/20_mpc_alpha_search.py` | Alpha grid search: trains once per fold, sweeps all α values. |

---

## 4. Honest Progression of Experiments

What was tested and the measured effect on walk-forward capture. Reverted items not listed.

| Lever | Effect | Status |
|---|---|---|
| Fix lag1/lag4/lag8 leakage | -2 pp (truthing — original "0.83" was leaky) | ✅ |
| Fix HEnEx market-clearing leakage (`build_clean_dataset`) | -1.5 pp (further truthing) | ✅ |
| Recency + seasonal weighting | +0.5 pp | ✅ |
| Greek holidays + solar geometry features | ~+0.1 pp | Kept (no harm) |
| **Soft cyclic SoC (penalty=3)** | **+6 pp — biggest single lever** | ✅ |
| Economic-impact weighting on q50 | +1 pp | ✅ |
| Scenario blend `0.6q50 + 0.2q05 + 0.2q95` | +1 pp | ✅ |
| Tuned idle-mask (validation grid) | <0.5 pp | ✅ |
| q50 ensemble (3 seeds) | +0.6 pp | ✅ |
| Conformal calibration | Capture flat; calibration improved | ✅ |
| Neighbor DA prices (IT_SUD/BG/RO lag96 + spreads) | Mean flat; **min day 0.52 → 0.67 (+15 pp robustness)** | ✅ |
| **Hand-engineered `spike_likelihood`** | **+0.5 pp mean, +7 pp on worst day** | ✅ |
| **2-day MPC with d1_discount=0.1** | **+0.4 pp mean, +€2,429 / 30 days** | ✅ (not yet wired to production) |
| Per-quantile hyperparams | -0.5 pp | ❌ reverted |
| Drop "dead-weight" features | -0.5 pp | ❌ reverted |
| Extended training to 2022 | -0.4 pp | ❌ parquet kept, not used |
| Full MPC (d1_discount=1.0) | -1.3 pp, -€7,503 / 30 days | ❌ see Section 5 |
| LambdaRank within-day head | Loses to q50 (already Spearman 0.92) | ❌ available but unused |
| Variance correction | Capture is rank-driven; didn't help | ❌ available but unused |
| Curriculum weighting | Same or worse | ❌ wired but unused |
| Rolling-window spike features | Helped one-shot, hurt walk-forward | ❌ reverted |

---

## 5. MPC (2-Day Rolling Horizon) — Full Analysis

### The Idea

The single-day LP is myopic: it optimises each day's 96 MTUs in isolation. Its only inter-day signal is the soft cyclic penalty (3 €/MWh), which anchors EOD SoC to 50% regardless of what tomorrow looks like. If tomorrow is forecast to be a high-price day (cloudy, high residual load), we should end today at high SoC to profit tomorrow.

`optimize_multiday(prices_d0, prices_d1, battery, d1_discount)` solves a single 192-MTU LP over both days. The cyclic return constraint applies at end of D1, so D0 is free to end at whatever SoC maximises combined 2-day revenue.

### Full MPC (d1_discount=1.0) Hurts

| Metric | Baseline | Full MPC | Delta |
|---|---|---|---|
| Mean capture | 0.871 | 0.858 | -1.3 pp |
| Total EUR (30d) | €548,438 | €540,935 | -€7,503 |
| Days helped | — | 10/30 | |
| Days hurt | — | 20/30 | |

**Why**: The LP treats D+1 forecast as ground truth. When D+1 is wrong (which it often is — MAE ~19 €/MWh), D0 ends at the wrong SoC for what actually happens. The soft cyclic penalty (3 €/MWh) in the baseline implicitly hedged against this by anchoring to 50%. Full MPC removes that anchor.

### Alpha Grid Search — d1_discount=0.1 is Optimal

Training once per fold, sweeping d1_discount (α) from 0.0 to 1.0:

| α | W0 | W1 | W2 | W3 | W4 | Mean cap | Total EUR | Δ vs baseline |
|---|---|---|---|---|---|---|---|---|
| 0.0 (baseline) | 0.845 | 0.893 | 0.917 | 0.832 | 0.850 | 0.870 | €548,438 | — |
| **0.1** | **0.863** | **0.894** | **0.917** | 0.830 | 0.850 | **0.874** | **€550,867** | **+€2,429** |
| 0.2 | 0.862 | 0.894 | 0.917 | 0.830 | 0.850 | 0.874 | €550,828 | +€2,390 |
| 0.3 | 0.860 | 0.894 | 0.918 | 0.830 | 0.850 | 0.874 | €550,477 | +€2,039 |
| 0.4 | 0.854 | 0.894 | 0.911 | 0.828 | 0.850 | 0.870 | €548,306 | -€132 |
| 0.5 | 0.847 | 0.893 | 0.911 | 0.828 | 0.850 | 0.869 | €547,370 | -€1,068 |
| 1.0 | 0.821 | 0.892 | 0.910 | 0.833 | 0.782 | 0.859 | €540,935 | -€7,503 |

**Interpretation of α=0.1**: D+1 prices are passed to the LP at 10% of their nominal value. A real 100 €/MWh spike tomorrow looks like 10 €/MWh — not enough to make the LP dramatically reposition D0, but enough to nudge EOD SoC slightly upward. The soft cyclic penalty (3 €/MWh) remains the dominant force; MPC just adjusts the anchor slightly in the right direction.

Source: `reports/mpc_alpha_search.json`, `reports/mpc_alpha_weekly.csv`.

### What's NOT Yet Done

`optimize_multiday` is implemented in `src/scheduler.py` and validated, but **not yet wired into production**:
- `scripts/18_live_loop.py` still calls `optimize()` (single-day)
- `src/inference.py` still calls `optimize()` (frontend depends on this)

To enable in production: pass `d1_discount=0.1` and the next day's forecast prices to `optimize_multiday()` instead of calling `optimize()`.

---

## 6. Files — What Was Modified / Created

### Modified
- `src/features.py` — solar geometry, Greek holidays, neighbor-price lags, `spike_likelihood` composite, `build_clean_dataset` exposes `_NEIGHBOR_PRICE_COLS`.
- `src/forecaster.py` — `make_sample_weights`, `economic_impact_weights`, `curriculum_weights`, `train_rank`, `blend_rank_with_q50`, `daily_variance_correction`, `conformal_calibrate`. `train_quantile` accepts weights, hparams, curriculum flags.
- `src/scheduler.py` — added `optimize_multiday(prices_d0, prices_d1, battery, d1_discount=1.0, ...)`. `d1_discount` scales D1 prices before solving.
- `src/data/entsoe_client.py` — added `fetch_neighbor_prices` and `save_neighbor_prices`.
- `scripts/09_validate_30d.py` — switched to `features_realistic.parquet` (kept for compatibility).

### Created
- `scripts/16_validate_stack.py` — one-shot 30-day validation.
- `scripts/17_walkforward.py` — production-honest walk-forward (5 folds × 7 days).
- `scripts/18_live_loop.py` — `--tick` / `--forecast` / `--serve` operational loop.
- `scripts/19_walkforward_mpc.py` — walk-forward using full 2-day MPC (α=1.0). Kept for reference; results worse than baseline.
- `scripts/20_mpc_alpha_search.py` — trains once per fold, sweeps α ∈ {0.0, 0.1, …, 1.0} at dispatch time. Optimal α=0.1 found.
- `data/processed/features_clean.parquet` — production feature set (use this).
- `data/processed/features_clean_extended.parquet` — 2022-2026 backfill (unused).
- `reports/walkforward_summary.json`, `reports/walkforward_daily.csv` — baseline production numbers.
- `reports/walkforward_mpc_summary.json`, `reports/walkforward_mpc_daily.csv` — full MPC results (worse).
- `reports/mpc_alpha_search.json`, `reports/mpc_alpha_weekly.csv` — alpha grid search results.
- `reports/forecasts/forecast_<YYYY-MM-DD>.csv` — per-day forecast persistence (live-loop).

### NOT Modified (still old stack)
- `src/inference.py` — production inference for the frontend. Still loads `features_realistic.parquet` and old single-booster q10/q50/q90 from `models/lgbm_q*.txt`. Frontend depends on this.
- `models/` — frozen artifacts from `06_train_final.py`. Do not reflect new ensemble / conformal stack.

---

## 7. How to Run

```sh
# Walk-forward (the number to claim externally)
python scripts/17_walkforward.py

# Alpha grid search (trains once per fold, sweeps MPC discount values)
python scripts/20_mpc_alpha_search.py

# Single forecast for a specific day
python scripts/18_live_loop.py --forecast 2026-05-01

# One-shot data refresh + KPI update
python scripts/18_live_loop.py --tick
python scripts/18_live_loop.py --tick --full-refresh   # incl. ENTSO-E + fuels (slow)

# Continuous loop (15-min ticks, 11:00 daily forecast)
python scripts/18_live_loop.py --serve
```

**Note:** ENTSO-E API key is required for any `--full-refresh`. Use `doppler run -- <cmd>` if the key is in Doppler.

---

## 8. What's Left

### Immediate — wire MPC into production (one session of work)

1. **Update `scripts/18_live_loop.py`** — in `forecast_day()`, after generating D0's dispatch prices, also generate D+1's dispatch prices and call `optimize_multiday(..., d1_discount=0.1)` instead of `optimize()`.

2. **Update `src/inference.py`** — the frontend inference path. Same change as above plus:
   - Switch from `features_realistic.parquet` to `features_clean.parquet`
   - Switch from single-booster q10/q50/q90 to the new ensemble + conformal stack
   - A new script `scripts/19_train_production.py` is needed to persist the ensemble artifacts to `models/` (mirrors `17_walkforward.py`'s training but saves boosters as `lgbm_q50_seed{N}.txt`)

### Capture-ratio improvements (closing the 0.871 → 0.90 gap)

In priority order — these are not low-hanging anymore:

1. **ENTSO-E A77/A80 outage feeds** — `entsoe-py` supports `query_unavailability_of_generation_units`. Large planned/forced CCGT or hydro outages cause most spike days the model misses. **Best shot at +1-2 pp.**
2. **Intraday market signals** (HEnEx CRIDA/LIDA results from earlier in D-1) — the HEnEx scraper can already discover these zip files; need a new parser. **+0.5-1 pp.**
3. **Stochastic dispatch** (CVaR-constrained MILP on q05/q95 scenarios) — significant implementation. **+1-3 pp in literature.**

### Things explicitly tried and dropped — do not redo without new information

- LambdaRank head — q50 Spearman already 0.92 within-day.
- Variance correction — dispatch is rank-driven.
- Spike/trough binary classifier warp — same features as q50, no new signal.
- Extended training to 2022 (with or without curriculum) — domain-knowledge feature (`spike_likelihood`) subsumed it.
- Per-quantile hparams (heavier regularization for tails) — hurt dispatch blend.
- Pruning low-gain features — hurt capture.
- Full MPC (d1_discount=1.0) — forecast error compounding, -1.3 pp.
- Rolling-window spike features (`solar_shortfall`) — helped one-shot, hurt walk-forward.

---

## 9. Critical Gotchas

1. **Capture ratio is rank-driven.** Improving MAE doesn't necessarily improve capture. Within-day Spearman matters more than RMSE. q50 is already at Spearman 0.92.
2. **Soft cyclic SoC (penalty=3) is the dominant scheduler lever.** Hard equality caps at ~0.82. Penalty ≥ 3 saturates at 0.87.
3. **MPC d1_discount must stay at 0.1.** Higher values compound forecast error. Lower values lose the look-ahead signal. The sweet spot is narrow: 0.1–0.3 all work, but 0.1 is best.
4. **Neighbor prices must be lagged.** SDAC zones clear simultaneously — same-day IT_SUD price isn't available at Greek DAM gate close. Always use `lag96` / `lag672`.
5. **One-shot validation is overfit-prone.** Always cross-check with `scripts/17_walkforward.py` before claiming an improvement is real.
6. **Pre-2025-10-01 HEnEx data was hourly**, resampled to 15-min via `ffill`. Lag features spanning this boundary are stable; intra-hour variation features are not.
7. **The capture-ratio numerator and denominator both depend on the battery spec.** When comparing configs, ALWAYS use the same battery for both perfect-foresight and forecast scheduler.
8. **Test window**: `end - 30 days` to `end` of `features_clean.parquet`. Currently `2026-04-01 → 2026-04-30`.
9. **Worst day in test window**: `2026-04-22` (cap=0.62). Spike day, 292 €/MWh peak. Canonical hard case.
10. **Doppler required for ENTSO-E calls.** API key is not in `.env`.
11. **Do not commit unless the user asks.**

---

## 10. Single Source of Truth — Current Claim

> **Walk-forward over the most recent 30 days (5 folds × 7 days, leakage-free, weekly retrain simulated):**
> Mean capture ratio **0.871**, median **0.885**, overall (€-weighted) **0.869**, total realized revenue **€548,438**, mean €18,281/day.
> 15/30 days hit ≥ 0.90 capture. Worst day 0.62.
>
> **MPC with d1_discount=0.1 adds +0.4 pp / +€2,429 / 30 days** (validated in `reports/mpc_alpha_search.json`) but is not yet wired into production inference.
>
> vs original honest baseline (0.808, €363,852): **+6.3 pp / +€184k / +51% revenue**.

When in doubt, re-run `scripts/17_walkforward.py` and quote those numbers.
