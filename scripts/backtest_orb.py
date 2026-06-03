#!/usr/bin/env python3
"""Backtest the Opening Range Breakout strategy against historical candle CSVs.

Usage:
    python scripts/backtest_orb.py --latest
    python scripts/backtest_orb.py logs/US_IWM_K_5M_2026-05-31.csv
    python scripts/backtest_orb.py --all
    python scripts/backtest_orb.py --latest --minutes 15
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.backtest import load_candles
from mm.orb_strategy import run_orb_signals, print_orb_summary


def _run_file(path: Path) -> None:
    print(f"\n{'='*60}")
    print(f"File: {path.name}")
    df = load_candles(path)
    print(f"  Candles: {len(df):,}  ({df['time_key'].iloc[0]} → {df['time_key'].iloc[-1]})")
    trades, annotated = run_orb_signals(df)
    print_orb_summary(trades, annotated)


def main() -> None:
    parser = argparse.ArgumentParser(description="ORB strategy backtest")
    parser.add_argument("csvs", nargs="*")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--minutes", type=int, default=None,
                        help="Override ORB_MINUTES (opening range window)")
    args = parser.parse_args()

    if args.minutes is not None:
        os.environ["ORB_MINUTES"] = str(args.minutes)
        import mm.orb_strategy as orb
        orb.ORB_MINUTES = args.minutes

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

    for path in paths:
        _run_file(path)


if __name__ == "__main__":
    main()
