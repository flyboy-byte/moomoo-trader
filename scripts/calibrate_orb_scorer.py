#!/usr/bin/env python3
"""Calibrate the ORB Claude scorer: score historical trades offline and compare
to actual outcomes to find the optimal confidence threshold.

Usage:
    python scripts/calibrate_orb_scorer.py                              # all combined CSVs (uses ANTHROPIC_MODEL from .env)
    python scripts/calibrate_orb_scorer.py --model haiku --quiet        # fast Haiku run, suppress per-trade noise
    python scripts/calibrate_orb_scorer.py --start 2024-01-01
    python scripts/calibrate_orb_scorer.py --dry-run                    # count calls, no API
    python scripts/calibrate_orb_scorer.py --from-cache                 # skip scoring, reload saved results
    python scripts/calibrate_orb_scorer.py --limit 50                   # cap API calls (testing)

Writes scored results to logs/orb_calibration.jsonl (append). On re-run,
already-scored (symbol, entry_time) pairs are skipped.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm import config as _config
from mm.backtest import load_candles, profit_factor
from mm.indicators import add_all
from mm.logger import set_quiet_mode
from mm.morning_regime import score_orb_setup, load_regime_today
from mm.orb_strategy import run_orb_signals, ORB_TARGET_MULT


LOGS = Path(__file__).parent.parent / "logs"
CACHE_FILE = LOGS / "orb_calibration.jsonl"


def _load_vix_map(logs_dir: Path) -> dict[str, float]:
    vix_file = logs_dir / "vix_daily.jsonl"
    if not vix_file.exists():
        return {}
    result: dict[str, float] = {}
    with open(vix_file) as f:
        for line in f:
            try:
                rec = json.loads(line)
                result[rec["date"]] = float(rec["vix_prev_close"])
            except (KeyError, ValueError, json.JSONDecodeError):
                continue
    return result


def _build_setup(trade, entry_row: pd.Series, vix_map: dict) -> dict:
    """Reconstruct the setup dict the live scorer would have used at entry."""
    entry_ts = pd.Timestamp(trade.entry_time)
    date_str = entry_ts.strftime("%Y-%m-%d")
    or_range = trade.or_high - trade.or_low
    close = trade.entry_price
    vol = float(entry_row.get("volume", 0))
    vol_ma = float(entry_row.get("volume_ma", 1) or 1)
    open_time = entry_ts.replace(hour=9, minute=30, second=0, microsecond=0)
    return {
        "date": date_str,
        "direction": trade.direction.upper(),
        "or_range_pct": round(or_range / close * 100, 3) if close else 0,
        "vol_ratio": round(vol / vol_ma, 2),
        "vix": vix_map.get(date_str),
        "regime": load_regime_today(date_str),
        "regime_confidence": 0.5,
        "mins_since_open": int((entry_ts - open_time).total_seconds() / 60),
    }


def _load_existing_cache() -> dict[str, dict]:
    """Return {symbol:entry_time_str: record} from existing cache file."""
    if not CACHE_FILE.exists():
        return {}
    records: dict[str, dict] = {}
    with open(CACHE_FILE) as f:
        for line in f:
            try:
                rec = json.loads(line)
                key = f"{rec['symbol']}:{rec['entry_time']}"
                records[key] = rec
            except (KeyError, json.JSONDecodeError):
                continue
    return records


def _print_bucket_analysis(records: list[dict]) -> None:
    if not records:
        print("\n  No scored records to analyze.")
        return

    buckets = [
        ("0.0-0.3",   0.0, 0.30),
        ("0.3-0.5",   0.3, 0.50),
        ("0.5-0.65",  0.5, 0.65),
        ("0.65-0.8",  0.65, 0.80),
        ("0.8-1.0",   0.8, 1.01),
    ]

    print(f"\n  ORB Scorer Calibration  (N={len(records)} trades)")
    print(f"  {'Bucket':<12}  {'N':>5}  {'Win%':>6}  {'PF':>7}  {'Avg PnL':>8}  "
          f"{'TIME_STOP%':>11}  {'Deployable?'}")
    print("  " + "-" * 72)

    for label, lo, hi in buckets:
        subset = [r for r in records if lo <= r["confidence"] < hi]
        if not subset:
            print(f"  {label:<12}  {'0':>5}")
            continue
        wins = sum(1 for r in subset if r["pnl"] > 0)
        ts_count = sum(1 for r in subset if r["exit_reason"] == "TIME_STOP")
        total_pnl = sum(r["pnl"] for r in subset)
        n = len(subset)
        pf = profit_factor([r["pnl"] for r in subset])
        avg_pnl = total_pnl / n
        deployable = "YES" if pf >= 1.2 and n >= 50 else ("maybe" if pf >= 1.1 and n >= 20 else "no")
        print(f"  {label:<12}  {n:>5}  {100*wins/n:>5.1f}%  {pf:>7.3f}  "
              f"{avg_pnl:>+8.3f}  {100*ts_count/n:>10.1f}%  {deployable}")

    # recommend optimal gate
    print()
    best_pf, best_thresh = 0.0, None
    for label, lo, hi in buckets:
        subset = [r for r in records if r["confidence"] >= lo]
        if len(subset) < 50:
            continue
        pf = profit_factor([r["pnl"] for r in subset])
        if pf > best_pf:
            best_pf = pf
            best_thresh = lo

    if best_thresh is not None:
        above = [r for r in records if r["confidence"] >= best_thresh]
        below = [r for r in records if r["confidence"] < best_thresh]
        print(f"  Recommended threshold: {best_thresh:.2f}  "
              f"(above: N={len(above)}, PF={profit_factor([r['pnl'] for r in above]):.3f}  "
              f"below: N={len(below)}, PF={profit_factor([r['pnl'] for r in below]):.3f})")
    else:
        print("  No threshold achieves PF ≥ 1.2 with ≥ 50 trades above gate.")
        print("  → Scorer is not discriminating — consider disabling it.")

    # confidence distribution
    confs = [r["confidence"] for r in records]
    print(f"\n  Confidence distribution: "
          f"min={min(confs):.2f}  median={sorted(confs)[len(confs)//2]:.2f}  "
          f"max={max(confs):.2f}  "
          f"above_0.65={sum(1 for c in confs if c >= 0.65)}/{len(confs)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate ORB Claude scorer offline")
    parser.add_argument("csvs", nargs="*")
    parser.add_argument("--start", metavar="YYYY-MM-DD",
                        help="Only include trades on or after this date")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count trades, show setup dicts, no API calls")
    parser.add_argument("--from-cache", action="store_true",
                        help="Skip scoring, load existing cache and print analysis")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap new API calls at N (0 = unlimited)")
    parser.add_argument("--model", metavar="MODEL", default=None,
                        help="Override ANTHROPIC_MODEL for this run (e.g. haiku, sonnet, or full ID)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress per-trade log noise (file logs unaffected)")
    args = parser.parse_args()

    if args.quiet:
        set_quiet_mode()

    if args.model:
        aliases = {
            "haiku": "claude-haiku-4-5-20251001",
            "sonnet": "claude-sonnet-5",
        }
        _config.cfg.anthropic_model = aliases.get(args.model, args.model)
        print(f"Model override: {_config.cfg.anthropic_model}")

    if args.from_cache:
        records = list(_load_existing_cache().values())
        if args.start:
            records = [r for r in records if r["entry_time"] >= args.start]
        print(f"Loaded {len(records)} cached records from {CACHE_FILE}")
        _print_bucket_analysis(records)
        return

    paths: list[Path] = []
    if args.csvs:
        paths = [Path(p) for p in args.csvs]
    else:
        combined = sorted(LOGS.glob("US_*_K_5M_combined.csv"))
        paths = combined if combined else sorted(LOGS.glob("US_*_K_5M_*.csv"))

    if not paths:
        print("No CSV files found. Pass paths explicitly or run from project root.")
        sys.exit(1)

    vix_map = _load_vix_map(LOGS)
    existing = _load_existing_cache()
    new_records: list[dict] = []
    call_count = 0

    for path in paths:
        sym = path.stem.split("_K_")[0].replace("_", ".", 1)
        print(f"\nProcessing {path.name} ({sym})")
        df = load_candles(path)
        if args.start:
            df = df[df["time_key"] >= args.start].reset_index(drop=True)
        df = add_all(df)
        trades, annotated = run_orb_signals(df.copy())
        print(f"  {len(trades)} trades")

        # build a time_key → row lookup
        annotated["_ts_str"] = annotated["time_key"].astype(str)
        ts_index = annotated.set_index("_ts_str")

        for trade in trades:
            entry_str = str(trade.entry_time)
            cache_key = f"{sym}:{entry_str}"
            if cache_key in existing:
                continue  # already scored

            # look up the entry bar
            try:
                entry_row = ts_index.loc[entry_str]
            except KeyError:
                entry_row = pd.Series({"volume": 0, "volume_ma": 1})

            setup = _build_setup(trade, entry_row, vix_map)

            if args.dry_run:
                print(f"  WOULD SCORE {sym} {entry_str}: {setup}")
                continue

            if args.limit and call_count >= args.limit:
                print(f"  --limit {args.limit} reached, stopping API calls")
                break

            scored = score_orb_setup(sym, entry_str, setup, logs_dir=LOGS)
            call_count += 1

            record = {
                "symbol": sym,
                "entry_time": entry_str,
                "exit_time": str(trade.exit_time),
                "exit_reason": trade.exit_reason,
                "direction": trade.direction,
                "confidence": scored["confidence"],
                "reason": scored["reason"],
                "pnl": trade.pnl,
                "or_range_pct": setup["or_range_pct"],
                "vol_ratio": setup["vol_ratio"],
                "vix": setup["vix"],
                "regime": setup["regime"],
                "mins_since_open": setup["mins_since_open"],
                "scored_at": datetime.utcnow().isoformat(),
            }
            new_records.append(record)
            existing[cache_key] = record

            if call_count % 50 == 0:
                print(f"  ... {call_count} API calls made")

        if args.limit and call_count >= args.limit:
            break

    if args.dry_run:
        print(f"\nDry run complete. Would have scored {len(trades)} trades per symbol.")
        return

    # append new records to cache file
    if new_records:
        with open(CACHE_FILE, "a") as f:
            for rec in new_records:
                f.write(json.dumps(rec) + "\n")
        print(f"\nWrote {len(new_records)} new records to {CACHE_FILE}")
    else:
        print("\nNo new records (all already cached).")

    all_records = list(existing.values())
    if args.start:
        all_records = [r for r in all_records if r["entry_time"] >= args.start]
    _print_bucket_analysis(all_records)


if __name__ == "__main__":
    main()
