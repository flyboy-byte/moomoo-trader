"""Canonical trade reconstruction from paper-runner JSONL logs.

One implementation of "turn position_open/position_close events into trades, net of
transaction costs", shared by every reporter. Added 2026-08-29.

Why this module exists
----------------------
Before it, `scripts/analyze_trades.py` and `scripts/web_dashboard.py` each had their
own pairing pass, and they disagreed in ways that mattered:

  * analyze_trades paired opens forward to closes, deduplicated the pre-2026-06-10
    fire-and-forget logs, and (after Goal A1) applied `mm/costs.py`.
  * web_dashboard paired closes backward to opens, did not deduplicate, and applied
    no cost model at all — while labelling its gross figure `net_pnl`.

So the dashboard reported the live portfolio at +$12.92 / PF 1.189 while
`analyze_trades.py` reported the same trades at net −$0.57 / PF 0.992. Two rulers,
one of them mislabelled, and whichever a session opened first won. That is the
divergence `docs/research-reset.md` calls out as loose end #1 / step B2a.

This module is the single ruler. Reporters format; they do not re-derive.

Profit factor is NOT defined here — import it from `mm.backtest`, the canonical
implementation (see `tests/test_metric_consistency.py`). Re-exported below purely so
callers doing cost-aware reporting need one import, never so a ninth version gets
written.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import costs

# Canonical PF, re-exported. Do not shadow it with a local definition — that mistake
# has been made and caught five times in this repo; see docs/strategy_graveyard.md
# "Reimplemented-Metric Drift".
from .backtest import profit_factor  # noqa: F401  (re-export)

_SYM_PATTERN = re.compile(r"paper_(.+)_\d{4}-\d{2}-\d{2}\.jsonl$")
_DATE_PATTERN = re.compile(r"paper_(.+)_(\d{4}-\d{2}-\d{2})\.jsonl$")

# Live logs before this date are from the fire-and-forget era: orders were logged
# without confirming the fill, so the "trades" in them are not reliably trades.
# scripts/analyze_trades.py has excluded them by default since it was written; the
# web dashboard did not, which is why it counted 119 trades where analyze_trades
# counted 102 on the same log directory. Same cutoff in one place now.
LIVE_LOGS_START = "2026-06-10"


def to_et(ts_str: str) -> datetime:
    """Parse an event timestamp and return it as Eastern Time.

    events.py writes ts = clock.now_et().isoformat() (fixed 2026-06-18, previously
    UTC). Naive timestamps are assumed to be ET — attaching ZoneInfo is needed only
    for astimezone() to work; no offset conversion should happen.
    """
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("America/New_York"))
    return dt.astimezone(ZoneInfo("America/New_York"))


def pair_trades(records: list[dict]) -> list[dict]:
    """Pair position_open with position_close. Returns a list of trade dicts.

    Deduplicates by (symbol, strategy, ts) — old fire-and-forget logs (pre-2026-06-10)
    wrote position_open/close once per poll cycle instead of once on entry/exit.

    Every trade carries BOTH the frictionless figures (`pnl`, `bps`) and the
    cost-adjusted ones (`pnl_net`, `bps_net`). Both are kept deliberately: the whole
    point of Goal A was that the difference between them was the entire reported
    profit, so a reporter that silently swapped one for the other would hide the
    finding instead of showing it.
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
             if (c.get("symbol") or c.get("_sym")) == sym
             and c.get("strategy") == strat
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

        # Net of transaction costs (docs/research-reset.md Goal A1).
        pnl_net = costs.net_pnl(pnl, sym, entry, qty) if pnl is not None else None
        bps_net = costs.net_bps(pnl, sym, entry, qty) if pnl is not None else None

        trades.append({
            "symbol": sym,
            "strategy": strat,
            "entry": entry,
            "stop": stop,
            "qty": qty,
            "direction": direction,
            "kdj_cross_age": o.get("kdj_cross_age"),
            "open_ts": o["ts"],
            "open_et": to_et(o["ts"]),
            "close_ts": match["ts"] if match else None,
            "close_et": to_et(match["ts"]) if match else None,
            "exit": match.get("exit") if match else None,
            "reason": match.get("reason") if match else None,
            "pnl": pnl,
            "pnl_net": pnl_net,
            "r_mult": r_mult,
            "bps": bps,
            "bps_net": bps_net,
            "hold_bars": match.get("hold_bars") if match else None,
            "closed": match is not None,
            "win": (match.get("pnl", 0) or 0) > 0 if match else None,
        })
    return trades


def load_jsonl(paths: list[Path]) -> list[dict]:
    """Read paper-runner JSONL files into a ts-sorted record list.

    Annotates each record with `_sym` from the filename — bar_eval events carry no
    symbol field of their own.
    """
    records: list[dict] = []
    for p in paths:
        m = _SYM_PATTERN.match(p.name)
        source_sym = m.group(1).replace("_", ".", 1) if m else ""
        try:
            with p.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                        r.setdefault("_sym", source_sym)
                        records.append(r)
                    except json.JSONDecodeError:
                        pass
        except OSError:
            continue
    return sorted(records, key=lambda r: r.get("ts", ""))


def load_trades(
    logs_dir: Path,
    start: str | None = None,
    default_start: str | None = LIVE_LOGS_START,
) -> list[dict]:
    """Load and pair every trade in `logs_dir`, optionally from `start` (YYYY-MM-DD).

    The convenience entry point for reporters that just want "the trades", without
    reimplementing the glob, the symbol annotation, or the pairing.

    `start=None` falls back to `default_start` (the pre-confirmed-fill cutoff). Pass
    `default_start=None` for replay output directories, which have no such era.
    """
    effective = start or default_start
    paths = []
    for p in sorted(logs_dir.glob("paper_*_????-??-??.jsonl")):
        m = _DATE_PATTERN.match(p.name)
        if not m:
            continue
        if effective and m.group(2) < effective:
            continue
        paths.append(p)
    return pair_trades(load_jsonl(paths))


def summarize_costs(trades: list[dict]) -> dict:
    """Gross-vs-net rollup over closed trades. Returns zeros/None on an empty set."""
    closed = [t for t in trades if t["closed"]]
    gross = [t["pnl"] for t in closed if t["pnl"] is not None]
    net = [t["pnl_net"] for t in closed if t["pnl_net"] is not None]
    bps = [t["bps"] for t in closed if t["bps"] is not None]
    bps_net = [t["bps_net"] for t in closed if t["bps_net"] is not None]
    wins = sum(1 for t in closed if t["pnl"] is not None and t["pnl"] > 0)
    return {
        "trades": len(closed),
        "wins": wins,
        "win_pct": round(wins / len(closed) * 100, 1) if closed else 0.0,
        "gross_pnl": round(sum(gross), 4) if gross else 0.0,
        "net_pnl": round(sum(net), 4) if net else 0.0,
        "gross_pf": profit_factor(gross) if gross else None,
        "net_pf": profit_factor(net) if net else None,
        "avg_bps": round(sum(bps) / len(bps), 2) if bps else None,
        "avg_bps_net": round(sum(bps_net) / len(bps_net), 2) if bps_net else None,
    }
