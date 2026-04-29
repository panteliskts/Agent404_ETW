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
QUANTILE_ALPHAS = [0.10, 0.50, 0.90]


def _drop_target_leakage(features: pd.DataFrame) -> list[str]:
    return [c for c in features.columns if c != TARGET]


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
        "num_leaves": 127,
        "min_data_in_leaf": 50,
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


def train_quantile(
    df: pd.DataFrame,
    alpha: float,
    valid_days: int = 30,
    test_days: int = 7,
) -> TrainResult:
    """Train a single quantile-regression LightGBM model."""
    df = df.dropna(subset=[TARGET]).copy()
    feat_cols = _drop_target_leakage(df)

    train_df, valid_df, test_df = time_split(df, valid_days, test_days)

    dtrain = lgb.Dataset(train_df[feat_cols], train_df[TARGET])
    dvalid = lgb.Dataset(valid_df[feat_cols], valid_df[TARGET], reference=dtrain)

    params = {
        "objective": "quantile",
        "alpha": alpha,
        "metric": "quantile",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "min_data_in_leaf": 50,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "verbose": -1,
    }
    booster = lgb.train(
        params,
        dtrain,
        num_boost_round=2000,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(80), lgb.log_evaluation(period=500)],
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


def load_quantile_models() -> dict[str, TrainResult] | None:
    """Load pre-trained quantile models from disk. Returns None if any are missing."""
    results: dict[str, TrainResult] = {}
    for alpha in QUANTILE_ALPHAS:
        key = f"q{int(alpha * 100):02d}"
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


def _train_lgbm_quick(train_df, valid_df, feat_cols, num_boost_round=2000, params_override: dict | None = None):
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
    if params_override:
        params.update(params_override)
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
    lgbm_params: dict | None = None,
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
            booster = _train_lgbm_quick(train_df, valid_df, feat_cols, params_override=lgbm_params)
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
