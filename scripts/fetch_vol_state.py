#!/usr/bin/env python3
"""
Volatility term-structure snapshot — writes logs/vol_state.jsonl (append-only).

Phase 1 of the volatility-engine plan (see docs/expansions/route-2-llm-signals.md
and CLAUDE.md history 2026-08-25). Fetches VIX/VIX1D/VIX9D/VIX3M/VIX6M/VVIX/VXN/
COR1M/COR3M via yfinance and runs the deterministic classification in
mm.vol_engine.compute_vol_state(). This script does NOT gate any trade and
nothing in mm/ reads its output yet — pure shadow-logging/data-accumulation,
same status fetch_vix_morning.py had before the ORB/gap_fade/regime gates were
built on top of it.

Run this intraday (every few minutes during market hours), not once/day like
fetch_vix_morning.py — VIX1D/VIX9D/VIX3M term structure is exactly the kind of
signal that can shift within a session, and the whole point of this snapshot
series is to accumulate enough forward data to eventually calibrate bucket
thresholds for the term-structure ratios (see mm/vol_engine.py's docstring —
yfinance has no historical backfill for those six tickers, only live values).

Usage:
    python scripts/fetch_vol_state.py
    python scripts/fetch_vol_state.py --dry-run   # print, don't write to logs/

Intended cron (VPS runs UTC, market 9:30-16:00 ET = 13:30-20:00 UTC):
  */15 13-20 * * 1-5  cd ~/moomoo && .venv/bin/python scripts/fetch_vol_state.py >> logs/cron_vol_state.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm import clock  # noqa: E402
from mm.config import cfg  # noqa: E402
from mm.vol_engine import compute_vol_state, fetch_vol_levels  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print, don't write to logs/")
    args = ap.parse_args()

    levels = fetch_vol_levels()
    if all(v is None for v in levels.values()):
        print("ERROR: all volatility ticker fetches failed.")
        sys.exit(1)

    state = compute_vol_state(levels)
    record = {
        "ts": clock.now_et().isoformat(timespec="seconds"),
        "date": str(clock.today()),
        **state,
    }

    print(json.dumps(record))
    if args.dry_run:
        return

    cfg.logs_dir.mkdir(exist_ok=True)
    path = cfg.logs_dir / "vol_state.jsonl"
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"Appended to {path}")


if __name__ == "__main__":
    main()
