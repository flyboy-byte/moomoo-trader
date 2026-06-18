#!/usr/bin/env python3
"""Backtest EMA Momentum Breakout strategy on historical CSV(s).

Usage:
    python scripts/backtest_ema_momentum.py logs/US_SPY_K_5M_2026-05-30.csv
    python scripts/backtest_ema_momentum.py --latest
    python scripts/backtest_ema_momentum.py --all
    python scripts/backtest_ema_momentum.py --sweep
    python scripts/backtest_ema_momentum.py --sweep --entry pullback
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from mm.backtest import profit_factor
from mm.indicators import add_all
from mm.ema_momentum import run_ema_momentum, print_ema_summary


def latest_csv() -> Path:
    csvs = sorted(Path("logs").glob("US_SPY_K_5M_*.csv"))
    if not csvs:
        raise FileNotFoundError("No US_SPY K_5M CSV in logs/")
    return csvs[-1]


def sweep(df: pd.DataFrame, days: int, sym: str, entry_type: str) -> None:
    print(f"\n=== {sym}  entry={entry_type} ===")
    print(f"{'target':>8}  {'stop':>6}  {'adx':>5}  {'trades':>7}  {'win%':>6}  {'pnl':>9}  {'pf':>7}")
    print("-" * 62)
    for target_m in [0.5, 1.0, 1.5, 2.0]:
        for stop_m in [0.5, 1.0, 1.5]:
            for adx_min in [20.0, 25.0, 30.0]:
                trades = run_ema_momentum(
                    df,
                    target_mult=target_m,
                    stop_mult=stop_m,
                    adx_min=adx_min,
                    entry_type=entry_type,
                )
                if not trades:
                    continue
                wins = sum(1 for t in trades if t.pnl > 0)
                pnl = sum(t.pnl for t in trades)
                pf = profit_factor(trades)
                print(f"{target_m:>8.1f}  {stop_m:>6.2f}  {adx_min:>5.0f}  "
                      f"{len(trades):>7}  {100*wins/len(trades):>5.1f}%  "
                      f"{pnl:>+9.2f}  {pf:>7.3f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csvs", nargs="*")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--all", action="store_true", dest="all_csvs")
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--entry", choices=["cross", "pullback"], default="cross")
    args = parser.parse_args()

    if args.all_csvs:
        paths = sorted(Path("logs").glob("US_*_K_5M_*.csv"))
    elif args.latest:
        paths = [latest_csv()]
    elif args.csvs:
        paths = [Path(p) for p in args.csvs]
    else:
        paths = [latest_csv()]

    for path in paths:
        sym = path.stem.split("_K_")[0].replace("_", ".", 1)
        df = pd.read_csv(path)
        df["time_key"] = pd.to_datetime(df["time_key"])
        df = df.sort_values("time_key").reset_index(drop=True)
        df = add_all(df)
        days = df["time_key"].dt.date.nunique()

        if args.sweep:
            sweep(df, days, sym, args.entry)
        else:
            trades = run_ema_momentum(df, entry_type=args.entry)
            print()
            print_ema_summary(trades, symbol=sym, days=days)


if __name__ == "__main__":
    main()
