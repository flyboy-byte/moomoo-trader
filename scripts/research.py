#!/usr/bin/env python3
"""Compare entry-condition variants over saved candle data.

Variants:
  strict   — close <= BB lower AND same-bar KDJ golden cross  (current live strategy)
  relaxed  — close <= BB lower AND K > D
  bb_only  — close <= BB lower
  kdj_only — KDJ golden cross

Usage:
    python scripts/research.py --latest
    python scripts/research.py --latest --walk-forward
    python scripts/research.py --latest --walk-forward --window 60
    python scripts/research.py logs/US_SPY_K_5M_2026-05-30.csv
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.research import research_file
from mm.config import cfg


def latest_csv() -> Path:
    csvs = sorted(cfg.logs_dir.glob("US_SPY_K_5M_*.csv"))
    if not csvs:
        print("No candle CSVs found in logs/. Run fetch_candles.py first.")
        sys.exit(1)
    return csvs[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare strategy entry variants")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("csv", nargs="?", help="Path to candle CSV")
    group.add_argument("--latest", action="store_true")
    parser.add_argument("--walk-forward", action="store_true", help="Also run walk-forward per entry variant")
    parser.add_argument("--window", type=int, default=30, help="Walk-forward window days (default: 30)")
    parser.add_argument("--exits", action="store_true", help="Also compare exit-condition variants")
    args = parser.parse_args()

    path = latest_csv() if (args.latest or args.csv is None) else Path(args.csv)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    research_file(path, walk_forward=args.walk_forward, window_days=args.window, exits=args.exits)


if __name__ == "__main__":
    main()
