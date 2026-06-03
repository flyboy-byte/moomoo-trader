#!/usr/bin/env python3
"""Backtest VWAP Pullback strategy on historical CSV(s).

Usage:
    python scripts/backtest_vwap_pb.py logs/US_IWM_K_5M_2026-05-31.csv
    python scripts/backtest_vwap_pb.py --latest
    python scripts/backtest_vwap_pb.py --all          # all K_5M CSVs in logs/
    python scripts/backtest_vwap_pb.py --sweep        # sweep stop_mult × max_crosses
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from mm.indicators import add_all
from mm.vwap_pullback import run_vwap_pullback, print_vwap_pb_summary


def latest_csv() -> Path:
    csvs = sorted(Path("logs").glob("US_SPY_K_5M_*.csv"))
    if not csvs:
        raise FileNotFoundError("No US_SPY K_5M CSV in logs/")
    return csvs[-1]


def sweep(df: pd.DataFrame, days: int, sym: str) -> None:
    print(f"\n{'stop_mult':>10}  {'max_crosses':>12}  {'trades':>7}  {'win%':>6}  {'pnl':>9}  {'pf':>7}")
    print("-" * 60)
    for stop_m in [0.5, 0.75, 1.0, 1.25]:
        for max_c in [1, 2, 3, 4]:
            trades = run_vwap_pullback(df, stop_mult=stop_m, max_crosses=max_c)
            if not trades:
                continue
            wins = sum(1 for t in trades if t.pnl > 0)
            pnl = sum(t.pnl for t in trades)
            gw = sum(t.pnl for t in trades if t.pnl > 0)
            gl = abs(sum(t.pnl for t in trades if t.pnl <= 0))
            pf = gw / gl if gl else 999.0
            print(f"{stop_m:>10.2f}  {max_c:>12}  {len(trades):>7}  "
                  f"{100*wins/len(trades):>5.1f}%  {pnl:>+9.2f}  {pf:>7.3f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csvs", nargs="*")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--all", action="store_true", dest="all_csvs")
    parser.add_argument("--sweep", action="store_true")
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
            print(f"\n=== {sym} sweep ===")
            sweep(df, days, sym)
        else:
            trades = run_vwap_pullback(df)
            print()
            print_vwap_pb_summary(trades, symbol=sym, days=days)


if __name__ == "__main__":
    main()
