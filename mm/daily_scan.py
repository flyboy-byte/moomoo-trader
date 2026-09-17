"""Route 3 — daily-horizon scan (docs/evaluation_criteria.md, "Route 3", frozen 2026-09-17).

Daily bars are built from the Step 9 five-minute files. Every rule decides on the *signal
price* (the close 15 minutes before the session's last bar) and fills at the session close,
so no rule ever sees the price it trades at. Nothing here imports mm.config.

Exposure convention: ``w[t]`` is the exposure held over day t (close t-1 → close t), decided
from information at the signal time of day t-1.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

STRATEGIES = ("R3-ON", "R3-TREND", "R3-VOL", "R3-MOM", "R3-REV")
PER_SYMBOL = ("R3-ON", "R3-TREND", "R3-VOL")
PRIMARY_ALPHA = 0.05 / len(STRATEGIES)
MIN_LANE_OBS = 250
SIGNAL_BARS_BEFORE_LAST = 3        # 15:45 bar when the last bar is 16:00
MIN_SESSION_BARS = 10
TREND_LOOKBACK = 200
VOL_WINDOW = 20
VOL_MIN_HISTORY = 60
XSEC_TOP = 10
MOM_LOOKBACK = 126
REV_LOOKBACK = 5


def build_daily(csv_path: str | Path) -> pd.DataFrame:
    """One row per regular session: open, close, sig (signal price), indexed by date."""
    df = pd.read_csv(csv_path, usecols=["time_key", "open", "close"])
    df["date"] = df["time_key"].str[:10]
    df = df.sort_values("time_key")
    g = df.groupby("date", sort=True)
    n = g.size()
    out = pd.DataFrame({
        "open": g["open"].first(),
        "close": g["close"].last(),
        "sig": g["close"].agg(lambda s: s.iloc[-(SIGNAL_BARS_BEFORE_LAST + 1)]
                              if len(s) > SIGNAL_BARS_BEFORE_LAST else np.nan),
    })
    return out[n >= MIN_SESSION_BARS]


def window(daily: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    return daily[(daily.index >= start) & (daily.index <= end)]


# ── per-symbol rules ────────────────────────────────────────────────────────────

def overnight_rows(d: pd.DataFrame, cost_bps: float) -> pd.DataFrame:
    """Close t → open t+1, dated t. The last session has no next open and is dropped."""
    gross = (d["open"].shift(-1) / d["close"] - 1) * 1e4
    r = pd.DataFrame({"date": d.index, "gross_bps": gross.values,
                      "turnover": 1.0}).dropna()
    r["net_bps"] = r["gross_bps"] - cost_bps
    return r


def trend_exposure(d: pd.DataFrame) -> pd.Series:
    """Decision on day s: sig_s > mean(close_{s-200..s-1}); held over day s+1."""
    sma = d["close"].shift(1).rolling(TREND_LOOKBACK).mean()
    decision = (d["sig"] > sma).astype(float).where(sma.notna())
    return decision.shift(1)


def vol_exposure(d: pd.DataFrame) -> pd.Series:
    """min(1, m/v); v = std of the 19 prior returns + the return to the signal price."""
    close = d["close"].to_numpy()
    sig = d["sig"].to_numpy()
    n = len(d)
    rets = np.full(n, np.nan)
    rets[1:] = close[1:] / close[:-1] - 1
    v = np.full(n, np.nan)
    for s in range(VOL_WINDOW, n):
        window_rets = np.append(rets[s - VOL_WINDOW + 1:s], sig[s] / close[s - 1] - 1)
        if np.isfinite(window_rets).all():
            v[s] = window_rets.std(ddof=1)
    vs = pd.Series(v, index=d.index)
    m = vs.shift(1).expanding(min_periods=VOL_MIN_HISTORY).median()
    decision = (m / vs).clip(upper=1.0)
    return decision.shift(1)


def timing_rows(d: pd.DataFrame, w: pd.Series, cost_bps: float) -> pd.DataFrame:
    """(w_t − w̄)·r_t − |Δw|·cost/2, per day, over days where w is defined."""
    r = d["close"].pct_change()
    turnover = w.diff().abs()
    first = w.first_valid_index()
    if first is not None:
        turnover.loc[first] = w.loc[first]      # entering from flat
    ok = w.notna() & r.notna()
    w, r, turnover = w[ok], r[ok], turnover[ok].fillna(0.0)
    if w.empty:
        return pd.DataFrame(columns=["date", "gross_bps", "net_bps", "turnover", "w", "r"])
    gross = (w - w.mean()) * r * 1e4
    return pd.DataFrame({"date": w.index, "gross_bps": gross.values,
                         "net_bps": (gross - turnover * cost_bps / 2).values,
                         "turnover": turnover.values, "w": w.values, "r": r.values})


# ── cross-sectional rules ───────────────────────────────────────────────────────

def week_keys(dates) -> list[str]:
    iso = pd.to_datetime(pd.Series(list(dates))).dt.isocalendar()
    return [f"{y}-W{w:02d}" for y, w in zip(iso["year"], iso["week"])]


def xsec_rows(panel: dict[str, pd.DataFrame], costs: dict[str, float], lookback: int,
              highest: bool, top: int = XSEC_TOP) -> pd.DataFrame:
    """Weekly top/bottom-N by lookback return vs equal-weight all, both net of turnover."""
    close = pd.DataFrame({s: d["close"] for s, d in panel.items()}).sort_index()
    sig = pd.DataFrame({s: d["sig"] for s, d in panel.items()}).reindex(close.index)
    rets = close.pct_change(fill_method=None)
    past = close.apply(lambda c: c.dropna().shift(lookback - 1).reindex(c.index))
    score = sig / past - 1        # sig_s / close_{s-lookback}, each symbol on its own sessions
    weeks = week_keys(close.index)
    rebal = [i for i in range(len(close) - 1) if weeks[i] != weeks[i + 1]]
    cost = pd.Series({s: costs[s] for s in close.columns})

    port_w = pd.Series(0.0, index=close.columns)
    bench_w = pd.Series(0.0, index=close.columns)
    out = []
    rebal_set = set(rebal)
    started = False
    for i in range(len(close) - 1):
        t = i + 1
        port_cost = bench_cost = 0.0
        if i in rebal_set:
            sc = score.iloc[i].dropna()
            sc = sc[close.iloc[i].reindex(sc.index).notna()]
            if len(sc) >= top * 2:
                chosen = (sc.nlargest(top) if highest else sc.nsmallest(top)).index
                new_p = pd.Series(0.0, index=close.columns)
                new_p[chosen] = 1.0 / top
                new_b = pd.Series(0.0, index=close.columns)
                new_b[sc.index] = 1.0 / len(sc)
                port_cost = float(((new_p - port_w).abs() * cost).sum() / 2)
                bench_cost = float(((new_b - bench_w).abs() * cost).sum() / 2)
                port_w, bench_w, started = new_p, new_b, True
        if not started:
            continue
        r = rets.iloc[t].fillna(0.0)
        gross = float((port_w * r).sum() - (bench_w * r).sum()) * 1e4
        out.append({"date": close.index[t], "gross_bps": gross,
                    "net_bps": gross - port_cost + bench_cost,
                    "port_bps": float((port_w * r).sum()) * 1e4 - port_cost,
                    "bench_bps": float((bench_w * r).sum()) * 1e4 - bench_cost,
                    "turnover": float((port_cost > 0) or (bench_cost > 0))})
    return pd.DataFrame(out)


# ── statistics ──────────────────────────────────────────────────────────────────

def stat(values, keys, extra_cost=None) -> dict:
    from . import stats
    vals = np.asarray(values, dtype=float)
    if extra_cost is not None:
        vals = vals - np.asarray(extra_cost, dtype=float)
    if len(vals) == 0:
        return {"n": 0, "p_one_sided": 1.0}
    keys = list(keys)
    lo, hi = stats.bootstrap_mean_ci(vals, block_keys=keys)
    pp = stats.prob_positive(vals, block_keys=keys)
    return {"n": int(len(vals)), "blocks": len(set(keys)), "mean_bps": float(vals.mean()),
            "ci": (lo, hi), "p_one_sided": 1.0 if pp != pp else 1.0 - pp}


def sharpe_and_dd(daily_bps) -> dict:
    r = np.asarray(daily_bps, dtype=float) / 1e4
    if len(r) < 2 or r.std(ddof=1) == 0:
        return {"sharpe": None, "max_dd_pct": None, "total_pct": None}
    eq = np.cumprod(1 + r)
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    return {"sharpe": float(r.mean() / r.std(ddof=1) * np.sqrt(252)),
            "max_dd_pct": float(dd * 100), "total_pct": float((eq[-1] - 1) * 100)}
