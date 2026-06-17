#!/usr/bin/env python3
"""Fetch historical 5-minute candles for US.SPY and save to logs/.

Usage:
    python scripts/fetch_candles.py
    python scripts/fetch_candles.py --symbol US.QQQ --start 2025-01-01 --end 2025-02-01
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.data import fetch_and_save
from mm.config import cfg


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch historical candles from OpenD")
    parser.add_argument("--symbol", default=cfg.symbol)
    parser.add_argument("--ktype", default=cfg.candle_ktype)
    parser.add_argument("--start", default=None, help="YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD")
    parser.add_argument("--extended-time", action="store_true",
                         help="Include pre-market/after-hours candles (US, <=60min timeframes)")
    args = parser.parse_args()

    path = fetch_and_save(
        symbol=args.symbol,
        ktype=args.ktype,
        start=args.start,
        end=args.end,
        extended_time=args.extended_time,
    )
    if path:
        print(f"Saved: {path}")
    else:
        print("No data fetched.")
        sys.exit(1)


if __name__ == "__main__":
    main()
