"""Weekly gate report — posts strategy gate progress to Discord.

Aggregates confirmed-fill trades (the era starting 2026-06-11, when the
fill-confirmation execution layer was deployed; earlier records are
unverified, see docs/evaluation_criteria.md) and reports each strategy's
sample progress toward its pre-registered evaluation gate. Also reports this
week's Gap Fade pre-market characteristics from the VPS's own rolling
archive (see scripts/fetch_daily_archive.py) — descriptive only, not a
backtest re-run; the full historical study stays a manual, local
scripts/research_premarket_gap.py run.

Intended to run from cron on the VPS every Saturday 00:30 UTC (= Friday
~20:30 ET during EDT, after that day's daily-archive fetch has run):
  30 0 * * 6  cd ~/moomoo && .venv/bin/python scripts/weekly_report.py

Run with --dry-run to print without posting to Discord.
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.config import cfg  # noqa: E402
from mm.gap_fade import _build_day_map  # noqa: E402
from mm.premarket import premarket_session, premarket_fill_pct, premarket_volume_ratio, \
    build_premarket_volume_history  # noqa: E402

# First session with broker-confirmed fills — gates evaluate from here only.
CONFIRMED_FILL_ERA = "2026-06-11"

# Pre-registered gates: strategy -> (sample size, description of trip condition)
GATES = {
    "vwap_pb": (20, "PF<1.0 or win%<40 → suspend"),
    "orb": (30, "PF<1.0 → check execution first"),
    "bb_kdj": (30, "PF<1.0 → switch to w=0"),
}


def _events() -> list[dict]:
    out = []
    for f in sorted(cfg.logs_dir.glob("paper_US_*_20*.jsonl")):
        date_str = f.stem.rsplit("_", 1)[-1]
        if date_str < CONFIRMED_FILL_ERA:
            continue
        for line in f.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def build_report() -> str:
    events = _events()
    closes = [e for e in events if e.get("event") == "position_close"]
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()

    stats: dict[str, dict] = defaultdict(lambda: {
        "n": 0, "wins": 0, "pnl": 0.0, "gw": 0.0, "gl": 0.0, "week_n": 0, "week_pnl": 0.0})
    for c in closes:
        s = stats[c.get("strategy", "?")]
        pnl = float(c.get("pnl", 0))
        s["n"] += 1
        s["pnl"] += pnl
        if pnl > 0:
            s["wins"] += 1
            s["gw"] += pnl
        else:
            s["gl"] += -pnl
        if c.get("ts", "") >= week_ago:
            s["week_n"] += 1
            s["week_pnl"] += pnl

    unfilled = sum(1 for e in events
                   if e.get("event") == "signal_skip" and e.get("reason") == "entry_unfilled")
    stuck = sum(1 for e in events
                if e.get("event") == "error" and "exit_unfilled" in str(e.get("message", "")))
    mismatches = sum(1 for e in events
                     if e.get("event") == "error" and "reconcile_mismatch" in str(e.get("message", "")))
    slips = [e["slippage_bps"] for e in events
             if e.get("event") in ("position_open", "position_close")
             and isinstance(e.get("slippage_bps"), (int, float))]

    lines = [f"**Weekly gate report** (confirmed-fill era since {CONFIRMED_FILL_ERA})"]
    for strat, (gate_n, gate_desc) in GATES.items():
        s = stats.get(strat)
        if not s or s["n"] == 0:
            lines.append(f"`{strat:8s}` 0/{gate_n} — no confirmed trades yet")
            continue
        pf = s["gw"] / s["gl"] if s["gl"] > 0 else float("inf")
        win = s["wins"] / s["n"] * 100
        bar = "█" * round(10 * min(s["n"] / gate_n, 1)) or "░"
        lines.append(
            f"`{strat:8s}` {s['n']}/{gate_n} {bar:<10s} "
            f"win {win:.0f}%  PnL {s['pnl']:+.2f}  PF {pf:.2f}  "
            f"(week: {s['week_n']} trades {s['week_pnl']:+.2f})")
        if s["n"] >= gate_n:
            lines.append(f"  ⚠ **GATE SAMPLE REACHED** — evaluate: {gate_desc}")
    avg_slip = sum(slips) / len(slips) if slips else 0.0
    lines.append(f"execution: {len(slips)} fills, avg slip {avg_slip:+.1f} bps, "
                 f"{unfilled} entries unfilled, {stuck} stuck exits, "
                 f"{mismatches} reconcile mismatches")
    lines.append("Knob freeze holds — no parameter changes until a gate trips.")
    return "\n".join(lines)


def _premarket_section() -> str:
    """Descriptive-only: this week's gap days per symbol from the VPS's own
    rolling RTH + extended-hours archive. Skips a symbol gracefully if its
    archive doesn't exist yet (e.g. fetch_daily_archive.py hasn't run/caught
    up yet)."""
    week_ago_date = (datetime.now() - timedelta(days=7)).date()
    lines = ["", "**Premarket (this week)**"]
    any_data = False

    for symbol in cfg.symbols:
        safe = symbol.replace(".", "_")
        rth_path = cfg.logs_dir / f"{safe}_K_5M_combined.csv"
        ext_path = cfg.logs_dir / f"{safe}_K_5M_EXT_combined.csv"
        if not rth_path.exists() or not ext_path.exists():
            lines.append(f"  {symbol}: archive not built yet")
            continue

        df_rth = pd.read_csv(rth_path)
        df_rth["time_key"] = pd.to_datetime(df_rth["time_key"])
        df_ext = pd.read_csv(ext_path)
        df_ext["time_key"] = pd.to_datetime(df_ext["time_key"])

        day_map = _build_day_map(df_rth)
        sessions = premarket_session(df_ext)
        if not sessions:
            lines.append(f"  {symbol}: no premarket sessions in archive yet")
            continue

        vol_history = build_premarket_volume_history(sessions)
        vol_avg20 = vol_history.rolling(20).mean().shift(1)

        week_dates = sorted(d for d in day_map if d in sessions and d >= week_ago_date)
        if not week_dates:
            lines.append(f"  {symbol}: no gap days this week")
            continue

        any_data = True
        for date in week_dates:
            info = day_map[date]
            prev_close, today_open = info["prev_close"], info["open"]
            gap_pct = (today_open - prev_close) / prev_close
            fill_pct = premarket_fill_pct(prev_close, today_open, sessions[date])
            today_vol = float(sessions[date]["volume"].sum())
            avg20 = vol_avg20.get(pd.Timestamp(date))
            vol_ratio = premarket_volume_ratio(today_vol, avg20) if avg20 and avg20 > 0 else None

            fp = f"{fill_pct*100:.0f}%" if fill_pct is not None else "n/a"
            vr = f"{vol_ratio:.2f}x" if vol_ratio is not None else "n/a"
            lines.append(f"  {symbol} {date}  gap {gap_pct*100:+.2f}%  fill {fp}  vol {vr}")

    if not any_data:
        lines.append("  (no gap days with full archive coverage this week)")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print, don't post")
    args = ap.parse_args()

    report = build_report() + "\n" + _premarket_section()
    print(report)
    if not args.dry_run:
        from mm.notifications import notify
        notify(report)


if __name__ == "__main__":
    main()
