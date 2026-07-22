"""
Classify today's (or a given date's) market regime using the Claude API.

Reads pre-market context from local files (vix_daily.jsonl, candle CSVs),
calls claude-haiku, writes logs/regime_YYYY-MM-DD.json, and prints the result.

Run at 9:20 ET before market open (VPS cron). Also useful for manual testing.

Usage:
    python scripts/classify_regime.py
    python scripts/classify_regime.py --date 2026-07-21
    python scripts/classify_regime.py --date 2026-07-21 --dry-run
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.morning_regime import classify_regime, load_regime_today
from mm import config as _config


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify market regime via Claude API")
    parser.add_argument("--date", help="Date to classify (YYYY-MM-DD). Defaults to today.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent to the API without making the call.",
    )
    args = parser.parse_args()

    cfg = _config.cfg

    if not cfg.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        from mm.morning_regime import (
            _load_vix, _load_prior_session, _macro_calendar,
            _vix_note, _USER_TEMPLATE, _SYSTEM, PROMPT_VERSION
        )
        from datetime import date as date_cls
        date_str = args.date or date_cls.today().isoformat()
        logs_dir = cfg.logs_dir
        vix = _load_vix(logs_dir, date_str)
        spy_chg, spy_range = _load_prior_session(logs_dir, "US_SPY")
        qqq_chg, qqq_range = _load_prior_session(logs_dir, "US_QQQ")
        calendar = _macro_calendar(date_str)
        prompt = _USER_TEMPLATE.format(
            date=date_str,
            vix=f"{vix:.1f}" if vix is not None else "unavailable",
            vix_note=_vix_note(vix),
            spy_chg=spy_chg,
            spy_range=spy_range,
            qqq_chg=qqq_chg,
            qqq_range=qqq_range,
            calendar=calendar,
        )
        print("=== SYSTEM ===")
        print(_SYSTEM)
        print("\n=== USER PROMPT ===")
        print(prompt)
        print(f"\n[dry-run] Model: {cfg.anthropic_model}  Prompt version: {PROMPT_VERSION}")
        print("[dry-run] No API call made.")
        return

    try:
        result = classify_regime(date_str=args.date)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(
        {
            "date": result.date,
            "regime": result.regime,
            "confidence": result.confidence,
            "reason": result.reason,
            "model": result.model,
            "prompt_version": result.prompt_version,
        },
        indent=2,
    ))

    # Confirm the written file reads back correctly
    label = load_regime_today(result.date)
    assert label == result.regime, f"Read-back mismatch: {label!r} != {result.regime!r}"
    print(f"\n✓ Written to logs/regime_{result.date}.json")


if __name__ == "__main__":
    main()
