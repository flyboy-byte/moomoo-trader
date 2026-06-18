#!/usr/bin/env python3
"""
Daily VIX shadow-logger — observational only, never touches live entry logic.

Logs yesterday's settled VIX close (the value actually knowable before market
open — same-day close, used by the original backtest in
scripts/backtest_vix_filter.py, has lookahead bias) plus what 2-3 already
graveyard-tested VIX block thresholds would have decided for today, purely
for forward observation. Nothing reads this file; nothing in mm/ changes
behavior based on it. See docs/strategy_graveyard.md — VIX daily regime
filter already tested and failed OOS on 2022-2025 backtest data. This script
exists to see whether forward live data agrees or disagrees, without
re-opening the knob freeze.

Source: yfinance ^VIX (free, no API key, already a project dependency).

Usage:
    python scripts/fetch_vix_morning.py
    python scripts/fetch_vix_morning.py --dry-run   # print, don't write to logs/

Intended cron (VPS runs UTC): run once daily before market open, e.g.
  10 13 * * 2-6  cd ~/moomoo && .venv/bin/python scripts/fetch_vix_morning.py >> logs/cron_vix.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm import clock  # noqa: E402
from mm.config import cfg  # noqa: E402

# Same thresholds as scripts/backtest_vix_filter.py — not new, not re-tuned.
_BLOCK_THRESHOLDS = (20, 25, 30)


def fetch_yesterdays_vix_close() -> tuple[date, float] | None:
    try:
        import yfinance as yf
    except ImportError:
        print("ERROR: yfinance not installed. Run: pip install yfinance")
        return None

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    df = yf.download("^VIX", start=start, end=end, auto_adjust=False, progress=False)
    if df.empty:
        print("ERROR: VIX download returned empty DataFrame.")
        return None
    if hasattr(df.columns, "get_level_values"):
        df.columns = df.columns.get_level_values(0)
    closes = df["Close"].dropna()
    if closes.empty:
        return None
    last_ts = closes.index[-1]
    return last_ts.date(), float(closes.iloc[-1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print, don't write to logs/")
    args = ap.parse_args()

    result = fetch_yesterdays_vix_close()
    if result is None:
        sys.exit(1)
    vix_date, vix_close = result

    record = {
        "date": str(clock.today()),
        "vix_close_date": str(vix_date),
        "vix_prev_close": round(vix_close, 2),
    }
    for t in _BLOCK_THRESHOLDS:
        record[f"would_block_{t}"] = vix_close >= t

    print(json.dumps(record))
    if args.dry_run:
        return

    cfg.logs_dir.mkdir(exist_ok=True)
    path = cfg.logs_dir / "vix_daily.jsonl"
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"Appended to {path}")


if __name__ == "__main__":
    main()
