#!/usr/bin/env python3
"""
Daily VPS cron job: maintain a rolling RTH + extended-hours candle archive.

Moomoo's own extended-hours retention may be <2 years (per their docs) and
the VPS has no candle history of its own at all (logs/ is gitignored, never
deployed via `git pull`). This script fetches a small trailing window every
day and merges it into two running archives per symbol via
mm.data.update_combined_csv — so the VPS builds its own history going
forward, for free, regardless of what Moomoo's retention window does later.

Idempotent: safe to re-run, safe to miss a day — the merge just catches up
on whatever the lookback window still covers.

Intended cron (VPS runs UTC; 8pm ET close = ~00:00 UTC during EDT):
  15 0 * * 2-6  cd ~/moomoo && .venv/bin/python scripts/fetch_daily_archive.py

Usage:
    python scripts/fetch_daily_archive.py
    python scripts/fetch_daily_archive.py --symbols US.SPY,US.QQQ,US.IWM --lookback-days 10
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.config import cfg          # noqa: E402
from mm.data import fetch_candles, update_combined_csv  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily rolling RTH + extended-hours archive fetch")
    parser.add_argument("--symbols", default=",".join(cfg.symbols))
    parser.add_argument("--lookback-days", type=int, default=10)
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    start = (datetime.now() - timedelta(days=args.lookback_days)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")

    for symbol in symbols:
        for extended_time in (False, True):
            df = fetch_candles(symbol=symbol, ktype="K_5M", start=start, end=end,
                                extended_time=extended_time)
            if df.empty:
                kind = "extended-hours" if extended_time else "RTH"
                print(f"{symbol}: no {kind} data returned for {start}..{end}")
                continue
            path = update_combined_csv(df, symbol, "K_5M", extended_time=extended_time)
            out = path.read_text().count("\n") - 1  # rough row count, header excluded
            kind = "EXT" if extended_time else "RTH"
            print(f"{symbol} [{kind}]: fetched {len(df)} rows, archive now ~{out} rows -> {path}")


if __name__ == "__main__":
    main()
