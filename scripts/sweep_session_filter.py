#!/usr/bin/env python3
"""Sweep BB+KDJ entry session filters — find which hours hurt and which help.

Tests a set of blocked-hour combinations against the baseline (no filter).
Exits always fire; only entries are suppressed during blocked hours.

Usage:
    python scripts/sweep_session_filter.py --all
    python scripts/sweep_session_filter.py logs/US_IWM_K_5M_combined.csv
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from mm.indicators import add_all
from mm.strategy import run_signals, Signal

FILTERS: list[tuple[str, set[int]]] = [
    ("baseline (no filter)",          set()),
    ("block 10-11",                   {10, 11}),
    ("block 14",                      {14}),
    ("block 10-11 + 14",              {10, 11, 14}),
    ("block 10-11 + 13-14",           {10, 11, 13, 14}),
    ("block 10-12",                   {10, 11, 12}),
    ("block 10-12 + 13-14",           {10, 11, 12, 13, 14}),
    ("open + close only (9 + 15-16)", {10, 11, 12, 13, 14}),
    ("open only (9)",                 {10, 11, 12, 13, 14, 15, 16}),
    ("close only (15-16)",            {9, 10, 11, 12, 13, 14}),
    ("block first hour (9)",          {9}),
    ("block last hour (15-16)",       {15, 16}),
]


def run_filter(df: pd.DataFrame, blocked: set[int]) -> dict:
    result = run_signals(df.copy(), blocked_hours=blocked or None)
    trades = []
    pos = None
    for _, row in result.iterrows():
        if row["signal"] == Signal.ENTRY:
            pos = {"entry": row["close"], "hour": pd.Timestamp(row["time_key"]).hour}
        elif pos and row["signal"] in (Signal.EXIT_TARGET, Signal.EXIT_STOP_LOSS):
            trades.append(row["close"] - pos["entry"])
            pos = None
    if not trades:
        return {"trades": 0, "win_pct": 0, "pnl": 0, "pf": 0, "per_trade": 0}
    wins = [p for p in trades if p > 0]
    losses = [p for p in trades if p <= 0]
    gw = sum(wins)
    gl = abs(sum(losses))
    return {
        "trades": len(trades),
        "win_pct": 100 * len(wins) / len(trades),
        "pnl": sum(trades),
        "pf": gw / gl if gl else 999.0,
        "per_trade": sum(trades) / len(trades),
    }


def sweep_file(path: Path) -> None:
    sym = path.stem.split("_K_")[0].replace("_", ".", 1)
    df = pd.read_csv(path)
    df["time_key"] = pd.to_datetime(df["time_key"])
    df = df.sort_values("time_key").reset_index(drop=True)
    df = add_all(df)
    days = df["time_key"].dt.date.nunique()

    print(f"\n=== {sym}  ({days} trading days) ===")
    print(f"{'Filter':<38}  {'Trades':>7}  {'Win%':>6}  {'PnL':>9}  {'PF':>7}  {'$/trade':>8}")
    print("-" * 82)

    baseline = None
    for label, blocked in FILTERS:
        r = run_filter(df, blocked)
        if baseline is None:
            baseline = r
        delta = f"  ({r['pnl'] - baseline['pnl']:+.2f})" if baseline and label != "baseline (no filter)" else ""
        print(f"  {label:<36}  {r['trades']:>7}  {r['win_pct']:>5.1f}%  "
              f"{r['pnl']:>+9.2f}{delta:<10}  {r['pf']:>6.3f}  {r['per_trade']:>+8.3f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csvs", nargs="*")
    parser.add_argument("--all", action="store_true", dest="all_csvs")
    args = parser.parse_args()

    if args.all_csvs:
        paths = sorted(Path("logs").glob("*_K_5M_combined.csv"))
        if not paths:
            paths = sorted(Path("logs").glob("US_*_K_5M_*.csv"))
    elif args.csvs:
        paths = [Path(p) for p in args.csvs]
    else:
        paths = sorted(Path("logs").glob("*_K_5M_combined.csv")) or \
                sorted(Path("logs").glob("US_SPY_K_5M_*.csv"))[-1:]

    for path in paths:
        sweep_file(path)


if __name__ == "__main__":
    main()
