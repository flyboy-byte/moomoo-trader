"""Diagnose paper runner JSONL logs.

Usage:
    python scripts/diagnose_logs.py [--date YYYY-MM-DD] [--all] [--symbol US.SPY]

Sections:
    1. Uptime  — gaps > 10 min between bar_eval events (runner may have been down)
    2. Signals — bb_touch%, kdj_cross%, bonus distribution per symbol/strategy
    3. Stale   — candles older than 600 s at eval time
    4. Trades  — position_open/close pairs with entry, exit, pnl, hold_bars
    5. Skips   — most common blocking conditions per symbol/strategy
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path


def _load_jsonl(paths: list[Path]) -> list[dict]:
    records = []
    for p in paths:
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return sorted(records, key=lambda r: r.get("ts", ""))


def _find_logs(logs_dir: Path, date_str: str | None, symbol: str | None, all_dates: bool) -> list[Path]:
    pattern = re.compile(r"paper_(.+)_(\d{4}-\d{2}-\d{2})\.jsonl$")
    results = []
    for p in sorted(logs_dir.glob("paper_*_????-??-??.jsonl")):
        m = pattern.match(p.name)
        if not m:
            continue
        sym, date = m.group(1), m.group(2)
        sym_dotted = sym.replace("_", ".", 1)  # US_SPY → US.SPY
        if symbol and sym_dotted != symbol:
            continue
        if date_str and date != date_str:
            continue
        if not all_dates and not date_str:
            # default: today
            today = datetime.now().strftime("%Y-%m-%d")
            if date != today:
                continue
        results.append(p)
    return results


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _uptime(records: list[dict]) -> None:
    section("1. UPTIME GAPS  (bar_eval gaps > 10 min)")
    by_sym_strat: dict[tuple, list[datetime]] = defaultdict(list)
    for r in records:
        if r.get("event") != "bar_eval":
            continue
        sym = r.get("symbol", r.get("signals", {}).get("symbol", "?"))
        strat = r.get("strategy", "?")
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (KeyError, ValueError):
            continue
        # symbol not in bar_eval top-level — use filename context
        by_sym_strat[(strat,)].append(ts)

    # re-group by strategy using top-level strategy field only
    strat_ts: dict[str, list[datetime]] = defaultdict(list)
    for r in records:
        if r.get("event") != "bar_eval":
            continue
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (KeyError, ValueError):
            continue
        strat_ts[r.get("strategy", "?")].append(ts)

    found_gap = False
    for strat, times in sorted(strat_ts.items()):
        times.sort()
        for i in range(1, len(times)):
            gap = (times[i] - times[i - 1]).total_seconds()
            if gap > 600:
                print(f"  [{strat}] gap {gap/60:.1f} min  {times[i-1].strftime('%H:%M:%S')} → {times[i].strftime('%H:%M:%S')}")
                found_gap = True
    if not found_gap:
        print("  No gaps > 10 min detected.")


def _signals(records: list[dict]) -> None:
    section("2. SIGNAL HIT RATES  (bar_eval events)")

    # bb_kdj only — other strategies don't have the same signal fields
    bb_totals: Counter = Counter()
    bb_hits: Counter = Counter()
    bb_bonus: Counter = Counter()

    for r in records:
        if r.get("event") != "bar_eval" or r.get("strategy") != "bb_kdj":
            continue
        sigs = r.get("signals", {})
        bb_totals["bars"] += 1
        for field in ("bb_touch", "kdj_cross", "rsi_oversold", "ranging", "volume_spike"):
            if sigs.get(field):
                bb_hits[field] += 1
        bb_bonus[r.get("bonus_score", 0)] += 1

    if bb_totals["bars"] == 0:
        print("  No bb_kdj bar_eval events found.")
    else:
        n = bb_totals["bars"]
        print(f"  bb_kdj  ({n} bars evaluated)")
        for field in ("bb_touch", "kdj_cross", "rsi_oversold", "ranging", "volume_spike"):
            print(f"    {field:<16} {bb_hits[field]:4d}  ({100*bb_hits[field]/n:.1f}%)")
        print(f"  bonus distribution: ", end="")
        for k in sorted(bb_bonus):
            print(f"  {k}={bb_bonus[k]}", end="")
        print()

    # per-strategy bar counts
    strat_counts: Counter = Counter()
    for r in records:
        if r.get("event") == "bar_eval":
            strat_counts[r.get("strategy", "?")] += 1
    print(f"\n  bar_eval counts by strategy:")
    for s, c in sorted(strat_counts.items()):
        print(f"    {s:<12} {c}")


def _staleness(records: list[dict]) -> None:
    section("3. CANDLE STALENESS  (candle_age_s > 600 during market hours 09:30–16:00 ET)")
    # Only flag staleness during trading hours — pre-market startup evals of last session's
    # closing candle are expected and not a problem.
    market_stale = []
    for r in records:
        if r.get("event") != "bar_eval" or r.get("candle_age_s", 0) <= 600:
            continue
        try:
            ts = datetime.fromisoformat(r["ts"])
            h, m = ts.hour, ts.minute
            if (h == 9 and m >= 30) or (10 <= h <= 15) or (h == 16 and m == 0):
                market_stale.append(r)
        except (ValueError, KeyError):
            pass
    if not market_stale:
        print("  No in-session stale candles detected.")
        return
    by_strat: Counter = Counter()
    worst = max(market_stale, key=lambda r: r["candle_age_s"])
    for r in market_stale:
        by_strat[r.get("strategy", "?")] += 1
    for s, c in sorted(by_strat.items()):
        print(f"  [{s}] {c} stale bars")
    print(f"  Worst: {worst.get('candle_age_s')}s at {worst.get('ts', '?')} (candle {worst.get('candle_ts', '?')})")


def _trades(records: list[dict]) -> None:
    section("4. TRADES")
    opens = [r for r in records if r.get("event") == "position_open"]
    closes = [r for r in records if r.get("event") == "position_close"]

    if not opens:
        print("  No trades opened.")
        return

    print(f"  Opened: {len(opens)}   Closed: {len(closes)}")
    print()
    for o in opens:
        sym = o.get("symbol", "?")
        strat = o.get("strategy", "?")
        entry = o.get("entry", "?")
        stop = o.get("stop", "?")
        qty = o.get("qty", "?")
        ts = o.get("ts", "?")
        print(f"  OPEN   {ts}  {sym}/{strat}  entry={entry}  stop={stop}  qty={qty}")

        # find matching close (same symbol + strategy, after open ts)
        match = next(
            (c for c in closes
             if c.get("symbol") == sym and c.get("strategy") == strat and c.get("ts", "") > ts),
            None,
        )
        if match:
            print(f"  CLOSE  {match.get('ts','?')}  {sym}/{strat}  exit={match.get('exit','?')}  "
                  f"reason={match.get('reason','?')}  pnl={match.get('pnl','?'):+}  "
                  f"hold_bars={match.get('hold_bars', '?')}")
        else:
            print(f"  CLOSE  (position still open)")
        print()


def _skips(records: list[dict]) -> None:
    section("5. WHY NO ENTRY  (signal_skip + risk_block events)")
    skip_counts: Counter = Counter()
    block_counts: Counter = Counter()

    for r in records:
        evt = r.get("event")
        strat = r.get("strategy", "?")
        if evt == "signal_skip":
            skip_counts[(strat, r.get("reason", "?"))] += 1
        elif evt == "risk_block":
            block_counts[(strat, r.get("reason", "?"))] += 1

    if not skip_counts and not block_counts:
        print("  No skips or risk blocks logged.")
        return

    if skip_counts:
        print("  signal_skip:")
        for (strat, reason), count in sorted(skip_counts.items(), key=lambda x: -x[1]):
            print(f"    [{strat}] {reason:<35} ×{count}")

    if block_counts:
        print("  risk_block:")
        for (strat, reason), count in sorted(block_counts.items(), key=lambda x: -x[1]):
            print(f"    [{strat}] {reason:<35} ×{count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose paper runner JSONL logs.")
    parser.add_argument("--date", help="YYYY-MM-DD (default: today)")
    parser.add_argument("--all", action="store_true", help="Process all available log dates")
    parser.add_argument("--symbol", help="Filter to one symbol, e.g. US.SPY")
    args = parser.parse_args()

    logs_dir = Path(__file__).parent.parent / "logs"
    paths = _find_logs(logs_dir, args.date, args.symbol, args.all)

    if not paths:
        date_hint = args.date or datetime.now().strftime("%Y-%m-%d")
        print(f"No log files found for {date_hint}. Try --date YYYY-MM-DD or --all.")
        sys.exit(1)

    print(f"Loading {len(paths)} log file(s):")
    for p in paths:
        print(f"  {p.name}")

    records = _load_jsonl(paths)
    print(f"  {len(records)} records total")

    _uptime(records)
    _signals(records)
    _staleness(records)
    _trades(records)
    _skips(records)
    print()


if __name__ == "__main__":
    main()
