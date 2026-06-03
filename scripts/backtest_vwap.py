#!/usr/bin/env python3
"""Backtest the VWAP mean-reversion scalp strategy against historical candle CSVs.

Usage:
    python scripts/backtest_vwap.py logs/US_IWM_K_5M_2026-05-31.csv
    python scripts/backtest_vwap.py --latest              # most recent K_5M CSV per symbol
    python scripts/backtest_vwap.py --all                 # all K_5M CSVs in logs/
    python scripts/backtest_vwap.py --start 2024-01-01 --end 2025-12-31 logs/US_IWM_K_5M*.csv
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.backtest import load_candles
from mm.vwap_strategy import run_vwap_signals, print_vwap_summary


def _run_file(path: Path, start: str | None, end: str | None) -> None:
    print(f"\n{'='*60}")
    print(f"File: {path.name}")
    df = load_candles(path)
    if start:
        df = df[df["time_key"] >= start]
    if end:
        df = df[df["time_key"] <= end]
    if df.empty:
        print("  No candles in range.")
        return
    print(f"  Candles: {len(df):,}  ({df['time_key'].iloc[0]} → {df['time_key'].iloc[-1]})")
    trades, annotated = run_vwap_signals(df)
    print_vwap_summary(trades, annotated)


def main() -> None:
    parser = argparse.ArgumentParser(description="VWAP strategy backtest")
    parser.add_argument("csvs", nargs="*", help="CSV file(s) to backtest")
    parser.add_argument("--latest", action="store_true", help="Use most recent K_5M CSV per symbol")
    parser.add_argument("--all", action="store_true", help="All K_5M CSVs in logs/")
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD")
    args = parser.parse_args()

    logs = Path(__file__).parent.parent / "logs"

    paths: list[Path] = []
    if args.csvs:
        paths = [Path(p) for p in args.csvs]
    elif args.all:
        paths = sorted(logs.glob("US_*_K_5M_*.csv"))
    elif args.latest:
        seen: dict[str, Path] = {}
        for p in sorted(logs.glob("US_*_K_5M_*.csv")):
            sym = p.name.split("_K_5M_")[0]
            seen[sym] = p
        paths = sorted(seen.values())
    else:
        parser.print_help()
        sys.exit(1)

    if not paths:
        print("No CSV files found.")
        sys.exit(1)

    for path in paths:
        _run_file(path, args.start, args.end)


if __name__ == "__main__":
    main()
