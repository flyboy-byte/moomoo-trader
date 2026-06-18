"""
Pre-market feature derivation for Gap Fade research.

Research-only module — NOT imported by mm/paper.py or mm/gap_fade.py's live path.
Three independent deep-research passes (see docs/deep/) converged on pre-market
fill % and pre-market volume tier as the best informational-vs-noise gap
discriminators, ahead of gap size alone. This module derives those features
from extended-hours candles (mm/data.py fetch_candles(extended_time=True))
and joins them onto the existing Gap Fade day map (mm/gap_fade.py::_build_day_map).

Moomoo's docs state extended-hours history "may be less than 2 years" — the
window actually available is a live-test unknown, not assumed here.
"""
from __future__ import annotations

from datetime import time as dtime

import pandas as pd

from .indicators import atr as _atr

# US premarket session per Moomoo/Nasdaq convention: 4:00 AM - 9:30 AM ET.
_PREMARKET_START = dtime(4, 0)
_PREMARKET_END = dtime(9, 30)
# Reference point for "how much of the gap is left standing right before the bell".
_FILL_REFERENCE_TIME = dtime(9, 25)


def premarket_session(df_ext: pd.DataFrame) -> dict:
    """Slice an extended-hours DataFrame into {date: premarket_bars_df}.

    df_ext must have a `time_key` column (as returned by fetch_candles).
    Bars are end-labeled (5-min bar covering 9:25-9:30 is labeled 9:30:00 —
    see mm/gap_fade.py's "first bar closes at 9:35" convention), so the
    premarket window is [4:00, 9:30] INCLUSIVE of the 9:30 label. Using an
    exclusive upper bound would silently drop the last premarket bar every
    day (bug fix 2026-06-17) without double-counting into RTH, since RTH's
    first label is 9:35, not 9:30.
    """
    df = df_ext.copy()
    df["_ts"] = pd.to_datetime(df["time_key"])
    df["_date"] = df["_ts"].dt.date
    df["_time"] = df["_ts"].dt.time

    sessions: dict = {}
    mask = (df["_time"] >= _PREMARKET_START) & (df["_time"] <= _PREMARKET_END)
    pm = df[mask]
    for date, grp in pm.groupby("_date"):
        sessions[date] = grp.sort_values("_ts").reset_index(drop=True)
    return sessions


def premarket_fill_pct(prev_close: float, today_open: float, premarket_bars: pd.DataFrame) -> float | None:
    """Fraction of the overnight gap already retraced by ~9:25 ET.

    0.0 = gap fully intact at the reference time (worst case for a fade that
    hasn't happened yet). 1.0 = gap already fully closed pre-bell. Can exceed
    1.0 if price overshot through prev_close, or go negative if it widened.
    Returns None if no premarket bar exists at/before the reference time.
    """
    if premarket_bars.empty or today_open == prev_close:
        return None
    candidates = premarket_bars[premarket_bars["_time"] <= _FILL_REFERENCE_TIME]
    if candidates.empty:
        return None
    ref_price = float(candidates.iloc[-1]["close"])
    gap = today_open - prev_close
    return (ref_price - prev_close) / gap


def premarket_volume_ratio(today_premarket_vol: float, rolling_20d_avg: float) -> float | None:
    """Today's pre-market volume vs the trailing 20-session pre-market average."""
    if rolling_20d_avg <= 0:
        return None
    return today_premarket_vol / rolling_20d_avg


def build_premarket_volume_history(sessions: dict) -> pd.Series:
    """Return a date-indexed Series of total pre-market volume per day, sorted by date.

    Use this to compute each day's trailing 20-day average via
    `series.rolling(20).mean().shift(1)` (shift(1) so the average never
    includes the day it's being applied to).
    """
    dates = sorted(sessions.keys())
    vols = [float(sessions[d]["volume"].sum()) for d in dates]
    return pd.Series(vols, index=pd.to_datetime(dates))


def gap_atr_mult(gap_pct: float, close: float, atr_value: float | None) -> float | None:
    """Normalize gap size by ATR (gap in dollars / ATR in dollars).

    Reuses mm.indicators.atr() output — pass the previous day's last-bar ATR
    value (computed on the existing RTH 5-min series) as atr_value.
    """
    if atr_value is None or atr_value <= 0:
        return None
    gap_dollars = abs(gap_pct) * close
    return gap_dollars / atr_value


def attach_atr(df_rth: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Thin wrapper around mm.indicators.atr() for callers that just need the
    last-bar-of-day ATR series to feed into gap_atr_mult()."""
    return _atr(df_rth, period=period)
