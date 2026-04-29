"""
Three-tier market data loader:
  1. ENTSO-E live API  (requires ENTSOE_API_KEY in .env)
  2. Parquet cache     (data/cache/market_cache.parquet)
  3. Synthetic demo    (data/demo/market_demo.parquet — generated on demand)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "cache" / "market_cache.parquet"
DEMO_PATH  = ROOT / "data" / "demo"  / "market_demo.parquet"
WEATHER_GLOB = "weather_*.parquet"


# ---------------------------------------------------------------------------
# Synthetic demo data
# ---------------------------------------------------------------------------

def _build_synthetic_prices(idx: pd.DatetimeIndex) -> pd.Series:
    """Generate realistic-looking Greek DAM prices for the given index."""
    rng = np.random.default_rng(42)
    hour  = idx.hour
    month = idx.month
    dow   = idx.dayofweek

    # Hourly price profile (EUR/MWh) — night valley → morning ramp →
    # midday solar depression → evening peak
    profile = np.array([
        45, 42, 40, 40, 42, 50,   # 00-05 night valley
        65, 80, 88, 85, 72, 52,   # 06-11 morning ramp + solar start
        38, 32, 32, 46, 68, 88,   # 12-17 solar depression → pre-peak
       105, 112, 108, 92, 75, 60, # 18-23 evening peak → fall-off
    ])
    base = profile[hour].astype(float)

    # Summer boosts solar depression; winter raises baseline
    summer_factor = np.sin(2 * np.pi * (month - 1) / 12)  # +1 in July, -1 in Jan
    midday = (hour >= 10) & (hour <= 15)
    base[midday] *= 1 - 0.25 * summer_factor[midday]       # midday cheaper in summer
    base += 6 * summer_factor                               # overall higher in winter

    # Weekend discount
    base[dow >= 5] *= 0.88

    # Correlated day-to-day noise (AR1)
    noise = rng.normal(0, 9, len(idx))
    for i in range(1, len(noise)):
        noise[i] = 0.6 * noise[i - 1] + 0.8 * noise[i]
    prices = np.clip(base + noise, -15, 280)
    return pd.Series(prices, index=idx, name="dam_price_eur_mwh")


def _build_synthetic_fuels(idx: pd.DatetimeIndex) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    n = len(idx)
    t = np.arange(n)
    ttf = 30 + 5 * np.sin(2 * np.pi * t / (24 * 365)) + rng.normal(0, 1.2, n)
    eua = 65 + 8 * np.sin(2 * np.pi * t / (24 * 365 * 2)) + rng.normal(0, 2, n)
    return pd.DataFrame({"ttf_eur_mwh": ttf, "eua_eur_t": eua}, index=idx)


def _build_synthetic_load_res(idx: pd.DatetimeIndex) -> pd.DataFrame:
    rng = np.random.default_rng(13)
    hour  = idx.hour
    month = idx.month
    n = len(idx)

    summer = np.sin(2 * np.pi * (month - 1) / 12)
    load_profile = np.array([
        4800, 4600, 4500, 4450, 4500, 4800,
        5400, 6000, 6400, 6600, 6500, 6400,
        6300, 6200, 6100, 6200, 6500, 7000,
        7200, 7100, 6800, 6300, 5800, 5200,
    ])
    load = load_profile[hour] + 400 * summer + rng.normal(0, 150, n)

    solar_max = np.maximum(0, np.sin(np.pi * (hour - 6) / 12)) * (hour >= 6) * (hour <= 19)
    solar = solar_max * (1600 + 400 * summer) + rng.normal(0, 80, n)
    solar = np.maximum(solar, 0)

    wind = 600 + 200 * rng.standard_normal(n)
    wind = np.maximum(wind, 0)

    return pd.DataFrame(
        {"load_forecast_mw": load, "res_total_forecast_mw": solar + wind},
        index=idx,
    )


def _make_demo() -> pd.DataFrame:
    from config import GR_TIMEZONE, RAW_DIR

    # Align with the real weather parquet already in data/raw/
    weather_files = sorted(RAW_DIR.glob(WEATHER_GLOB))
    if weather_files:
        wx = pd.read_parquet(weather_files[0])
        if wx.index.tz is None:
            wx.index = wx.index.tz_localize(GR_TIMEZONE)
        else:
            wx.index = wx.index.tz_convert(GR_TIMEZONE)
        wx = wx.resample("h").mean()
        idx = wx.index
    else:
        idx = pd.date_range("2024-01-01", "2026-04-29", freq="h", tz=GR_TIMEZONE)
        wx = pd.DataFrame(index=idx)

    prices  = _build_synthetic_prices(idx)
    fuels   = _build_synthetic_fuels(idx)
    load_res = _build_synthetic_load_res(idx)

    df = pd.concat([prices, load_res, fuels, wx], axis=1)
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def _ensure_demo() -> pd.DataFrame:
    if DEMO_PATH.exists():
        return pd.read_parquet(DEMO_PATH)
    print("[data_sources] generating synthetic demo data …")
    df = _make_demo()
    DEMO_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DEMO_PATH)
    print(f"[data_sources] demo saved → {DEMO_PATH}  rows={len(df)}")
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_market_data() -> tuple[pd.DataFrame, str]:
    """
    Returns (df, source) where source ∈ {'live', 'cache', 'demo'}.
    df always has dam_price_eur_mwh on a tz-aware DatetimeIndex.
    """
    # 1. Live ENTSO-E
    try:
        from config import ENTSOE_API_KEY, GR_TIMEZONE, RAW_DIR
        from src.data.entsoe_client import fetch_dam_prices
        from src.data.fuels import fetch_fuels
        from src.data.weather import fetch_weather

        if not ENTSOE_API_KEY:
            raise RuntimeError("no API key")

        end   = pd.Timestamp.now(tz=GR_TIMEZONE).normalize()
        start = end - pd.Timedelta(days=90)
        s, e  = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

        dam  = fetch_dam_prices(s, e).to_frame()
        wx   = fetch_weather(s, e)
        fuel = fetch_fuels(s, e)
        df   = dam.join(wx, how="left").join(fuel, how="left")
        df.to_parquet(CACHE_PATH)
        return df, "live"
    except Exception as exc:
        print(f"[data_sources] live fetch skipped: {exc}")

    # 2. Parquet cache
    if CACHE_PATH.exists():
        try:
            return pd.read_parquet(CACHE_PATH), "cache"
        except Exception as exc:
            print(f"[data_sources] cache load failed: {exc}")

    # 3. Synthetic demo
    return _ensure_demo(), "demo"
