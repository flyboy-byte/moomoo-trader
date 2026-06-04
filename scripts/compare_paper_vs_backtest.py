#!/usr/bin/env python3
"""
Compare paper-run JSONL log against backtester output on the same candle data.

Goal: prove the live paper runner and the backtester generate the same signals
on the same closed candles. Discrepancies mean the paper runner is evaluating
different data or using different logic than the backtester.

Usage:
    python scripts/compare_paper_vs_backtest.py logs/paper_US_SPY_2026-06-01.jsonl
    python scripts/compare_paper_vs_backtest.py logs/paper_US_SPY_2026-06-01.jsonl --candle-csv logs/US_SPY_K_5M_2026-05-30.csv
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from mm.backtest import load_candles, run_backtest
from mm.strategy import Signal
from mm.logger import get_logger

log = get_logger("compare")

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"


# ---------------------------------------------------------------------------
# JSONL parsing
# ---------------------------------------------------------------------------

def load_paper_events(path: Path) -> list[dict]:
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def extract_paper_entries(events: list[dict]) -> list[dict]:
    """Extract bb_kdj position_open events from paper log."""
    return [e for e in events if e["event"] == "position_open" and e.get("strategy", "bb_kdj") == "bb_kdj"]


def extract_paper_exits(events: list[dict]) -> list[dict]:
    """Extract bb_kdj position_close events from paper log."""
    return [e for e in events if e["event"] == "position_close" and e.get("strategy", "bb_kdj") == "bb_kdj"]


def extract_paper_skips(events: list[dict]) -> list[dict]:
    return [e for e in events if e["event"] == "signal_skip" and e.get("strategy", "bb_kdj") == "bb_kdj"]


def extract_paper_risk_blocks(events: list[dict]) -> list[dict]:
    return [e for e in events if e["event"] == "risk_block" and e.get("strategy", "bb_kdj") == "bb_kdj"]


def extract_date_range(events: list[dict], session_date: str = "") -> tuple[str, str]:
    """Return date range for comparison.

    Uses the session date from the filename as the start to avoid including
    stale candles from the prior session close. Falls back to candle_ts range
    if no session date is available.
    """
    bar_evals = [e for e in events if e["event"] == "bar_eval" and e.get("strategy") == "bb_kdj"]
    if not bar_evals:
        return session_date, session_date
    timestamps = [e["candle_ts"] for e in bar_evals]
    end_date = max(timestamps)[:10]
    # Prefer filename-derived session date so stale prior-day candles
    # don't widen the window and cause false backtest signal matches.
    start_date = session_date if session_date else min(timestamps)[:10]
    return start_date, end_date


def detect_symbol(path: Path) -> str:
    """Infer symbol from filename: paper_US_SPY_2026-06-01.jsonl → US.SPY"""
    parts = path.stem.split("_")
    if len(parts) >= 3:
        return f"{parts[1]}.{parts[2]}"
    return ""


def detect_session_date(path: Path) -> str:
    """Infer session date from filename: paper_US_SPY_2026-06-01.jsonl → '2026-06-01'"""
    # Filename ends with _YYYY-MM-DD
    stem = path.stem
    if len(stem) >= 10:
        candidate = stem[-10:]
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
            return candidate
        except ValueError:
            pass
    return ""


# ---------------------------------------------------------------------------
# Candle CSV discovery
# ---------------------------------------------------------------------------

def find_candle_csv(symbol: str, ktype: str = "K_5M") -> Path | None:
    from mm.config import cfg
    sym_safe = symbol.replace(".", "_")
    pattern = f"{sym_safe}_{ktype}_*.csv"
    matches = sorted(cfg.logs_dir.glob(pattern))
    return matches[-1] if matches else None


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------

def compare(paper_path: Path, candle_csv: Path | None = None,
            ktype: str = "K_5M") -> bool:
    print(f"\nLoading paper log: {paper_path}")
    events = load_paper_events(paper_path)
    if not events:
        print("No events found in paper log.")
        return False

    symbol = detect_symbol(paper_path)
    session_date = detect_session_date(paper_path)
    start_date, end_date = extract_date_range(events, session_date)
    print(f"Symbol: {symbol}  Candle range in log: {start_date} → {end_date}")

    if not candle_csv:
        candle_csv = find_candle_csv(symbol, ktype)
    if not candle_csv or not candle_csv.exists():
        print(f"No candle CSV found for {symbol} {ktype}. Pass --candle-csv explicitly.")
        return False

    print(f"Candle CSV: {candle_csv}")

    # Load the full candle CSV so backtester has complete indicator warm-up history.
    # (Filtering before running the backtester would produce different indicator values
    # at the window boundary — the simulation uses full history so we match that here.)
    df = load_candles(candle_csv)
    if df.empty:
        print("Candle CSV is empty.")
        return False

    print(f"Total candles in CSV: {len(df)}")

    # Run backtester on full history, then filter entries/exits to the date range
    trades, annotated = run_backtest(df)
    exit_signals = [Signal.EXIT_TARGET, Signal.EXIT_STOP_LOSS, Signal.EXIT_DEATH_CROSS]
    if start_date and end_date:
        date_mask = (annotated["time_key"].astype(str) >= start_date) & \
                    (annotated["time_key"].astype(str) <= end_date + " 23:59:59")
        bt_entries = annotated[date_mask & (annotated["signal"] == Signal.ENTRY)]
        bt_exits = annotated[date_mask & annotated["signal"].isin(exit_signals)]
        trades = [t for t in trades
                  if start_date <= str(t.entry_time)[:10] <= end_date]
    else:
        bt_entries = annotated[annotated["signal"] == Signal.ENTRY]
        bt_exits = annotated[annotated["signal"].isin(exit_signals)]

    print(f"Candle range evaluated: {start_date} → {end_date}")

    paper_entries = extract_paper_entries(events)
    paper_exits = extract_paper_exits(events)
    paper_skips = extract_paper_skips(events)
    paper_risk_blocks = extract_paper_risk_blocks(events)

    # Risk blocks only fire after a valid signal — they count as "signal found, not traded"
    paper_signals_found = len(paper_entries) + len(paper_risk_blocks)

    print(f"\n{'='*60}")
    print(f"COMPARISON SUMMARY")
    print(f"{'='*60}")

    # --- Signal agreement (primary validation goal) ---
    bt_n = len(bt_entries)
    signal_match = paper_signals_found == bt_n
    icon = PASS if signal_match else FAIL
    print(f"\n{icon} Signal agreement: backtest={bt_n}  paper_found={paper_signals_found}", end="")
    if not signal_match:
        print(f"  ← ENGINE MISMATCH (diff={paper_signals_found - bt_n:+d})")
    else:
        print("  (signal engine agrees)")

    # --- Executed trades (affected by risk management) ---
    paper_n = len(paper_entries)
    bt_ex = len(bt_exits)
    paper_ex = len(paper_exits)
    if paper_risk_blocks:
        print(f"  ↳ paper executed {paper_n}/{paper_signals_found} signals "
              f"({len(paper_risk_blocks)} blocked by risk management)")
    exit_match = bt_ex == paper_ex

    # --- Entry timestamp alignment ---
    if paper_entries:
        print(f"\nEntry timestamps (paper log):")
        for e in paper_entries:
            print(f"  {e['ts'][:19]}  entry={e['entry']:.4f}  stop={e['stop']:.4f}  qty={e['qty']}")

    if not bt_entries.empty:
        print(f"\nEntry timestamps (backtest):")
        for _, row in bt_entries.iterrows():
            print(f"  {str(row['time_key']):<19}  price={row['close']:.4f}")

    # --- Exit reason comparison ---
    if paper_exits:
        print(f"\nExit events (paper log):")
        for e in paper_exits:
            print(f"  {e['ts'][:19]}  exit={e['exit']:.4f}  reason={e['reason']}  pnl={e['pnl']:+.4f}")

    if trades:
        print(f"\nTrades (backtest):")
        for t in trades:
            print(f"  {str(t.entry_time):<19} → {str(t.exit_time):<19}  "
                  f"entry={t.entry_price:.4f}  exit={t.exit_price:.4f}  "
                  f"reason={t.exit_reason}  pnl={t.pnl:+.4f}")

    # --- Risk blocks & skips ---
    if paper_risk_blocks:
        print(f"\nRisk blocks in paper log ({len(paper_risk_blocks)}):")
        for b in paper_risk_blocks:
            print(f"  {b['ts'][:19]}  reason={b['reason']}")
        if any(b["reason"] == "price_exceeds_max_position" for b in paper_risk_blocks):
            print("  NOTE: price_exceeds_max_position means MAX_POSITION_DOLLARS is too low "
                  "for one share. Raise the cap to allow trading.")

    if paper_skips:
        print(f"\nSignal skips in paper log ({len(paper_skips)}):")
        for s in paper_skips:
            print(f"  {s['ts'][:19]}  bonus={s.get('bonus_score', '?')}  min={s.get('min_score', '?')}")

    # --- Verdict ---
    print(f"\n{'='*60}")
    if signal_match and bt_n == 0:
        print(f"{PASS} No signals in this window — both systems agree (no trades).")
    elif signal_match:
        print(f"{PASS} Signal engines agree: {bt_n} signal(s) found by both systems.")
        if paper_risk_blocks:
            print(f"     {len(paper_risk_blocks)} signal(s) blocked by risk management (not a signal bug).")
    else:
        print(f"{FAIL} Signal engine mismatch. Investigate indicator pipeline or date range.")
        print("     Common causes: partial candle evaluated, indicator warm-up difference,")
        print("     MIN_SIGNAL_SCORE mismatch, or different date range.")
    print()

    return signal_match


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare paper-run JSONL against backtester on the same candles"
    )
    parser.add_argument("jsonl", help="Paper run JSONL log (logs/paper_US_SPY_*.jsonl)")
    parser.add_argument("--candle-csv", default=None, help="Override candle CSV path")
    parser.add_argument("--ktype", default="K_5M", help="Candle ktype for auto-discovery")
    args = parser.parse_args()

    paper_path = Path(args.jsonl)
    if not paper_path.exists():
        print(f"File not found: {paper_path}")
        sys.exit(1)

    candle_csv = Path(args.candle_csv) if args.candle_csv else None
    ok = compare(paper_path, candle_csv, ktype=args.ktype)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
