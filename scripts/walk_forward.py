#!/usr/bin/env python3
"""Walk-forward backtest: splits candle data into sequential windows and tests each.

Usage:
    python scripts/walk_forward.py --latest
    python scripts/walk_forward.py logs/US_SPY_K_5M_2026-05-30.csv
    python scripts/walk_forward.py --latest --window 14
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.backtest import walk_forward_file
from mm.config import cfg


def latest_csv() -> Path:
    csvs = sorted(cfg.logs_dir.glob("US_SPY_K_5M_*.csv"))
    if not csvs:
        print("No candle CSVs found in logs/. Run fetch_candles.py first.")
        sys.exit(1)
    return csvs[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward backtest")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("csv", nargs="?", help="Path to candle CSV")
    group.add_argument("--latest", action="store_true", help="Use newest CSV in logs/")
    parser.add_argument("--window", type=int, default=30, help="Window size in calendar days (default: 30)")
    args = parser.parse_args()

    path = latest_csv() if (args.latest or args.csv is None) else Path(args.csv)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    walk_forward_file(path, window_days=args.window)


if __name__ == "__main__":
    main()
