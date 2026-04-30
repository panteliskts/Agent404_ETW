from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from config import MODELS_DIR

TARGET = "dam_price_eur_mwh"
QUANTILE_ALPHAS = [0.05, 0.50, 0.95]


def _drop_target_leakage(features: pd.DataFrame) -> list[str]:
    return [c for c in features.columns if c != TARGET]


# ── sample-weighting helpers ────────────────────────────────────────────────
def curriculum_weights(
    prices: pd.Series,
    cutoff_date: str,
    older_normal_weight: float = 0.15,
    older_spike_weight: float = 1.0,
    spike_pct: float = 0.85,
) -> np.ndarray:
    """Curriculum weight: keep older SPIKE rows, down-weight older NORMAL rows.

    For rows on or after cutoff_date: weight = 1.0 (full).
    For rows before cutoff_date:
      - If price ≥ within-day spike_pct percentile: weight = older_spike_weight
      - Else:                                       weight = older_normal_weight

    The idea is to add 2022-2023's spike-pattern examples without polluting
    the model with their normal-day distribution (different gas-crisis regime).
    """
    cutoff = pd.Timestamp(cutoff_date)
    if prices.index.tz is not None and cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize(prices.index.tz)
    days = prices.index.normalize() if prices.index.tz is None else prices.index.tz_convert(prices.index.tz).normalize()
    day_arr = np.asarray(days.values)
    is_spike = np.zeros(len(prices), dtype=bool)
    p = prices.values.astype(float)
    for d in pd.unique(day_arr):
        m = day_arr == d
        if m.sum() < 2:
            continue
        thr = np.quantile(p[m], spike_pct)
        is_spike[m] = p[m] >= thr
    is_old = np.asarray(prices.index < cutoff)
    out = np.ones(len(prices), dtype=float)
    out[is_old & is_spike] = older_spike_weight
    out[is_old & ~is_spike] = older_normal_weight
    return out


def economic_impact_weights(
    prices: pd.Series,
    floor: float = 1.0,
    scale: float = 25.0,
) -> np.ndarray:
    """Per-row weight ∝ deviation from daily mean.

    Slots that are clear peaks or troughs within their day matter
    economically far more than mid-of-day slots. Down-weighting flat slots
    pushes the model to fit spreads over levels — which is what capture
    ratio actually rewards.
    """
    days = prices.index.normalize() if prices.index.tz is None else prices.index.tz_convert(prices.index.tz).normalize()
    day_arr = np.asarray(days.values)
    out = np.full(len(prices), floor, dtype=float)
    p = prices.values.astype(float)
    for d in pd.unique(day_arr):
        mask = day_arr == d
        if mask.sum() < 2:
            continue
        deviation = np.abs(p[mask] - p[mask].mean())
        out[mask] = floor + deviation / max(scale, 1e-6)
    return out


def make_sample_weights(
    index: pd.DatetimeIndex,
    ref_date: pd.Timestamp,
    recency_halflife_days: float = 90.0,
    seasonal_sigma_days: float = 30.0,
    mtu_15m_boost: float = 1.5,
    mtu_switch_date: str = "2025-10-01",
) -> np.ndarray:
    """
    Combined recency × seasonal weight for training rows.

    - Recency: exponential decay with given half-life (days before ref_date).
    - Seasonal: Gaussian on day-of-year distance to ref_date.
    - mtu_15m_boost: extra weight after the 15-min market switch (genuine 15-min
      variation, vs hourly-resampled pre-switch data).
    """
    if index.tz is None:
        raise ValueError("index must be tz-aware")
    ref = pd.Timestamp(ref_date).tz_convert(index.tz) if pd.Timestamp(ref_date).tzinfo else pd.Timestamp(ref_date, tz=index.tz)

    days_ago = (ref - index).total_seconds() / 86400.0
    days_ago = np.clip(days_ago.values, 0, None)
    w_recency = 0.5 ** (days_ago / max(recency_halflife_days, 1e-6))

    ref_doy = ref.dayofyear
    doy = np.asarray(index.dayofyear, dtype=float)
    diff = np.abs(doy - ref_doy)
    diff = np.minimum(diff, 365 - diff)
    w_seasonal = np.exp(-0.5 * (diff / max(seasonal_sigma_days, 1e-6)) ** 2)

    w = w_recency * w_seasonal

    if mtu_15m_boost != 1.0:
        switch = pd.Timestamp(mtu_switch_date, tz=index.tz)
        is_15m = np.asarray(index >= switch, dtype=float)
        w = w * (1.0 + (mtu_15m_boost - 1.0) * is_15m)

    # Normalize so mean weight = 1 (keeps LightGBM regularization scale stable)
    w = w / max(w.mean(), 1e-9)
    return w


@dataclass
class TrainResult:
    model: lgb.Booster
    feature_cols: list[str]
    metrics: dict = field(default_factory=dict)

    def save(self, name: str = "lgbm_dam") -> Path:
        out = MODELS_DIR / f"{name}.txt"
        self.model.save_model(str(out))
        meta = {"feature_cols": self.feature_cols, "metrics": self.metrics}
        (MODELS_DIR / f"{name}.json").write_text(json.dumps(meta, indent=2))
        return out


def time_split(df: pd.DataFrame, valid_days: int = 30, test_days: int = 30):
    end = df.index.max()
    test_start = end - pd.Timedelta(days=test_days)
    valid_start = test_start - pd.Timedelta(days=valid_days)
    train = df.loc[df.index < valid_start]
    valid = df.loc[(df.index >= valid_start) & (df.index < test_start)]
    test = df.loc[df.index >= test_start]
    return train, valid, test


def train(df: pd.DataFrame, valid_days: int = 30, test_days: int = 30) -> TrainResult:
    df = df.dropna(subset=[TARGET]).copy()
    feat_cols = _drop_target_leakage(df)

    train_df, valid_df, test_df = time_split(df, valid_days, test_days)

    dtrain = lgb.Dataset(train_df[feat_cols], train_df[TARGET])
    dvalid = lgb.Dataset(valid_df[feat_cols], valid_df[TARGET], reference=dtrain)

    params = {
        "objective": "regression",
        "metric": "mae",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "min_data_in_leaf": 30,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "verbose": -1,
    }
    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=4000,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(100), lgb.log_evaluation(period=200)],
    )

    preds = booster.predict(test_df[feat_cols], num_iteration=booster.best_iteration)
    metrics = {
        "test_mae": float(mean_absolute_error(test_df[TARGET], preds)),
        "test_rmse": float(np.sqrt(mean_squared_error(test_df[TARGET], preds))),
        "test_n": int(len(test_df)),
        "best_iter": int(booster.best_iteration),
    }
    print(f"  test MAE = {metrics['test_mae']:.2f} EUR/MWh   RMSE = {metrics['test_rmse']:.2f}")
    return TrainResult(model=booster, feature_cols=feat_cols, metrics=metrics)


_QUANTILE_PARAMS = {
    0.05: dict(learning_rate=0.05, num_leaves=63, min_data_in_leaf=30,
               feature_fraction=0.85, bagging_fraction=0.85),
    0.50: dict(learning_rate=0.05, num_leaves=63, min_data_in_leaf=30,
               feature_fraction=0.85, bagging_fraction=0.85),
    0.95: dict(learning_rate=0.05, num_leaves=63, min_data_in_leaf=30,
               feature_fraction=0.85, bagging_fraction=0.85),
}


def train_quantile(
    df: pd.DataFrame,
    alpha: float,
    valid_days: int = 30,
    test_days: int = 7,
    sample_weights: bool = True,
    recency_halflife_days: float = 90.0,
    seasonal_sigma_days: float = 30.0,
    economic_weight: bool = False,
    economic_weight_scale: float = 25.0,
    hparams: dict | None = None,
    curriculum_cutoff: str | None = None,
    curriculum_normal_weight: float = 0.15,
    curriculum_spike_weight: float = 1.0,
) -> TrainResult:
    """Train a single quantile-regression LightGBM model.

    sample_weights: combined recency+seasonal weight anchored at the start of
    the test window.
    economic_weight: extra multiplicative weight ∝ |price - daily_mean|.
    Pushes the model to fit within-day spreads; helps capture ratio more
    than uniform MAE minimisation.
    """
    df = df.dropna(subset=[TARGET]).copy()
    feat_cols = _drop_target_leakage(df)

    train_df, valid_df, test_df = time_split(df, valid_days, test_days)

    w_train = w_valid = None
    if sample_weights:
        ref = test_df.index.min() if len(test_df) else valid_df.index.max()
        w_train = make_sample_weights(
            train_df.index, ref_date=ref,
            recency_halflife_days=recency_halflife_days,
            seasonal_sigma_days=seasonal_sigma_days,
        )
        w_valid = make_sample_weights(
            valid_df.index, ref_date=ref,
            recency_halflife_days=recency_halflife_days,
            seasonal_sigma_days=seasonal_sigma_days,
        )
    if economic_weight:
        w_econ_train = economic_impact_weights(train_df[TARGET], scale=economic_weight_scale)
        w_econ_valid = economic_impact_weights(valid_df[TARGET], scale=economic_weight_scale)
        w_train = w_econ_train if w_train is None else w_train * w_econ_train
        w_valid = w_econ_valid if w_valid is None else w_valid * w_econ_valid
    if curriculum_cutoff is not None:
        w_cur_train = curriculum_weights(
            train_df[TARGET], curriculum_cutoff,
            older_normal_weight=curriculum_normal_weight,
            older_spike_weight=curriculum_spike_weight,
        )
        w_train = w_cur_train if w_train is None else w_train * w_cur_train
    if w_train is not None:
        w_train = w_train / max(w_train.mean(), 1e-9)
        w_valid = w_valid / max(w_valid.mean(), 1e-9)

    dtrain = lgb.Dataset(train_df[feat_cols], train_df[TARGET], weight=w_train)
    dvalid = lgb.Dataset(valid_df[feat_cols], valid_df[TARGET], weight=w_valid, reference=dtrain)

    hp = hparams if hparams is not None else _QUANTILE_PARAMS.get(alpha, _QUANTILE_PARAMS[0.50])
    params = {
        "objective": "quantile",
        "alpha": alpha,
        "metric": "quantile",
        "bagging_freq": 5,
        "verbose": -1,
        **hp,
    }
    early_patience = 200 if alpha != 0.5 else 80
    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=4000,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(early_patience), lgb.log_evaluation(period=0)],
    )

    preds = booster.predict(test_df[feat_cols], num_iteration=booster.best_iteration)
    metrics = {
        "alpha": alpha,
        "test_n": int(len(test_df)),
        "best_iter": int(booster.best_iteration),
    }
    return TrainResult(model=booster, feature_cols=feat_cols, metrics=metrics)


def train_all_quantiles(
    df: pd.DataFrame,
    valid_days: int = 30,
    test_days: int = 7,
) -> dict[str, TrainResult]:
    """Train q10, q50, q90 quantile models. Returns dict keyed by 'q10'/'q50'/'q90'."""
    results: dict[str, TrainResult] = {}
    for alpha in QUANTILE_ALPHAS:
        key = f"q{int(alpha * 100):02d}"
        print(f"  training {key} (alpha={alpha}) …")
        results[key] = train_quantile(df, alpha, valid_days, test_days)
        results[key].save(f"lgbm_{key}")
    return results


def predict_interval(
    models: dict[str, TrainResult],
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Return DataFrame with q10, q50, q90 forecast columns."""
    out = {}
    for key, result in models.items():
        raw = result.model.predict(
            features[result.feature_cols],
            num_iteration=result.model.best_iteration,
        )
        out[key] = pd.Series(raw, index=features.index)
    return pd.DataFrame(out)


class EnsembleBooster:
    """Mean-prediction wrapper over multiple lgb.Boosters sharing feature_cols.

    Mimics the small surface of lgb.Booster used by predict_interval:
      .predict(X, num_iteration=...) -> np.ndarray
      .best_iteration                -> int (max across members; predict ignores it per-booster)
      .feature_importance(importance_type=...) -> np.ndarray (mean across members)
    """

    def __init__(self, boosters: list[lgb.Booster]):
        if not boosters:
            raise ValueError("EnsembleBooster needs at least one booster")
        self._boosters = boosters

    @property
    def best_iteration(self) -> int:
        return max(int(b.best_iteration) for b in self._boosters)

    def predict(self, X, num_iteration=None):
        preds = []
        for b in self._boosters:
            preds.append(b.predict(X, num_iteration=int(b.best_iteration)))
        return np.mean(np.stack(preds, axis=0), axis=0)

    def feature_importance(self, importance_type: str = "gain"):
        imps = [b.feature_importance(importance_type=importance_type) for b in self._boosters]
        return np.mean(np.stack(imps, axis=0), axis=0)


def load_quantile_models() -> dict[str, TrainResult] | None:
    """Load pre-trained quantile models from disk. Returns None if any are missing.

    For q50, prefers the ensemble (lgbm_q50_seedN.txt files) when present,
    falling back to the single lgbm_q50.txt artifact.
    """
    results: dict[str, TrainResult] = {}
    for alpha in QUANTILE_ALPHAS:
        key = f"q{int(alpha * 100):02d}"

        if key == "q50":
            seed_files = sorted(MODELS_DIR.glob("lgbm_q50_seed*.txt"))
            seed_metas = sorted(MODELS_DIR.glob("lgbm_q50_seed*.json"))
            if seed_files and len(seed_files) == len(seed_metas):
                boosters = [lgb.Booster(model_file=str(p)) for p in seed_files]
                meta = json.loads(seed_metas[0].read_text())
                results[key] = TrainResult(
                    model=EnsembleBooster(boosters),
                    feature_cols=meta["feature_cols"],
                    metrics={"ensemble_size": len(boosters), **meta.get("metrics", {})},
                )
                continue

        model_path = MODELS_DIR / f"lgbm_{key}.txt"
        meta_path  = MODELS_DIR / f"lgbm_{key}.json"
        if not model_path.exists() or not meta_path.exists():
            return None
        booster = lgb.Booster(model_file=str(model_path))
        meta    = json.loads(meta_path.read_text())
        results[key] = TrainResult(
            model=booster,
            feature_cols=meta["feature_cols"],
            metrics=meta.get("metrics", {}),
        )
    return results


# ── Within-day rank head ────────────────────────────────────────────────────
# LambdaRank optimises NDCG, which is mathematically aligned with capture
# ratio: a battery cares about which 15-min slots are highest/lowest *within*
# the day, not about absolute price levels. A rank-only score is unitless
# (~0..1), so we blend it with q50 by mapping each daily rank to a
# percentile-matched price from q50's daily distribution.

def _daily_groups(idx: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Return (group_sizes ordered by index time, day_key_per_row).

    LightGBM ranking requires groups in the same row order as the dataset; we
    rely on the index being sorted ascending (callers pass sort_index'd df).
    """
    days = idx.tz_convert(idx.tz).normalize() if idx.tz is not None else idx.normalize()
    day_keys = np.asarray(days.values)
    # Counts in time order — np.unique sorts, but for sorted dt64 input that
    # ordering matches the index ordering so it's fine.
    _, counts = np.unique(day_keys, return_counts=True)
    return counts, day_keys


def _rank_label(prices: pd.Series, n_levels: int = 32) -> np.ndarray:
    """Discretise within-day price rank into 0..n_levels-1. LambdaRank needs ints."""
    days = prices.index.normalize() if prices.index.tz is None else prices.index.tz_convert(prices.index.tz).normalize()
    day_arr = np.asarray(days.values)
    out = np.zeros(len(prices), dtype=int)
    for d in pd.unique(day_arr):
        mask = day_arr == d
        if mask.sum() < 2:
            continue
        ranks = pd.Series(prices.values[mask]).rank(method="average", pct=True).values
        out[mask] = np.clip((ranks * (n_levels - 1)).round().astype(int), 0, n_levels - 1)
    return out


def train_rank(
    df: pd.DataFrame,
    valid_days: int = 30,
    test_days: int = 7,
    sample_weights: bool = True,
    recency_halflife_days: float = 90.0,
    seasonal_sigma_days: float = 30.0,
) -> TrainResult:
    """Train a LambdaRank model on within-day price rank.

    The output score is unitless; combine via `blend_rank_with_q50`.
    """
    df = df.dropna(subset=[TARGET]).sort_index().copy()
    feat_cols = _drop_target_leakage(df)
    train_df, valid_df, _ = time_split(df, valid_days, test_days)

    y_train = _rank_label(train_df[TARGET])
    y_valid = _rank_label(valid_df[TARGET])
    g_train, _ = _daily_groups(train_df.index)
    g_valid, _ = _daily_groups(valid_df.index)

    if sample_weights:
        ref = valid_df.index.max()
        w_train = make_sample_weights(train_df.index, ref_date=ref,
                                      recency_halflife_days=recency_halflife_days,
                                      seasonal_sigma_days=seasonal_sigma_days)
        w_valid = make_sample_weights(valid_df.index, ref_date=ref,
                                      recency_halflife_days=recency_halflife_days,
                                      seasonal_sigma_days=seasonal_sigma_days)
    else:
        w_train = w_valid = None

    dtrain = lgb.Dataset(train_df[feat_cols], y_train, group=g_train, weight=w_train)
    dvalid = lgb.Dataset(valid_df[feat_cols], y_valid, group=g_valid, weight=w_valid, reference=dtrain)

    params = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "ndcg_eval_at": [16, 32],
        "learning_rate": 0.05,
        "num_leaves": 63,
        "min_data_in_leaf": 30,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "label_gain": list(range(32)),
        "verbose": -1,
    }
    booster = lgb.train(
        params, dtrain,
        num_boost_round=2000,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(80, verbose=False), lgb.log_evaluation(period=0)],
    )
    return TrainResult(
        model=booster,
        feature_cols=feat_cols,
        metrics={"best_iter": int(booster.best_iteration), "task": "lambdarank"},
    )


def blend_rank_with_q50(
    q50: pd.Series,
    rank_score: pd.Series,
    weight: float = 0.4,
) -> pd.Series:
    """
    Per-day blend: replace each MTU's q50 with a convex combination of itself
    and the q50 value at the matching rank position from the rank model.

    For each calendar day:
      sorted_q50 = q50 sorted ascending
      rank_pos   = rank order of rank_score within the day (0..n-1)
      target     = sorted_q50[rank_pos]
      blended    = (1 - weight) * q50 + weight * target

    `target` shifts the daily *shape* toward the rank model's ordering while
    keeping the daily mean from q50.
    """
    out_vals = q50.values.copy().astype(float)
    days = q50.index.normalize() if q50.index.tz is None else q50.index.tz_convert(q50.index.tz).normalize()
    day_arr = np.asarray(days.values)
    for d in pd.unique(day_arr):
        mask = day_arr == d
        n = int(mask.sum())
        if n < 2:
            continue
        q_day = q50.values[mask]
        r_day = rank_score.values[mask]
        sorted_q = np.sort(q_day)
        order = np.argsort(np.argsort(r_day))
        target = sorted_q[order]
        out_vals[mask] = (1.0 - weight) * q_day + weight * target
    return pd.Series(out_vals, index=q50.index, name=q50.name)


def conformal_calibrate(
    valid_pred: pd.Series,
    valid_real: pd.Series,
    test_pred: pd.Series,
    alpha: float,
) -> pd.Series:
    """Empirical conformalization of a single quantile prediction.

    Computes the residual r = real - pred on the validation set and shifts
    test predictions by the empirical alpha-quantile of those residuals.
    For q05 (alpha=0.05): shift = 5th percentile of (real - pred), making
    coverage_below_q05 ≈ 5%. Symmetric for q95.

    Returns a new Series with the same index as `test_pred`.
    """
    r = (valid_real.values - valid_pred.values).astype(float)
    if len(r) == 0:
        return test_pred.copy()
    shift = float(np.quantile(r, alpha))
    return (test_pred + shift).rename(test_pred.name)


def daily_variance_correction(
    q50: pd.Series,
    target_std_eur: pd.Series | float,
    floor: float = 0.5,
) -> pd.Series:
    """Rescale q50 within each day so its std matches `target_std_eur`.

    Compressed predictions are the #1 reason capture ratio < 1: the
    optimizer can't pick peaks/troughs apart if q50 is too flat.
    """
    out_vals = q50.values.copy().astype(float)
    days = q50.index.normalize() if q50.index.tz is None else q50.index.tz_convert(q50.index.tz).normalize()
    day_arr = np.asarray(days.values)
    for d in pd.unique(day_arr):
        mask = day_arr == d
        if mask.sum() < 2:
            continue
        slice_ = q50.values[mask]
        cur_std = float(slice_.std())
        if cur_std < 1e-3:
            continue
        if isinstance(target_std_eur, pd.Series):
            tgt = float(target_std_eur.loc[pd.Timestamp(d)] if pd.Timestamp(d) in target_std_eur.index else target_std_eur.median())
        else:
            tgt = float(target_std_eur)
        scale = max(tgt / cur_std, floor)
        mean_ = slice_.mean()
        out_vals[mask] = mean_ + (slice_ - mean_) * scale
    return pd.Series(out_vals, index=q50.index, name=q50.name)


def predict(model: lgb.Booster, features: pd.DataFrame, feature_cols: list[str]) -> pd.Series:
    yhat = model.predict(features[feature_cols], num_iteration=model.best_iteration)
    return pd.Series(yhat, index=features.index, name="dam_price_forecast_eur_mwh")


def load(name: str = "lgbm_dam") -> tuple[lgb.Booster, list[str]]:
    booster = lgb.Booster(model_file=str(MODELS_DIR / f"{name}.txt"))
    meta = json.loads((MODELS_DIR / f"{name}.json").read_text())
    return booster, meta["feature_cols"]


# === Audit utilities (added for model selection / ablation) ===
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline


def train_ridge(
    df: pd.DataFrame,
    feature_cols: list[str] | None = None,
    valid_days: int = 30,
    test_days: int = 7,
    alpha: float = 1.0,
) -> dict:
    df = df.dropna(subset=[TARGET]).copy()
    feat_cols = feature_cols or _drop_target_leakage(df)
    train_df, _, test_df = time_split(df, valid_days, test_days)

    pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("ridge", Ridge(alpha=alpha)),
    ])
    pipe.fit(train_df[feat_cols], train_df[TARGET])
    preds = pipe.predict(test_df[feat_cols])
    return {
        "model": pipe,
        "feature_cols": feat_cols,
        "test_mae": float(mean_absolute_error(test_df[TARGET], preds)),
        "test_rmse": float(np.sqrt(mean_squared_error(test_df[TARGET], preds))),
        "n_train": len(train_df),
        "n_test": len(test_df),
    }


def feature_importance_table(booster: lgb.Booster, feature_cols: list[str]) -> pd.DataFrame:
    gain = booster.feature_importance(importance_type="gain")
    split = booster.feature_importance(importance_type="split")
    out = pd.DataFrame({"feature": feature_cols, "gain": gain, "split": split})
    out["gain_pct"] = 100 * out["gain"] / max(out["gain"].sum(), 1e-9)
    return out.sort_values("gain", ascending=False).reset_index(drop=True)


def _train_lgbm_quick(train_df, valid_df, feat_cols, num_boost_round=2000):
    dtrain = lgb.Dataset(train_df[feat_cols], train_df[TARGET])
    dvalid = lgb.Dataset(valid_df[feat_cols], valid_df[TARGET], reference=dtrain)
    params = {
        "objective": "regression",
        "metric": "mae",
        "learning_rate": 0.05,
        "num_leaves": 127,
        "min_data_in_leaf": 50,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "verbose": -1,
    }
    return lgb.train(
        params, dtrain, num_boost_round=num_boost_round,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(80), lgb.log_evaluation(period=0)],
    )


def rolling_origin_cv(
    df: pd.DataFrame,
    n_folds: int = 5,
    test_days: int = 14,
    valid_days: int = 14,
    feature_cols: list[str] | None = None,
    model: str = "lgbm",
    alpha: float = 1.0,
) -> pd.DataFrame:
    """Disjoint test windows of `test_days` each, anchored at the end and walking back."""
    df = df.dropna(subset=[TARGET]).sort_index().copy()
    feat_cols = feature_cols or _drop_target_leakage(df)
    end = df.index.max()
    rows = []
    for i in range(n_folds):
        test_end = end - pd.Timedelta(days=i * test_days)
        test_start = test_end - pd.Timedelta(days=test_days)
        valid_end = test_start
        valid_start = valid_end - pd.Timedelta(days=valid_days)
        train_df = df.loc[df.index < valid_start]
        valid_df = df.loc[(df.index >= valid_start) & (df.index < valid_end)]
        test_df = df.loc[(df.index >= test_start) & (df.index < test_end)]
        if len(train_df) < 1000 or len(test_df) < 50 or len(valid_df) < 50:
            continue
        if model == "lgbm":
            booster = _train_lgbm_quick(train_df, valid_df, feat_cols)
            preds = booster.predict(test_df[feat_cols], num_iteration=booster.best_iteration)
        elif model == "ridge":
            pipe = Pipeline([
                ("impute", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
                ("ridge", Ridge(alpha=alpha)),
            ])
            pipe.fit(train_df[feat_cols], train_df[TARGET])
            preds = pipe.predict(test_df[feat_cols])
        else:
            raise ValueError(f"unknown model {model}")
        rows.append({
            "fold": i,
            "test_start": test_start,
            "test_end": test_end,
            "n_train": len(train_df),
            "n_test": len(test_df),
            "mae": float(mean_absolute_error(test_df[TARGET], preds)),
            "rmse": float(np.sqrt(mean_squared_error(test_df[TARGET], preds))),
        })
    return pd.DataFrame(rows)
