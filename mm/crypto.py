"""Crypto pilot (docs/evaluation_criteria.md § "Crypto pilot (C)", frozen 2026-09-17).

Research data is Binance's public spot archive (data.binance.vision); no account, no key.
Rules reuse the Route 3 machinery in mm/daily_scan.py. Paper trading, if ever, goes through
Alpaca's paper endpoint only — nothing in this module places orders.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import daily_scan as ds

ARCHIVE = "https://data.binance.vision/data/spot/monthly/klines"
UNIVERSE = Path(__file__).resolve().parent.parent / "docs" / "crypto" / "universe_2026-09-17.json"

DEV_START, DEV_END = "2018-01-01", "2022-12-31"
HOLDOUT_START, HOLDOUT_END = "2023-01-01", "2026-08-31"
ELIGIBLE_AFTER_DAYS = 90
TREND_LOOKBACKS = (10, 30, 90)
XMOM_LOOKBACK = 28
XMOM_TOP = 5
PRIMARY_ALPHA = 0.05 / 2
MIN_DEV_DAYS = 365
MIN_HOLDOUT_DAYS = 180
FINALIST_CAP = 5
TAKER_BPS, MAKER_BPS = 25.0, 15.0

KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
              "quote_volume", "trades", "taker_base", "taker_quote", "ignore"]


def load_universe(path: Path = UNIVERSE) -> dict:
    return json.loads(Path(path).read_text())["coins"]


def months(first: str, last: str) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(first, last, freq="M")]


def parse_klines(raw: bytes) -> pd.DataFrame:
    """One monthly zip → OHLCV with a UTC timestamp. Handles headers and µs timestamps."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        text = z.read(z.namelist()[0]).decode()
    df = pd.read_csv(io.StringIO(text), header=None, names=KLINE_COLS)
    df = df[pd.to_numeric(df["open_time"], errors="coerce").notna()]   # drop a header row
    t = df["open_time"].astype("int64")
    t = np.where(t > 10**14, t // 1000, t)                             # Binance spot: µs from 2025
    df["ts"] = pd.to_datetime(t, unit="ms")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return df[["ts", "open", "high", "low", "close", "volume"]]


def fetch_klines(symbol: str, interval: str, first: str, last: str, out: Path,
                 get=None) -> Path:
    """Download every monthly file into one CSV (cached: existing months are skipped)."""
    import requests
    get = get or (lambda url: requests.get(url, timeout=60))
    out.parent.mkdir(parents=True, exist_ok=True)
    have = None
    if out.exists():
        have = pd.read_csv(out)
        have["ts"] = pd.to_datetime(have["ts"], format="mixed")
    done = set(have["ts"].dt.strftime("%Y-%m")) if have is not None else set()
    frames = [have] if have is not None else []
    for m in months(first, last):
        if m in done:
            continue
        r = get(f"{ARCHIVE}/{symbol}/{interval}/{symbol}-{interval}-{m}.zip")
        if r.status_code == 404:
            continue
        r.raise_for_status()
        frames.append(parse_klines(r.content))
    df = pd.concat(frames).drop_duplicates("ts").sort_values("ts")
    df["ts"] = df["ts"].dt.floor("s")           # kline opens are always whole seconds;
    df.to_csv(out, index=False)                 # avoids a mixed .%f / no-.%f format on disk
    return out


def daily_frame(csv_path: Path) -> pd.DataFrame:
    """Daily bars indexed by UTC date, with `sig` = close (decision on the daily close)."""
    df = pd.read_csv(csv_path)
    df["ts"] = pd.to_datetime(df["ts"], format="mixed")
    idx = df["ts"].dt.strftime("%Y-%m-%d")
    return pd.DataFrame({"open": df["open"].values, "close": df["close"].values,
                         "sig": df["close"].values}, index=idx.values)


def trend_exposure(d: pd.DataFrame) -> pd.Series:
    """Mean over L of 1[close_s > close_{s-L}], decided on day s, held over day s+1."""
    close = d["close"]
    votes = [(close > close.shift(L)).astype(float).where(close.shift(L).notna())
             for L in TREND_LOOKBACKS]
    w = pd.concat(votes, axis=1).mean(axis=1, skipna=False)
    w[np.arange(len(w)) < ELIGIBLE_AFTER_DAYS] = np.nan
    return w.shift(1)


def trend_rows(d: pd.DataFrame, cost_bps: float, start: str, end: str) -> pd.DataFrame:
    w = trend_exposure(d)
    keep = (d.index >= start) & (d.index <= end)
    return ds.timing_rows(d[keep], w[keep], cost_bps)


def xmom_rows(panel: dict[str, pd.DataFrame], costs: dict[str, float], start: str,
              end: str) -> pd.DataFrame:
    """Weekly top-5 by 28-day return vs equal-weight eligible coins, days inside [start, end]."""
    gated = {}
    for s, d in panel.items():
        g = d.copy()
        g.iloc[:ELIGIBLE_AFTER_DAYS, g.columns.get_loc("sig")] = np.nan
        gated[s] = g
    # mm.daily_scan.xsec_rows measures sig_s against the close (lookback − 1) sessions back
    rows = ds.xsec_rows(gated, costs, XMOM_LOOKBACK + 1, highest=True, top=XMOM_TOP)
    if rows.empty:
        return rows
    rows["date"] = rows["date"].astype(str)
    return rows[(rows["date"] >= start) & (rows["date"] <= end)].reset_index(drop=True)


def open_close_gap_bps(d: pd.DataFrame) -> float:
    """Median |open(t+1)/close(t) − 1| — confirms 'fill at next open' ≈ 'at the close'."""
    return float(((d["open"].shift(-1) / d["close"] - 1).abs() * 1e4).median())


def seasonality(hourly_csv: Path, start: str, end: str) -> dict:
    """Gross mean bps by UTC hour and weekday (diagnostic only)."""
    h = pd.read_csv(hourly_csv)
    h["ts"] = pd.to_datetime(h["ts"], format="mixed")
    h = h[(h["ts"] >= pd.Timestamp(start)) & (h["ts"] < pd.Timestamp(end) + pd.Timedelta(days=1))]
    r = (h["close"] / h["open"] - 1) * 1e4
    by_hour = r.groupby(h["ts"].dt.hour).agg(["mean", "count"])
    by_dow = r.groupby(h["ts"].dt.dayofweek).sum() / h["ts"].dt.date.groupby(
        h["ts"].dt.dayofweek).nunique()
    return {"hour_mean_bps": {int(k): round(float(v), 2) for k, v in by_hour["mean"].items()},
            "weekday_mean_daily_bps": {int(k): round(float(v), 2) for k, v in by_dow.items()}}
