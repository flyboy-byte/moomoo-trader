#!/usr/bin/env python3
"""
Weekly trading synthesis — reads last week's JSONL events, calls Claude for
structured analysis, posts summary to Discord.

Intended cron (VPS, UTC): every Monday at 13:00 UTC (9:00 ET).
  0 13 * * 1  cd ~/moomoo && .venv/bin/python scripts/weekly_synthesis.py >> logs/cron_synthesis.log 2>&1

Usage:
    python scripts/weekly_synthesis.py
    python scripts/weekly_synthesis.py --week 2026-W30
    python scripts/weekly_synthesis.py --dry-run    # print stats, no API call, no Discord
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.morning_regime import synthesize_week
from mm.notifications import notify


def main() -> None:
    ap = argparse.ArgumentParser(description="Weekly trading synthesis")
    ap.add_argument("--week", metavar="YYYY-WNN",
                    help="ISO week string (default: last week)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print stats without calling Claude API or posting to Discord")
    args = ap.parse_args()

    import json
    import mm.config as _config

    if args.dry_run:
        _config.cfg.anthropic_api_key = ""  # suppress API call

    result = synthesize_week(week_str=args.week)

    print(f"\n=== Weekly Synthesis {result['week']} ===")
    print(f"Stats:\n{json.dumps(result['stats'], indent=2)}")

    if result.get("analysis"):
        print(f"\nAnalysis:\n{json.dumps(result['analysis'], indent=2)}")
        tokens = result.get("input_tokens", 0) + result.get("output_tokens", 0)
        if tokens:
            print(f"\nTokens used: {tokens}")

    if args.dry_run:
        print("\n[dry-run] Skipped Discord post.")
        return

    analysis = result.get("analysis") or {}
    summary = analysis.get("summary", "No summary available.")
    rec = analysis.get("recommendation", "")
    msg = f"**Weekly Synthesis {result['week']}**\n{summary}"
    if rec and rec != "more data needed":
        msg += f"\n> {rec}"
    notify(msg)


if __name__ == "__main__":
    main()
