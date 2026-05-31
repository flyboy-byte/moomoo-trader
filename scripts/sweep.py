#!/usr/bin/env python3
"""Parameter sweep: find the best ATR stop multiplier and entry tolerance.

Runs three analyses in sequence:
  1. Full-period grid search (ATR mult × entry tolerance)
  2. Stop-loss exit recovery analysis — how many stopped trades recovered anyway
  3. Walk-forward ATR sweep — scores consistency across time windows

Usage:
    python scripts/sweep.py --latest
    python scripts/sweep.py --latest --entry relaxed
    python scripts/sweep.py logs/US_SPY_K_5M_2026-05-30.csv
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.research import sweep_parameters, analyze_stop_exits, sweep_walk_forward
from mm.config import cfg
import pandas as pd


def latest_csv() -> Path:
    csvs = sorted(cfg.logs_dir.glob("US_SPY_K_5M_*.csv"))
    if not csvs:
        print("No candle CSVs found in logs/. Run fetch_candles.py first.")
        sys.exit(1)
    return csvs[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Parameter sweep for stop and entry tuning")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("csv", nargs="?", help="Path to candle CSV")
    group.add_argument("--latest", action="store_true")
    parser.add_argument("--entry", default="strict",
                        choices=["strict", "relaxed", "bb_only", "kdj_only"])
    parser.add_argument("--window", type=int, default=90,
                        help="Walk-forward window in days (default: 90)")
    args = parser.parse_args()

    path = latest_csv() if (args.latest or args.csv is None) else Path(args.csv)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    df = pd.read_csv(path)
    df["time_key"] = pd.to_datetime(df["time_key"])
    df = df.sort_values("time_key").reset_index(drop=True)

    # 1. Full-period grid search
    sweep_parameters(df, entry_key=args.entry)

    print()

    # 2. Stop recovery: how many stops would have recovered?
    analyze_stop_exits(df, lookahead_bars=48)

    print()

    # 3. Walk-forward ATR sweep for consistency
    sweep_walk_forward(df, entry_key=args.entry, window_days=args.window)


if __name__ == "__main__":
    main()
