"""Comprehensive trade analysis from paper runner JSONL logs.

Usage:
    python scripts/analyze_trades.py [--date YYYY-MM-DD] [--all] [--symbol US.SPY] [--strategy vwap_pb]

Default: all available log dates.

Sections:
    1.  Overview          — total trades, win rate, PnL across all strategies
    2.  Per-strategy      — trades/wins/losses/PF/avg hold per strategy
    3.  Time-of-day       — entry hour (ET) → trades, win rate, avg PnL
    4.  Exit reasons      — breakdown by strategy and reason
    5.  VWAP PB           — cross_count and entry hour on wins vs losses
    5b. Gap Fade          — direction/symbol/exit breakdown + skip attribution
    6.  ORB filters       — vol_fail / too_late / before_cutoff / scorer skip rates
    7.  BB+KDJ signals    — bonus≥2 bar composition, why no entry
    7b. BB+KDJ cross-age  — w=0 purity vs window dilution
    8.  Regime gate       — days gated, label distribution, bars blocked per strategy
    9.  Gate attribution  — all signal_skip + risk_block counts per strategy
    10. Daily trend       — PnL per session date with cumulative
    11. Concurrent exposure
"""
import argparse
import io
import json
import re
import sys
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm import clock  # noqa: E402


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


def _find_logs(logs_dir: Path, date_str: str | None, symbol: str | None, all_dates: bool,
               from_date: str | None = None) -> list[Path]:
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
        if from_date and date < from_date:
            continue
        if not all_dates and not date_str:
            today = clock.today().strftime("%Y-%m-%d")
            if date != today:
                continue
        results.append(p)
    return results


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _to_et(ts_str: str) -> datetime:
    """Parse event timestamp and return as Eastern Time.

    events.py writes ts = clock.now_et().isoformat() (fixed 2026-06-18, previously UTC).
    Naive timestamps are assumed to be ET — attaching ZoneInfo is needed only for
    astimezone() to work; no offset conversion should happen.
    """
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("America/New_York"))
    return dt.astimezone(ZoneInfo("America/New_York"))


def _pair_trades(records: list[dict]) -> list[dict]:
    """Pair position_open with position_close. Returns list of trade dicts.

    Deduplicates by (symbol, strategy, ts) — old fire-and-forget logs (pre-Jun-10)
    wrote position_open/close once per poll cycle instead of once on entry/exit.
    """
    def _dedup(events: list[dict]) -> list[dict]:
        seen: set = set()
        out = []
        for r in events:
            key = (r.get("symbol") or r.get("_sym"), r.get("strategy"), r.get("ts"))
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    opens = _dedup([r for r in records if r.get("event") == "position_open"])
    closes = _dedup([r for r in records if r.get("event") == "position_close"])
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
        entry = o.get("entry", 0.0)
        stop = o.get("stop", 0.0)
        qty = o.get("qty", 1) or 1
        direction = o.get("direction", "long")
        pnl = match.get("pnl") if match else None

        # Size-independent metrics. R = PnL / initial risk; bps = return on notional.
        risk_share = (entry - stop) if direction == "long" else (stop - entry)
        r_mult = (pnl / (risk_share * qty)) if (pnl is not None and risk_share > 0) else None
        bps = (pnl / (entry * qty) * 10000) if (pnl is not None and entry > 0) else None

        trades.append({
            "symbol": sym,
            "strategy": strat,
            "entry": entry,
            "stop": stop,
            "qty": qty,
            "direction": direction,
            "kdj_cross_age": o.get("kdj_cross_age"),
            "open_ts": o["ts"],
            "open_et": _to_et(o["ts"]),
            "close_ts": match["ts"] if match else None,
            "close_et": _to_et(match["ts"]) if match else None,
            "exit": match.get("exit") if match else None,
            "reason": match.get("reason") if match else None,
            "pnl": pnl,
            "r_mult": r_mult,
            "bps": bps,
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

    header = (f"  {'Strategy':<12} {'Trades':>6} {'W':>4} {'L':>4} {'Win%':>6} {'PnL':>8} "
              f"{'PF':>6} {'AvgR':>6} {'AvgBps':>7} {'AvgHold':>8}")
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
        r_vals = [t["r_mult"] for t in closed if t["r_mult"] is not None]
        bps_vals = [t["bps"] for t in closed if t["bps"] is not None]
        avg_r = f"{sum(r_vals)/len(r_vals):+.2f}" if r_vals else "—"
        avg_bps = f"{sum(bps_vals)/len(bps_vals):+.1f}" if bps_vals else "—"
        win_pct = f"{100*len(wins)/len(closed):.0f}%" if closed else "—"
        pf_str = f"{pf:.2f}" if gross_loss > 0 else "∞" if gross_win > 0 else "—"
        print(f"  {strat:<12} {len(ts):>6} {len(wins):>4} {len(losses):>4} {win_pct:>6} "
              f"{total_pnl:>+8.2f} {pf_str:>6} {avg_r:>6} {avg_bps:>7} {avg_hold:>7.1f}b")
    print("\n  AvgR = avg PnL / initial risk (entry−stop).  AvgBps = avg return on notional.")
    print("  Slippage hurdle: SPY/QQQ/IWM round-trip spread+slip ≈ 1–3 bps. AvgBps must clear it.")


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


def _gap_fade_deep_dive(trades: list[dict], records: list[dict]) -> None:
    section("5b. GAP FADE DEEP-DIVE")
    gf_trades = [t for t in trades if t["strategy"] == "gap_fade" and t["closed"]]
    gf_skips = [r for r in records if r.get("event") == "signal_skip" and r.get("strategy") == "gap_fade"]

    if not gf_trades and not gf_skips:
        print("  No gap_fade activity.")
        return

    longs = [t for t in gf_trades if t["direction"] == "long"]
    shorts = [t for t in gf_trades if t["direction"] == "short"]
    wins = [t for t in gf_trades if t["win"]]
    print(f"  Total: {len(gf_trades)} trades  {len(wins)}W / {len(gf_trades)-len(wins)}L")
    print()

    # Direction breakdown
    print("  Direction:")
    for label, ts in [("long  (gap-down fade)", longs), ("short (gap-up fade) ", shorts)]:
        if not ts:
            print(f"    {label}  0 trades")
            continue
        w = sum(1 for t in ts if t["win"])
        pnl = sum(t["pnl"] for t in ts if t["pnl"] is not None)
        gw = sum(t["pnl"] for t in ts if t["pnl"] and t["pnl"] > 0)
        gl = abs(sum(t["pnl"] for t in ts if t["pnl"] and t["pnl"] < 0))
        pf_str = f"{gw/gl:.2f}" if gl > 0 else "∞" if gw > 0 else "—"
        print(f"    {label}  {len(ts):>2} trades  {w}/{len(ts)} wins  PF={pf_str}  PnL={pnl:+.2f}")

    # Symbol breakdown
    print()
    print("  Symbol:")
    by_sym: dict[str, list] = defaultdict(list)
    for t in gf_trades:
        by_sym[t["symbol"]].append(t)
    for sym in sorted(by_sym):
        ts = by_sym[sym]
        w = sum(1 for t in ts if t["win"])
        pnl = sum(t["pnl"] for t in ts if t["pnl"] is not None)
        dirs = Counter(t["direction"] for t in ts)
        dir_str = " ".join(f"{d[0].upper()}{n}" for d, n in sorted(dirs.items()))
        print(f"    {sym:<8}  {len(ts):>2} trades  {w}/{len(ts)} wins  PnL={pnl:+.2f}  [{dir_str}]")

    # Exit reason per direction
    print()
    print("  Exit reasons:")
    for dir_label, ts in [("long", longs), ("short", shorts)]:
        if not ts:
            continue
        by_reason: Counter = Counter(t["reason"] for t in ts if t["reason"])
        for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
            sub = [t for t in ts if t["reason"] == reason]
            pnl = sum(t["pnl"] for t in sub if t["pnl"] is not None)
            print(f"    [{dir_label}] {reason:<12} ×{count}  pnl={pnl:+.2f}")

    # Enrich trades with gap_pct from position_open events
    open_events = {
        (r.get("symbol"), r.get("ts")): r
        for r in records
        if r.get("event") == "position_open" and r.get("strategy") == "gap_fade"
    }
    for t in gf_trades:
        ev = open_events.get((t["symbol"], t["open_ts"]), {})
        t["gap_pct"] = ev.get("gap_pct")
        t["vix_at_entry"] = ev.get("vix_at_entry")

    # Gap size bucket breakdown (if gap_pct logged)
    tagged_gap = [t for t in gf_trades if t.get("gap_pct") is not None]
    if tagged_gap:
        print()
        print("  Gap size buckets:")
        buckets = [("0.3–0.6%", 0.3, 0.6), ("0.6–1.0%", 0.6, 1.0), (">1.0%", 1.0, 99)]
        for label, lo, hi in buckets:
            sub = [t for t in tagged_gap if lo <= abs(t["gap_pct"]) < hi]
            if not sub:
                continue
            w = sum(1 for t in sub if t["win"])
            pnl = sum(t["pnl"] for t in sub if t["pnl"] is not None)
            gw = sum(t["pnl"] for t in sub if t["pnl"] and t["pnl"] > 0)
            gl = abs(sum(t["pnl"] for t in sub if t["pnl"] and t["pnl"] < 0))
            pf_str = f"{gw/gl:.2f}" if gl > 0 else "∞" if gw > 0 else "—"
            print(f"    {label:<12}  {len(sub):>2} trades  {w}/{len(sub)} wins  PF={pf_str}  PnL={pnl:+.2f}")

    # Individual trades
    print()
    print("  Trade log:")
    for t in sorted(gf_trades, key=lambda x: x["open_ts"]):
        gap_str = f"  gap={t['gap_pct']:+.2f}%" if t.get("gap_pct") is not None else ""
        vix_str = f"  VIX={t['vix_at_entry']:.1f}" if t.get("vix_at_entry") else ""
        print(f"    {'WIN ' if t['win'] else 'LOSS'}  {t['symbol']:<8}  {t['direction']:<5}  "
              f"{t['open_et'].strftime('%Y-%m-%d %H:%M')}  "
              f"entry={t['entry']:.2f}  pnl={t['pnl']:+.2f}  {t['reason']}{gap_str}{vix_str}")

    # Skip reason breakdown
    if gf_skips:
        print()
        skip_by_reason: Counter = Counter(r.get("reason", "?") for r in gf_skips)
        total_skips = sum(skip_by_reason.values())
        print(f"  Skip reasons ({total_skips} total across {len({r['ts'][:10] for r in gf_skips})} sessions):")
        for reason, count in sorted(skip_by_reason.items(), key=lambda x: -x[1]):
            print(f"    {reason:<30} ×{count:>5}  ({100*count/total_skips:.1f}%)")


def _regime_gate_summary(records: list[dict], logs_dir: Path) -> None:
    section("8. REGIME GATE SUMMARY  (signal_skip reason=regime_gate)")
    dates = sorted({r.get("ts", "")[:10] for r in records if r.get("ts") and r.get("ts")[:10] >= "2020"})
    if not dates:
        print("  No dated records.")
        return

    # Load regime label for each session date
    regime_by_date: dict[str, str] = {}
    for date in dates:
        f = logs_dir / f"regime_{date}.json"
        if f.exists():
            try:
                regime_by_date[date] = json.loads(f.read_text()).get("regime", "unknown")
            except Exception:
                regime_by_date[date] = "parse_error"
        else:
            regime_by_date[date] = "no_file"

    gate_skips = [r for r in records if r.get("event") == "signal_skip" and r.get("reason") == "regime_gate"]
    shadow_skips = [r for r in records if r.get("event") == "signal_skip"
                    and "shadow" in (r.get("reason") or "")]

    days_blocked = len({r.get("ts", "")[:10] for r in gate_skips})
    label_counts: Counter = Counter(regime_by_date.values())
    blocked_labels = {r.get("regime") for r in gate_skips if r.get("regime")}

    print(f"  Sessions loaded: {len(dates)}")
    print()
    print("  Label distribution:")
    for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
        flag = "← blocked" if label in blocked_labels else ""
        pct = 100 * count / len(dates)
        print(f"    {label:<16} {count:>3} days  ({pct:.0f}%)  {flag}")

    print()
    print(f"  Gate fired:    {days_blocked}/{len(dates)} days")
    print(f"  Bars blocked:  {len(gate_skips)}")
    if shadow_skips:
        print(f"  Shadow events: {len(shadow_skips)}  (gate_enabled=false days)")

    by_strat: Counter = Counter(r.get("strategy", "?") for r in gate_skips)
    if by_strat:
        print()
        print("  Blocked bars by strategy:")
        for strat, count in sorted(by_strat.items(), key=lambda x: -x[1]):
            print(f"    {strat:<16} {count:>5} bars")


def _gate_attribution(records: list[dict]) -> None:
    section("9. GATE ATTRIBUTION  (all signal_skip + risk_block per strategy)")
    all_skips = [r for r in records if r.get("event") in ("signal_skip", "risk_block")]
    if not all_skips:
        print("  No skip or block events found.")
        return

    by_strat: dict[str, Counter] = defaultdict(Counter)
    for r in all_skips:
        strat = r.get("strategy") or "unknown"
        reason = r.get("reason") or r.get("event", "?")
        by_strat[strat][reason] += 1

    for strat in sorted(by_strat):
        counts = by_strat[strat]
        total = sum(counts.values())
        print(f"  [{strat}]  {total:,} total")
        for reason, count in sorted(counts.items(), key=lambda x: -x[1]):
            pct = 100 * count / total
            bar = "█" * int(pct / 5)
            print(f"    {reason:<35} ×{count:>6}  {pct:>5.1f}%  {bar}")
        print()


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
        print(f"  {'Date':<12} {'vol_fail':>9} {'too_late':>9} {'cutoff':>8} {'scorer':>7} {'shorts_ks':>10}")
        for d in sorted(by_date):
            c = by_date[d]
            print(f"  {d:<12} {c.get('orb_vol_fail',0):>9} {c.get('orb_too_late',0):>9} "
                  f"{c.get('orb_before_cutoff',0):>8} {c.get('orb_claude_score',0):>7} "
                  f"{c.get('orb_shorts_kill_switch',0):>10}")


def _bb_kdj_signals(records: list[dict], kdj_window: int = 3) -> None:
    section(f"7. BB+KDJ SIGNAL CONTEXT  (bar_eval bonus≥2, KDJ window=w{kdj_window})")
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
    kdj_same = sum(1 for r in bonus2 if r.get("signals", {}).get("kdj_cross"))
    both_same = sum(1 for r in bonus2 if r.get("signals", {}).get("bb_touch")
                    and r.get("signals", {}).get("kdj_cross"))

    print(f"\n  Of bonus≥2 bars (same-bar signals from logs):")
    print(f"    bb_touch:                {bb_touch:>4}  ({100*bb_touch/len(bonus2):.1f}%)")
    print(f"    kdj_cross (same-bar):    {kdj_same:>4}  ({100*kdj_same/len(bonus2):.1f}%)")
    print(f"    both same-bar:           {both_same:>4}  ({100*both_same/len(bonus2):.1f}%)")

    # w=N window check: rebuild per-(sym, date) bar sequence and check rolling window
    # This mirrors the live paper runner logic: kdj_cross within last N bars counts.
    sym_date_bars: dict[tuple, list[dict]] = defaultdict(list)
    seen: dict[tuple, dict] = {}
    for r in evals:
        key = (r.get("_sym", ""), r.get("ts", "")[:10], r["candle_ts"])
        if key not in seen:
            seen[key] = r
            sym_date_bars[(r.get("_sym", ""), r.get("ts", "")[:10])].append(r)

    # Per-symbol window overrides (e.g. US.SPY:0 requires same-bar cross live)
    try:
        from mm.config import cfg
        overrides = cfg.kdj_window_overrides
    except Exception:
        overrides = {}

    would_fire = []
    for (sym, _), bars in sym_date_bars.items():
        w = overrides.get(sym, kdj_window)
        bars.sort(key=lambda r: r["candle_ts"])
        for i, r in enumerate(bars):
            if not r["signals"].get("bb_touch") or r.get("bonus_score", 0) < 2:
                continue
            start = max(0, i - w)
            if any(b["signals"].get("kdj_cross") for b in bars[start:i + 1]):
                would_fire.append(r)

    ov_note = f", overrides={overrides}" if overrides else ""
    print(f"\n  With w={kdj_window} rolling window (mirrors live runner logic{ov_note}):")
    print(f"    bb_touch + kdj_w + bonus≥2: {len(would_fire):>4}  ← actual would-fire count")

    if would_fire:
        # Show each would-fire bar and what happened.
        # Checks risk_block AND signal_skip events (e.g. entry_unfilled, already_attempted).
        # Note: _entry_attempted dedup emits no log event — silence here is normal after
        # a candle has already been attempted (first poll fires, subsequent polls silent).
        risk_blocks = [r for r in records if r.get("event") == "risk_block"
                       and r.get("strategy") == "bb_kdj"]
        bb_skips = [r for r in records if r.get("event") == "signal_skip"
                    and r.get("strategy") == "bb_kdj"]
        bb_entries = [r for r in records if r.get("event") == "position_open"
                      and r.get("strategy") == "bb_kdj"]

        events_by_sym_date: dict[tuple, list] = defaultdict(list)
        for rb in risk_blocks + bb_skips:
            events_by_sym_date[(rb.get("_sym", ""), rb.get("ts", "")[:10])].append(rb)
        entries_by_sym_date: dict[tuple, list] = defaultdict(list)
        for e in bb_entries:
            entries_by_sym_date[(e.get("_sym", ""), e.get("ts", "")[:10])].append(e)

        print()
        for r in sorted(would_fire, key=lambda x: x.get("ts", "")):
            sym = r.get("_sym", "?")
            date = r.get("ts", "")[:10]
            cts = r["candle_ts"]
            bonus = r.get("bonus_score", 0)
            day_events = events_by_sym_date.get((sym, date), [])
            reasons = Counter(b.get("reason") or b.get("event", "?") for b in day_events)
            day_entries = entries_by_sym_date.get((sym, date), [])
            if day_entries:
                entry_str = f"ENTERED at {day_entries[0].get('entry')}"
            elif reasons:
                entry_str = ", ".join(f"{k}×{v}" for k, v in reasons.items())
            else:
                entry_str = "no entry/block/skip logged (_entry_attempted dedup?)"
            print(f"    {date} {sym:<8} {cts}  bonus={bonus}  → [{entry_str}]")

    # Overall risk_block summary for bb_kdj
    all_blocks = [r for r in records if r.get("event") == "risk_block" and r.get("strategy") == "bb_kdj"]
    if all_blocks:
        print(f"\n  All bb_kdj risk_blocks across loaded sessions:")
        for reason, count in sorted(Counter(r.get("reason") for r in all_blocks).items(),
                                    key=lambda x: -x[1]):
            print(f"    {reason:<35} ×{count}")


def _bb_kdj_cross_age(trades: list[dict]) -> None:
    """KDJ cross-age subset comparison — the w=0 vs w>0 dilution question.

    Backtest: w=0 (same-bar cross) PF=2.131 vs w=3 (live) PF=1.107. Every live
    trade logs kdj_cross_age, so we can check whether the pure same-bar subset
    outperforms diluted window entries in forward data. Gate is in
    docs/evaluation_criteria.md (3 months of data).
    """
    section("7b. BB+KDJ CROSS-AGE SUBSETS  (w=0 purity vs window dilution)")
    bb = [t for t in trades if t["strategy"] == "bb_kdj" and t["closed"]]
    if not bb:
        print("  No closed bb_kdj trades yet.")
        return
    tagged = [t for t in bb if t.get("kdj_cross_age") is not None]
    untagged = len(bb) - len(tagged)
    if untagged:
        print(f"  ({untagged} trade(s) predate cross-age logging — excluded)")
    if not tagged:
        return

    subsets = {
        "w=0 (same-bar cross)": [t for t in tagged if t["kdj_cross_age"] == 0],
        "w>0 (window entries) ": [t for t in tagged if t["kdj_cross_age"] > 0],
    }
    print(f"  {'Subset':<24} {'Trades':>6} {'Win%':>6} {'PnL':>8} {'AvgR':>6}")
    print("  " + "-" * 54)
    for label, ts in subsets.items():
        if not ts:
            print(f"  {label:<24} {'0':>6} {'—':>6} {'—':>8} {'—':>6}")
            continue
        wins = sum(1 for t in ts if t["win"])
        pnl = sum(t["pnl"] for t in ts if t["pnl"] is not None)
        r_vals = [t["r_mult"] for t in ts if t["r_mult"] is not None]
        avg_r = f"{sum(r_vals)/len(r_vals):+.2f}" if r_vals else "—"
        print(f"  {label:<24} {len(ts):>6} {100*wins/len(ts):>5.0f}% {pnl:>+8.2f} {avg_r:>6}")

    age_dist = Counter(t["kdj_cross_age"] for t in tagged)
    print(f"\n  Cross-age distribution: " +
          ", ".join(f"age {a}: {n}" for a, n in sorted(age_dist.items())))


def _concurrency(trades: list[dict]) -> None:
    section("11. CONCURRENT EXPOSURE  (live sessions)")
    closed = [t for t in trades if t["closed"]]
    if not closed:
        print("  No closed trades.")
        return
    events = []
    for t in closed:
        notional = (t["entry"] or 0) * (t["qty"] or 1)
        events.append((t["open_ts"], 1, notional))
        events.append((t["close_ts"], -1, notional))
    events.sort(key=lambda e: (e[0], -e[1]))

    open_now, notional_now = 0, 0.0
    peak_n, peak_notional, peak_at = 0, 0.0, None
    stacked_entries = 0
    for ts, delta, notional in events:
        if delta == 1:
            if open_now >= 1:
                stacked_entries += 1
            open_now += 1
            notional_now += notional
            if open_now > peak_n:
                peak_n, peak_at = open_now, ts
            peak_notional = max(peak_notional, notional_now)
        else:
            open_now -= 1
            notional_now -= notional

    print(f"  Peak simultaneous positions: {peak_n}" +
          (f"  (at {peak_at})" if peak_n > 1 else ""))
    print(f"  Peak combined notional:      ${peak_notional:,.0f}")
    print(f"  Entries while ≥1 open:       {stacked_entries}/{len(closed)}")


def _daily_trend(trades: list[dict]) -> None:
    section("10. DAILY PnL TREND")
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
    parser.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD",
                        help="Exclude logs before this date (default: 2026-06-10 for live logs)")
    parser.add_argument("--symbol", help="Filter to one symbol, e.g. US.SPY")
    parser.add_argument("--strategy", help="Filter to one strategy, e.g. vwap_pb")
    parser.add_argument("--dir", dest="logs_dir", metavar="PATH",
                        help="Log directory (default: logs/). Use replay_out/ for replay data.")
    parser.add_argument("--interpret", action="store_true",
                        help="Pass P&L breakdown to Haiku for a brief interpretation")
    args = parser.parse_args()

    # Default to --all when no date specified
    all_dates = args.all or not args.date

    logs_dir = Path(args.logs_dir) if args.logs_dir else Path(__file__).parent.parent / "logs"

    # For live logs, default to excluding pre-confirmed-fill era. For custom dirs (replay), no default cutoff.
    if args.from_date is not None:
        from_date = args.from_date
    elif args.logs_dir:
        from_date = None  # replay dirs don't need the era cutoff
    else:
        from_date = "2026-06-10" if all_dates else None

    paths = _find_logs(logs_dir, args.date, args.symbol, all_dates, from_date)

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

    buf = io.StringIO() if args.interpret else None
    with redirect_stdout(buf if buf else sys.stdout):
        _overview(trades)
        _per_strategy(trades)
        _time_of_day(trades)
        _exit_reasons(trades)
        _vwap_pb_deep_dive(trades, records)
        _gap_fade_deep_dive(trades, records)
        _orb_filters(records)
        _bb_kdj_signals(records)
        _bb_kdj_cross_age(trades)
        _regime_gate_summary(records, logs_dir)
        _gate_attribution(records)
        _daily_trend(trades)
        _concurrency(trades)
        print()

    if buf:
        captured = buf.getvalue()
        print(captured, end="")
        from mm.analyst import haiku_interpret
        print("\n--- Haiku interpretation ---")
        print(haiku_interpret(captured,
            "What patterns stand out in the losing trades by strategy, hour, or exit reason? "
            "Which strategy or time bucket looks most problematic? Be brief."))


if __name__ == "__main__":
    main()
