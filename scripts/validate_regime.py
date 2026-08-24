#!/usr/bin/env python3
"""Validate the LLM regime gate: batch-classify historical dates and cross-reference
with bb_kdj backtest PF to test whether regime labels predict trading performance.

Usage:
    python scripts/validate_regime.py --start 2024-01-01                       # full run (uses ANTHROPIC_MODEL from .env)
    python scripts/validate_regime.py --start 2024-01-01 --model haiku         # override model (haiku/sonnet/full-id)
    python scripts/validate_regime.py --start 2024-01-01 --dry-run             # count dates, no API
    python scripts/validate_regime.py --start 2024-01-01 --from-cache          # skip classification
    python scripts/validate_regime.py --start 2024-01-01 --limit 20 --quiet    # cap calls, suppress log noise

Saves per-day results to logs/regime_validation.csv.
Writes logs/regime_YYYY-MM-DD.json for any newly classified dates (same as live).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm import config as _config
from mm.backtest import load_candles, profit_factor, run_backtest
from mm.indicators import add_all
from mm.logger import set_quiet_mode
from mm.morning_regime import classify_regime, load_regime_today

LOGS = Path(__file__).parent.parent / "logs"
RESULTS_FILE = LOGS / "regime_validation.csv"
VALID_LABELS = ("neutral", "trending_up", "trending_down", "choppy", "risk_off")
# Labels the live gate would skip — read from config so this matches the live .env
def _get_skip_labels() -> tuple[str, ...]:
    labels = getattr(_config.cfg, "regime_skip_labels", None)
    if labels:
        return tuple(labels)
    return ("choppy", "risk_off")
# Rate-limit: seconds between API calls (Haiku is fast but be polite)
API_DELAY = 0.5


# ---------------------------------------------------------------------------
# VIX backfill
# ---------------------------------------------------------------------------

def _backfill_vix(trading_days: list[str]) -> None:
    """Populate logs/vix_daily.jsonl with prior-day VIX for all trading_days."""
    vix_file = LOGS / "vix_daily.jsonl"
    existing_dates: set[str] = set()
    if vix_file.exists():
        with open(vix_file) as f:
            for line in f:
                try:
                    existing_dates.add(json.loads(line)["date"])
                except (KeyError, json.JSONDecodeError):
                    continue

    missing = [d for d in trading_days if d not in existing_dates]
    if not missing:
        return

    print(f"  Backfilling VIX for {len(missing)} dates via yfinance...")
    try:
        import yfinance as yf
    except ImportError:
        print("  WARNING: yfinance not installed. VIX will be unavailable for historical dates.")
        print("           Run: pip install yfinance")
        return

    # Fetch a window wide enough to cover all missing dates
    start_dt = (pd.Timestamp(min(missing)) - timedelta(days=10)).strftime("%Y-%m-%d")
    end_dt = (pd.Timestamp(max(missing)) + timedelta(days=2)).strftime("%Y-%m-%d")
    df = yf.download("^VIX", start=start_dt, end=end_dt, auto_adjust=False, progress=False)
    if df.empty:
        print("  WARNING: VIX download returned empty DataFrame.")
        return
    if hasattr(df.columns, "get_level_values"):
        df.columns = df.columns.get_level_values(0)
    closes = df["Close"].dropna()
    # Build date → close mapping
    vix_by_date: dict[str, float] = {str(ts.date()): float(v) for ts, v in closes.items()}

    # For each missing trading day, find the most recent VIX close before it
    new_records: list[dict] = []
    for day_str in sorted(missing):
        day = pd.Timestamp(day_str).date()
        # Prior trading day VIX: most recent close before this day
        candidates = [(d, v) for d, v in vix_by_date.items() if d < day_str]
        if not candidates:
            continue
        prev_date, prev_vix = max(candidates, key=lambda x: x[0])
        new_records.append({
            "date": day_str,
            "vix_close_date": prev_date,
            "vix_prev_close": round(prev_vix, 2),
        })

    if new_records:
        with open(vix_file, "a") as f:
            for rec in new_records:
                f.write(json.dumps(rec) + "\n")
        print(f"  Wrote {len(new_records)} VIX records to {vix_file.name}")


# ---------------------------------------------------------------------------
# Regime loading / classification
# ---------------------------------------------------------------------------

def _load_existing_regime(date_str: str) -> dict | None:
    """Load regime file if it exists, return dict or None."""
    path = LOGS / f"regime_{date_str}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _classify_date(date_str: str) -> dict | None:
    """Call classify_regime for this date, return the regime dict or None on error."""
    try:
        result = classify_regime(
            date_str=date_str,
            logs_dir=LOGS,
            prior_session_date=date_str,  # use last day BEFORE this date for prior session
        )
        return {"regime": result.regime, "confidence": result.confidence, "reason": result.reason}
    except Exception as e:
        print(f"  WARNING: classify_regime failed for {date_str}: {e}")
        return None


# ---------------------------------------------------------------------------
# bb_kdj daily PF computation
# ---------------------------------------------------------------------------

def _build_daily_trade_index(combined_csv_paths: list[Path]) -> dict[str, list]:
    """Run full bb_kdj backtest on all symbols, return {date_str: [trades]} dict."""
    all_by_date: dict[str, list] = {}
    for path in combined_csv_paths:
        sym = path.stem.split("_K_")[0].replace("_", ".", 1)
        df = load_candles(path)
        df = add_all(df)
        trades, _ = run_backtest(df)
        for t in trades:
            d = str(pd.Timestamp(t.entry_time).date())
            all_by_date.setdefault(d, []).append(t)
    return all_by_date


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Validate LLM regime gate vs bb_kdj PF")
    parser.add_argument("--start", metavar="YYYY-MM-DD", default="2024-01-01")
    parser.add_argument("--end", metavar="YYYY-MM-DD", default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="Count dates and show setup, no API calls")
    parser.add_argument("--from-cache", action="store_true",
                        help="Skip classification, load existing regime files only")
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

    # Discover trading days from candle CSVs
    combined_paths = sorted(LOGS.glob("US_*_K_5M_combined.csv"))
    if not combined_paths:
        print("No combined CSV files found in logs/. Run from project root.")
        sys.exit(1)

    # Use SPY as the canonical source of trading days
    spy_path = next((p for p in combined_paths if "SPY" in p.name), combined_paths[0])
    day_df = pd.read_csv(spy_path, usecols=["time_key"])
    day_df["date"] = pd.to_datetime(day_df["time_key"]).dt.date
    all_trading_days = sorted(str(d) for d in day_df["date"].unique())
    trading_days = [d for d in all_trading_days if d >= args.start]
    if args.end:
        trading_days = [d for d in trading_days if d <= args.end]

    print(f"Trading days in range [{args.start}, {args.end or 'latest'}]: {len(trading_days)}")

    if args.dry_run:
        need_classify = [d for d in trading_days if _load_existing_regime(d) is None]
        print(f"  Already classified:  {len(trading_days) - len(need_classify)}")
        print(f"  Would call API for:  {len(need_classify)}")
        print(f"  Estimated API cost:  ~${len(need_classify) * 0.00004:.2f}")
        return

    # Step 1 — backfill VIX history
    print("\nStep 1 — VIX backfill")
    _backfill_vix(trading_days)

    # Step 2 — classify all dates
    print("\nStep 2 — Regime classification")
    regime_map: dict[str, dict] = {}
    api_calls = 0
    skipped = 0

    for date_str in trading_days:
        existing = _load_existing_regime(date_str)
        if existing:
            regime_map[date_str] = existing
            continue

        if args.from_cache:
            regime_map[date_str] = {"regime": "neutral", "confidence": 0.0, "reason": "missing"}
            skipped += 1
            continue

        if args.limit and api_calls >= args.limit:
            regime_map[date_str] = {"regime": "neutral", "confidence": 0.0, "reason": "skipped-limit"}
            skipped += 1
            continue

        rec = _classify_date(date_str)
        if rec is None:
            regime_map[date_str] = {"regime": "neutral", "confidence": 0.0, "reason": "error"}
        else:
            regime_map[date_str] = rec
        api_calls += 1

        if api_calls % 25 == 0:
            print(f"  ... {api_calls} API calls made")
        time.sleep(API_DELAY)

    print(f"  Classified {api_calls} dates via API, {skipped} skipped, "
          f"{len(regime_map) - api_calls - skipped} loaded from file")

    # Step 3 — bb_kdj backtest, index by date
    print("\nStep 3 — bb_kdj backtest (all symbols)")
    trades_by_date = _build_daily_trade_index(combined_paths)

    # Step 4 — merge and compute per-day stats
    print("\nStep 4 — Merging regime labels with trade outcomes")
    rows: list[dict] = []
    for date_str in trading_days:
        if date_str not in regime_map:
            continue
        r = regime_map[date_str]
        day_trades = trades_by_date.get(date_str, [])
        pf = profit_factor(day_trades) if day_trades else None
        rows.append({
            "date": date_str,
            "regime": r.get("regime", "neutral"),
            "confidence": r.get("confidence", 0.0),
            "trades": len(day_trades),
            "pf": round(pf, 3) if pf is not None and pf != float("inf") else ("inf" if pf == float("inf") else ""),
            "would_block": r.get("regime", "neutral") in _get_skip_labels(),
        })

    # Save CSV
    if rows:
        with open(RESULTS_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Saved {len(rows)} rows to {RESULTS_FILE.name}")

    # Step 5 — summary table
    #
    # Bug fix 2026-08-25 (found by external audit, verified against this code):
    # this used to average each day's independently-computed PF ratio, then drop
    # infinite-PF (zero-loss) days before averaging. Averaging ratios is not the
    # same statistic as profit factor and can be wildly misleading — e.g. day A
    # gross_win=10/gross_loss=1 (PF=10) and day B gross_win=1/gross_loss=10
    # (PF=0.1) average to 5.05, while the actual pooled PF across both days is
    # (10+1)/(1+10)=1.00, i.e. breakeven. Fixed by pooling every trade belonging
    # to a label and calling profit_factor() ONCE on the pooled list — the same
    # canonical calc every other PF number in this project uses.
    print("\n" + "=" * 65)
    print(f"  Regime Gate Validation  ({args.start} → {trading_days[-1] if trading_days else '?'})")
    print(f"  {'Label':<16}  {'Days':>5}  {'Trades':>7}  {'Pooled PF':>9}  {'Avg trades/day':>15}  "
          f"{'Gate fires?':>12}  {'Would-block days':>17}")
    print("  " + "-" * 65)

    label_pooled_trades: dict[str, list] = {}
    for label in VALID_LABELS:
        subset = [r for r in rows if r["regime"] == label]
        if not subset:
            continue
        pooled = [t for r in subset for t in trades_by_date.get(r["date"], [])]
        label_pooled_trades[label] = pooled
        pf = profit_factor(pooled) if pooled else None
        n_trades = len(pooled)
        avg_trades = sum(r["trades"] for r in subset) / len(subset)
        blocked = sum(1 for r in subset if r["would_block"])
        gate_str = "YES" if label in _get_skip_labels() else "no"
        pf_str = f"{pf:.3f}" if pf is not None and pf != float("inf") else ("inf" if pf == float("inf") else "n/a")
        print(f"  {label:<16}  {len(subset):>5}  {n_trades:>7}  {pf_str:>9}  {avg_trades:>15.1f}  "
              f"{gate_str:>12}  {blocked:>17}")

    # Overall gate assessment — pool trades across all skip-labeled days vs all
    # kept-labeled days, then compute PF once on each pool (not an average of
    # per-day or per-label PFs).
    _skip = _get_skip_labels()
    skip_trades = [t for label in _skip for t in label_pooled_trades.get(label, [])]
    keep_trades = [t for label in VALID_LABELS if label not in _skip
                   for t in label_pooled_trades.get(label, [])]
    if skip_trades and keep_trades:
        skip_pf = profit_factor(skip_trades)
        keep_pf = profit_factor(keep_trades)
        delta = keep_pf - skip_pf
        print(f"\n  Skip-label pooled PF:   {skip_pf:.3f}  (N={len(skip_trades)} trades)")
        print(f"  Keep-label pooled PF:   {keep_pf:.3f}  (N={len(keep_trades)} trades)")
        print(f"  Delta:                  {delta:+.3f}")
        if delta >= 0.2:
            verdict = "GATE CONFIRMED — skip labels have meaningfully worse PF"
        elif delta >= 0.05:
            verdict = "WEAK SIGNAL — marginal difference, accumulate more data"
        else:
            verdict = "GATE UNCONFIRMED — no meaningful PF difference by label"
        print(f"\n  Verdict: {verdict}")
        print(f"  Recommendation: {'keep REGIME_GATE_ENABLED=true' if delta >= 0.1 else 'consider REGIME_GATE_ENABLED=false'}")

    # Days that would have been blocked
    total_block = sum(1 for r in rows if r["would_block"])
    total_block_trades = sum(r["trades"] for r in rows if r["would_block"])
    print(f"\n  Total days blocked if gate were live: {total_block}/{len(rows)} "
          f"({100*total_block/len(rows):.1f}%)")
    print(f"  bb_kdj trades that would have been skipped: {total_block_trades}")


if __name__ == "__main__":
    main()
