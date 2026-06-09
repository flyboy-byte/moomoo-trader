"""Comprehensive trade analysis from paper runner JSONL logs.

Usage:
    python scripts/analyze_trades.py [--date YYYY-MM-DD] [--all] [--symbol US.SPY] [--strategy vwap_pb]

Default: all available log dates.

Sections:
    1. Overview        — total trades, win rate, PnL across all strategies
    2. Per-strategy    — trades/wins/losses/PF/avg hold per strategy
    3. Time-of-day     — entry hour (ET) → trades, win rate, avg PnL
    4. Exit reasons    — breakdown by strategy and reason
    5. VWAP PB         — cross_count and entry hour on wins vs losses
    6. ORB filters     — vol_fail / before_cutoff / other skip rates
    7. BB+KDJ signals  — bonus≥2 bar composition, why no entry
    8. Daily trend     — PnL per session date with cumulative
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


# ---------------------------------------------------------------------------
# Shared helpers (same patterns as diagnose_logs.py)
# ---------------------------------------------------------------------------

_SYM_PATTERN = re.compile(r"paper_(.+)_\d{4}-\d{2}-\d{2}\.jsonl$")


def _load_jsonl(paths: list[Path]) -> list[dict]:
    records = []
    for p in paths:
        m = _SYM_PATTERN.match(p.name)
        source_sym = m.group(1).replace("_", ".", 1) if m else ""
        with p.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    # Annotate with source symbol (bar_eval doesn't include symbol field)
                    r.setdefault("_sym", source_sym)
                    records.append(r)
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
        sym_dotted = sym.replace("_", ".", 1)
        if symbol and sym_dotted != symbol:
            continue
        if date_str and date != date_str:
            continue
        if not all_dates and not date_str:
            today = datetime.now().strftime("%Y-%m-%d")
            if date != today:
                continue
        results.append(p)
    return results


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _to_et(ts_str: str) -> datetime:
    """Parse UTC ISO timestamp and convert to Eastern Time."""
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("America/New_York"))


def _pair_trades(records: list[dict]) -> list[dict]:
    """Pair position_open with position_close. Returns list of trade dicts."""
    opens = [r for r in records if r.get("event") == "position_open"]
    closes = [r for r in records if r.get("event") == "position_close"]
    trades = []
    for o in opens:
        sym = o.get("symbol") or o.get("_sym", "?")
        strat = o.get("strategy") or "unknown"
        match = next(
            (c for c in closes
             if c.get("symbol") == sym and c.get("strategy") == strat
             and c.get("ts", "") > o["ts"]),
            None,
        )
        trades.append({
            "symbol": sym,
            "strategy": strat,
            "entry": o.get("entry", 0.0),
            "stop": o.get("stop", 0.0),
            "qty": o.get("qty", 1),
            "direction": o.get("direction", "long"),
            "open_ts": o["ts"],
            "open_et": _to_et(o["ts"]),
            "close_ts": match["ts"] if match else None,
            "close_et": _to_et(match["ts"]) if match else None,
            "exit": match.get("exit") if match else None,
            "reason": match.get("reason") if match else None,
            "pnl": match.get("pnl") if match else None,
            "hold_bars": match.get("hold_bars") if match else None,
            "closed": match is not None,
            "win": (match.get("pnl", 0) or 0) > 0 if match else None,
        })
    return trades


# ---------------------------------------------------------------------------
# Analysis sections
# ---------------------------------------------------------------------------

def _overview(trades: list[dict]) -> None:
    section("1. OVERVIEW")
    closed = [t for t in trades if t["closed"]]
    if not trades:
        print("  No trades found.")
        return
    wins = [t for t in closed if t["win"]]
    total_pnl = sum(t["pnl"] for t in closed if t["pnl"] is not None)
    gross_win = sum(t["pnl"] for t in closed if t["pnl"] and t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in closed if t["pnl"] and t["pnl"] < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    print(f"  Trades opened:  {len(trades)}")
    print(f"  Trades closed:  {len(closed)}  (open: {len(trades) - len(closed)})")
    if closed:
        print(f"  Win rate:       {len(wins)}/{len(closed)} = {100*len(wins)/len(closed):.1f}%")
        print(f"  Total PnL:      {total_pnl:+.2f}")
        print(f"  Profit factor:  {pf:.3f}")
        print(f"  Avg PnL/trade:  {total_pnl/len(closed):+.2f}")


def _per_strategy(trades: list[dict]) -> None:
    section("2. PER-STRATEGY")
    by_strat: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_strat[t["strategy"]].append(t)

    header = f"  {'Strategy':<12} {'Trades':>6} {'W':>4} {'L':>4} {'Win%':>6} {'PnL':>8} {'PF':>6} {'AvgHold':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for strat in sorted(by_strat):
        ts = by_strat[strat]
        closed = [t for t in ts if t["closed"]]
        wins = [t for t in closed if t["win"]]
        losses = [t for t in closed if not t["win"]]
        total_pnl = sum(t["pnl"] for t in closed if t["pnl"] is not None)
        gross_win = sum(t["pnl"] for t in closed if t["pnl"] and t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in closed if t["pnl"] and t["pnl"] < 0))
        pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
        avg_hold = sum(t["hold_bars"] for t in closed if t["hold_bars"]) / len(closed) if closed else 0
        win_pct = f"{100*len(wins)/len(closed):.0f}%" if closed else "—"
        pf_str = f"{pf:.2f}" if gross_loss > 0 else "∞" if gross_win > 0 else "—"
        print(f"  {strat:<12} {len(ts):>6} {len(wins):>4} {len(losses):>4} {win_pct:>6} "
              f"{total_pnl:>+8.2f} {pf_str:>6} {avg_hold:>7.1f}b")


def _time_of_day(trades: list[dict]) -> None:
    section("3. TIME-OF-DAY  (entry hour ET, closed trades only)")
    closed = [t for t in trades if t["closed"]]
    if not closed:
        print("  No closed trades.")
        return

    by_hour: dict[int, list[dict]] = defaultdict(list)
    for t in closed:
        by_hour[t["open_et"].hour].append(t)

    print(f"  {'Hour (ET)':<12} {'Trades':>6} {'Wins':>6} {'Win%':>6} {'AvgPnL':>8}")
    print("  " + "-"*42)
    for h in sorted(by_hour):
        ts = by_hour[h]
        wins = [t for t in ts if t["win"]]
        avg_pnl = sum(t["pnl"] for t in ts if t["pnl"] is not None) / len(ts)
        print(f"  {h:02d}:00–{h+1:02d}:00   {len(ts):>6} {len(wins):>6} "
              f"{100*len(wins)/len(ts):>5.0f}% {avg_pnl:>+8.2f}")

    # Per-strategy breakdown if multiple strategies have trades
    strats = sorted({t["strategy"] for t in closed})
    if len(strats) > 1:
        print()
        for strat in strats:
            strat_closed = [t for t in closed if t["strategy"] == strat]
            if not strat_closed:
                continue
            print(f"  [{strat}]")
            by_h: dict[int, list[dict]] = defaultdict(list)
            for t in strat_closed:
                by_h[t["open_et"].hour].append(t)
            for h in sorted(by_h):
                ts = by_h[h]
                wins = [t for t in ts if t["win"]]
                avg_pnl = sum(t["pnl"] for t in ts if t["pnl"] is not None) / len(ts)
                print(f"    {h:02d}:00  {len(ts):>3} trades  {len(wins)}/{len(ts)} wins  {avg_pnl:+.2f} avg")


def _exit_reasons(trades: list[dict]) -> None:
    section("4. EXIT REASONS")
    closed = [t for t in trades if t["closed"] and t["reason"]]
    if not closed:
        print("  No closed trades.")
        return

    by_strat: dict[str, list[dict]] = defaultdict(list)
    for t in closed:
        by_strat[t["strategy"]].append(t)

    for strat in sorted(by_strat):
        print(f"  [{strat}]")
        by_reason: dict[str, list[dict]] = defaultdict(list)
        for t in by_strat[strat]:
            by_reason[t["reason"]].append(t)
        for reason in sorted(by_reason, key=lambda r: -len(by_reason[r])):
            ts = by_reason[reason]
            total_pnl = sum(t["pnl"] for t in ts if t["pnl"] is not None)
            wins = sum(1 for t in ts if t["win"])
            print(f"    {reason:<22} ×{len(ts):>2}  wins={wins}  pnl={total_pnl:+.2f}")
        print()


def _vwap_pb_deep_dive(trades: list[dict], records: list[dict]) -> None:
    section("5. VWAP PB DEEP-DIVE")
    pb_trades = [t for t in trades if t["strategy"] == "vwap_pb" and t["closed"]]
    if not pb_trades:
        print("  No closed vwap_pb trades.")
        return

    # For each trade, find the bar_eval event at the candle matching the entry timestamp
    # (candle_ts in bar_eval corresponds to the 5-min bar, entry ts is eval time ~60s later)
    bar_evals_pb = [r for r in records if r.get("event") == "bar_eval" and r.get("strategy") == "vwap_pb"]

    def _find_bar_eval(trade: dict) -> dict | None:
        open_ts = trade["open_ts"]
        # Find bar_eval for the same symbol closest before the position_open
        # Use _sym (source filename annotation) since bar_eval has no symbol field
        candidates = [
            r for r in bar_evals_pb
            if r.get("_sym") == trade["symbol"]
            and r.get("ts", "") <= open_ts
        ]
        return candidates[-1] if candidates else None

    wins = [t for t in pb_trades if t["win"]]
    losses = [t for t in pb_trades if not t["win"]]

    print(f"  Total: {len(pb_trades)} trades  {len(wins)}W / {len(losses)}L")
    print()

    # Entry hour distribution
    print("  Entry hour (ET):")
    for t in pb_trades:
        label = "WIN " if t["win"] else "LOSS"
        bar = _find_bar_eval(t)
        cross_count = bar["signals"].get("cross_count", "?") if bar else "?"
        print(f"    {label}  {t['symbol']:<8}  {t['open_et'].strftime('%H:%M ET')}  "
              f"cross_count={cross_count}  pnl={t['pnl']:+.2f}  reason={t['reason']}")

    print()
    # cross_count summary
    win_crosses: list = []
    loss_crosses: list = []
    for t in pb_trades:
        bar = _find_bar_eval(t)
        cc = bar["signals"].get("cross_count") if bar else None
        if cc is not None:
            (win_crosses if t["win"] else loss_crosses).append(cc)
    if win_crosses or loss_crosses:
        print(f"  cross_count on wins:   {sorted(win_crosses)}")
        print(f"  cross_count on losses: {sorted(loss_crosses)}")


def _orb_filters(records: list[dict]) -> None:
    section("6. ORB FILTER STATS  (signal_skip events)")
    orb_skips = [r for r in records if r.get("event") == "signal_skip" and r.get("strategy") == "orb"]
    if not orb_skips:
        print("  No ORB skips found.")
        return

    by_reason: Counter = Counter(r.get("reason", "?") for r in orb_skips)
    total = sum(by_reason.values())
    print(f"  Total ORB skips: {total}")
    for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
        print(f"    {reason:<30} ×{count:>4}  ({100*count/total:.1f}%)")

    # Per-date breakdown
    by_date: dict[str, Counter] = defaultdict(Counter)
    for r in orb_skips:
        date_str = r.get("ts", "")[:10]
        by_date[date_str][r.get("reason", "?")] += 1

    if len(by_date) > 1:
        print()
        print(f"  {'Date':<12} {'vol_fail':>9} {'cutoff':>8} {'shorts_ks':>10}")
        for d in sorted(by_date):
            c = by_date[d]
            print(f"  {d:<12} {c.get('orb_vol_fail',0):>9} {c.get('orb_before_cutoff',0):>8} "
                  f"{c.get('orb_shorts_kill_switch',0):>10}")


def _bb_kdj_signals(records: list[dict]) -> None:
    section("7. BB+KDJ SIGNAL CONTEXT  (bar_eval bonus≥2 bars)")
    evals = [r for r in records if r.get("event") == "bar_eval" and r.get("strategy") == "bb_kdj"]
    if not evals:
        print("  No bb_kdj bar_eval events.")
        return

    bonus2 = [r for r in evals if r.get("bonus_score", 0) >= 2]
    print(f"  Total bb_kdj bars evaluated: {len(evals)}")
    print(f"  Bars with bonus≥2:           {len(bonus2)}  ({100*len(bonus2)/len(evals):.1f}%)")

    if not bonus2:
        return

    bb_touch = sum(1 for r in bonus2 if r.get("signals", {}).get("bb_touch"))
    kdj_cross = sum(1 for r in bonus2 if r.get("signals", {}).get("kdj_cross"))
    both = sum(1 for r in bonus2 if r.get("signals", {}).get("bb_touch") and r.get("signals", {}).get("kdj_cross"))

    print(f"\n  Of bonus≥2 bars:")
    print(f"    bb_touch:           {bb_touch:>4}  ({100*bb_touch/len(bonus2):.1f}%)")
    print(f"    kdj_cross:          {kdj_cross:>4}  ({100*kdj_cross/len(bonus2):.1f}%)")
    print(f"    bb_touch+kdj_cross: {both:>4}  ({100*both/len(bonus2):.1f}%)  ← core gate met")

    # Why didn't the core-gate bars convert to entries?
    core_met_ts = {r["ts"] for r in bonus2 if r.get("signals", {}).get("bb_touch")
                   and r.get("signals", {}).get("kdj_cross")}
    if not core_met_ts:
        print("\n  No bars cleared the full core gate (bb_touch + kdj_cross + bonus≥2).")
        return

    # Find risk_blocks and signal_skips that immediately follow core-met bars
    risk_blocks = [r for r in records if r.get("event") == "risk_block" and r.get("strategy") == "bb_kdj"]
    block_reasons: Counter = Counter(r.get("reason", "?") for r in risk_blocks)
    if block_reasons:
        print(f"\n  Risk blocks (bb_kdj, all bars):")
        for reason, count in sorted(block_reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason:<35} ×{count}")
    else:
        print("\n  No risk_block events for bb_kdj.")


def _daily_trend(trades: list[dict]) -> None:
    section("8. DAILY PnL TREND")
    closed = [t for t in trades if t["closed"] and t["pnl"] is not None]
    if not closed:
        print("  No closed trades.")
        return

    by_date: dict[str, list[dict]] = defaultdict(list)
    for t in closed:
        date_str = t["open_ts"][:10]
        by_date[date_str].append(t)

    cumulative = 0.0
    print(f"  {'Date':<12} {'Trades':>6} {'W':>3} {'L':>3} {'PnL':>8} {'Cumul':>8}")
    print("  " + "-"*46)
    for d in sorted(by_date):
        ts = by_date[d]
        wins = sum(1 for t in ts if t["win"])
        day_pnl = sum(t["pnl"] for t in ts)
        cumulative += day_pnl
        print(f"  {d:<12} {len(ts):>6} {wins:>3} {len(ts)-wins:>3} {day_pnl:>+8.2f} {cumulative:>+8.2f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Comprehensive trade analysis from paper JSONL logs.")
    parser.add_argument("--date", help="YYYY-MM-DD")
    parser.add_argument("--all", action="store_true", help="All available dates (default when no --date)")
    parser.add_argument("--symbol", help="Filter to one symbol, e.g. US.SPY")
    parser.add_argument("--strategy", help="Filter to one strategy, e.g. vwap_pb")
    args = parser.parse_args()

    # Default to --all when no date specified
    all_dates = args.all or not args.date

    logs_dir = Path(__file__).parent.parent / "logs"
    paths = _find_logs(logs_dir, args.date, args.symbol, all_dates)

    if not paths:
        hint = args.date or "all dates"
        print(f"No log files found ({hint}). Try --date YYYY-MM-DD or --all.")
        sys.exit(1)

    print(f"Loading {len(paths)} log file(s):")
    for p in paths:
        print(f"  {p.name}")

    records = _load_jsonl(paths)
    print(f"  {len(records)} records total")

    # Filter by strategy if requested
    if args.strategy:
        records = [r for r in records
                   if r.get("strategy") == args.strategy or r.get("event") not in
                   ("bar_eval", "signal_skip", "risk_block", "position_open",
                    "position_close", "order_attempt", "order_result")]

    trades = _pair_trades(records)
    # Drop pre-multi-strategy logs that lack a strategy tag
    trades = [t for t in trades if t["strategy"] != "unknown"]
    if args.strategy:
        trades = [t for t in trades if t["strategy"] == args.strategy]

    _overview(trades)
    _per_strategy(trades)
    _time_of_day(trades)
    _exit_reasons(trades)
    _vwap_pb_deep_dive(trades, records)
    _orb_filters(records)
    _bb_kdj_signals(records)
    _daily_trend(trades)
    print()


if __name__ == "__main__":
    main()
