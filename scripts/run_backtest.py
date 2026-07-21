#!/usr/bin/env python3
"""Run the BB+KDJ strategy backtest over a saved candle CSV.

Usage:
    python scripts/run_backtest.py logs/US_SPY_K_5M_2026-05-30.csv
    python scripts/run_backtest.py --latest   # picks newest CSV in logs/
    python scripts/run_backtest.py logs/US_SPY_K_5M_combined.csv --start 2026-01-01
    python scripts/run_backtest.py logs/US_SPY_K_5M_combined.csv --start 2024-01-01 --end 2025-12-31
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.backtest import backtest_file
from mm.config import cfg


def latest_csv() -> Path:
    csvs = sorted(cfg.logs_dir.glob("US_SPY_K_5M_*.csv"))
    if not csvs:
        print("No candle CSVs found in logs/. Run fetch_candles.py first.")
        sys.exit(1)
    return csvs[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest BB+KDJ strategy over saved candles")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("csv", nargs="?", help="Path to candle CSV")
    group.add_argument("--latest", action="store_true", help="Use newest CSV in logs/")
    parser.add_argument("--start", metavar="YYYY-MM-DD", help="Only include candles on or after this date")
    parser.add_argument("--end", metavar="YYYY-MM-DD", help="Only include candles on or before this date")
    args = parser.parse_args()

    if args.latest or args.csv is None:
        path = latest_csv()
    else:
        path = Path(args.csv)

    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    backtest_file(path, start=args.start, end=args.end)


if __name__ == "__main__":
    main()
