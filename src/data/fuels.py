from __future__ import annotations

import pandas as pd
import yfinance as yf

from config import GR_TIMEZONE, RAW_DIR

# yfinance proxies — pragmatic free fallback. Swap for an ICE/EEX feed in production.
TTF_TICKER = "TTF=F"
EUA_TICKER = "CO2.L"


def _daily(ticker: str, start: str, end: str, name: str) -> pd.Series:
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"yfinance returned empty for {ticker}")
    s = df["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize("UTC").tz_convert(GR_TIMEZONE)
    s.name = name
    return s


def fetch_ttf(start: str, end: str) -> pd.Series:
    return _daily(TTF_TICKER, start, end, "ttf_eur_mwh")


def fetch_eua(start: str, end: str) -> pd.Series:
    return _daily(EUA_TICKER, start, end, "eua_eur_t")


def fetch_fuels(start: str, end: str) -> pd.DataFrame:
    parts = {}
    try:
        parts["ttf"] = fetch_ttf(start, end)
    except Exception as exc:
        print(f"[fuels] TTF fetch failed: {exc}")
    try:
        parts["eua"] = fetch_eua(start, end)
    except Exception as exc:
        print(f"[fuels] EUA fetch failed: {exc}")
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts.values(), axis=1).ffill()


def save(start: str, end: str) -> None:
    df = fetch_fuels(start, end)
    if df.empty:
        print("[fuels] nothing to save")
        return
    path = RAW_DIR / f"fuels_{start}_{end}.parquet"
    df.to_parquet(path)
    print(f"  saved {path.name}  rows={len(df)}")
