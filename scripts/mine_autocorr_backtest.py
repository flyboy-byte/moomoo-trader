#!/usr/bin/env python3
"""H3 follow-up: translate IWM 9:30-10:00 lag-1 autocorr into a trading rule.

Signal: lag-1 5-min return autocorr r=-0.185 p<0.0001 on IWM in 9:30-10:00 window.
Trade rule: fade the previous bar's direction — enter at close of bar t-1, exit at close of bar t.
IS=2022-2023, OOS=2024+.

Usage:
    python scripts/mine_autocorr_backtest.py
    python scripts/mine_autocorr_backtest.py --symbol US.IWM
    python scripts/mine_autocorr_backtest.py --all        # all three symbols
    python scripts/mine_autocorr_backtest.py --oos-only
"""
from __future__ import annotations

import argparse
import sys
from datetime import time as dtime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.backtest import load_candles

LOGS = Path(__file__).parent.parent / "logs"
IS_START = "2022-01-01"
IS_END   = "2023-12-31"
OOS_START = "2024-01-01"

# Bars in the 9:30-10:00 window (labeled at close time)
_WINDOW_TIMES = {dtime(9, 35), dtime(9, 40), dtime(9, 45), dtime(9, 50), dtime(9, 55), dtime(10, 0)}


def _csv_path(symbol: str) -> Path:
    return LOGS / f"{symbol.replace('.', '_')}_K_5M_combined.csv"


def _simulate(df: pd.DataFrame, start: str, end: str) -> list[float]:
    """Simulate lag-1 fade trades. Returns list of pnl-in-bps per trade."""
    df = df.copy()
    df["_ts"] = pd.to_datetime(df["time_key"])
    df["_date"] = df["_ts"].dt.date
    df["_time"] = df["_ts"].dt.time
    df["_ret"] = df["close"].pct_change()
    df.loc[df["_date"] != df["_date"].shift(1), "_ret"] = float("nan")

    slice_df = df[(df["time_key"] >= start) & (df["time_key"] <= end)].copy()

    pnls: list[float] = []
    for i in range(1, len(slice_df)):
        row = slice_df.iloc[i]
        prev = slice_df.iloc[i - 1]

        if row["_time"] not in _WINDOW_TIMES:
            continue
        if row["_date"] != prev["_date"]:
            continue
        if pd.isna(prev["_ret"]) or prev["_ret"] == 0:
            continue

        entry = float(prev["close"])
        exit_ = float(row["close"])
        # Fade: if prev bar up → short (pnl = entry - exit); if prev bar down → long (exit - entry)
        raw_pnl = (entry - exit_) if prev["_ret"] > 0 else (exit_ - entry)
        pnls.append(raw_pnl / entry * 1e4)   # in bps
    return pnls


def _pf(pnls: list[float]) -> float:
    gains = sum(p for p in pnls if p > 0)
    losses = sum(-p for p in pnls if p < 0)
    return gains / losses if losses > 0 else float("inf")


def _report(pnls: list[float], label: str) -> None:
    if not pnls:
        print(f"  {label:<20}  n=0  —")
        return
    wins = sum(1 for p in pnls if p > 0)
    pf = _pf(pnls)
    avg_bps = sum(pnls) / len(pnls)
    pf_str = f"{pf:.3f}" if pf != float("inf") else "inf"
    print(f"  {label:<20}  n={len(pnls):<5}  win%={100*wins/len(pnls):>5.1f}  PF={pf_str}  avg_bps={avg_bps:+.2f}")


def _run_symbol(symbol: str, oos_only: bool) -> None:
    path = _csv_path(symbol)
    if not path.exists():
        print(f"  Missing: {path}")
        return

    df = load_candles(path)
    print(f"\n{symbol}")
    print(f"  {'Period':<20}  {'N':<6}  {'Win%':>6}  {'PF':>6}  {'avg_bps':>8}")
    print(f"  {'-'*55}")

    if not oos_only:
        is_pnls = _simulate(df, IS_START, IS_END)
        _report(is_pnls, f"IS  {IS_START[:4]}-{IS_END[:4]}")

    oos_pnls = _simulate(df, OOS_START, "2099-12-31")
    _report(oos_pnls, f"OOS {OOS_START[:4]}+")

    if not oos_only and is_pnls and oos_pnls:
        is_pf = _pf(is_pnls)
        oos_pf = _pf(oos_pnls)
        gap = abs(is_pf - oos_pf)
        # Require BOTH IS and OOS to show edge — if IS is near 1.0, signal was discovered in OOS
        # period (no truly held-out validation possible).
        consistent = gap < 0.15
        deployable = is_pf >= 1.1 and oos_pf >= 1.1 and len(oos_pnls) >= 50
        note = "IS near random — signal discovered in OOS, no held-out validation" if is_pf < 1.05 else ""
        print(f"  IS→OOS gap: {gap:.3f}  {'consistent' if consistent else 'degraded'}  "
              f"deploy={'YES' if deployable else 'NO'}"
              + (f"  ← {note}" if note else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="H3 autocorr backtest: lag-1 fade in 9:30-10:00")
    parser.add_argument("--symbol", default="US.IWM", help="Symbol to test (default: US.IWM)")
    parser.add_argument("--all", action="store_true", dest="all_syms",
                        help="Run all three symbols (SPY/QQQ/IWM)")
    parser.add_argument("--oos-only", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("H3 Autocorr Backtest — Lag-1 Fade, 9:30-10:00 ET Window")
    print("  Rule: fade previous 5-min bar direction (1-bar hold)")
    print("=" * 60)

    symbols = ["US.SPY", "US.QQQ", "US.IWM"] if args.all_syms else [args.symbol]
    for sym in symbols:
        _run_symbol(sym, args.oos_only)

    print()


if __name__ == "__main__":
    main()
