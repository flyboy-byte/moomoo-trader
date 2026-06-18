#!/usr/bin/env python3
"""End-of-day summary for a paper trading session.

Reads today's JSONL event logs, reconstructs the session, and prints a
formatted recap. Optionally posts to Discord.

Usage:
    python scripts/eod_summary.py
    python scripts/eod_summary.py --date 2026-06-02
    python scripts/eod_summary.py --post-discord
"""
import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm import clock
from mm.config import cfg
from mm.notifications import notify


# ---------------------------------------------------------------------------
# Data model (mirrors dashboard.py logic)
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    symbol: str
    entry_time: str
    entry_price: float
    stop_price: float
    qty: int
    bonus: int = 0
    exit_time: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    entry_slippage_bps: float = 0.0
    exit_slippage_bps: float = 0.0
    strategy: str = ""
    direction: str = "long"
    orphaned: bool = False  # position_close with no matching position_open in this day's window

    @property
    def hold_minutes(self) -> int:
        if not self.exit_time or not self.entry_time:
            return 0
        try:
            t0 = datetime.fromisoformat(self.entry_time)
            t1 = datetime.fromisoformat(self.exit_time)
            return int((t1 - t0).total_seconds() / 60)
        except ValueError:
            return 0

    @property
    def closed(self) -> bool:
        return bool(self.exit_time)


@dataclass
class SessionSummary:
    session_date: date
    symbols: list[str]
    trades: list[TradeRecord]
    risk_blocks: int = 0
    signal_skips: int = 0
    bar_evals: int = 0
    errors: int = 0
    open_at_close: list[TradeRecord] = field(default_factory=list)

    @property
    def closed_trades(self) -> list[TradeRecord]:
        return [t for t in self.trades if t.closed]

    @property
    def realized_pnl(self) -> float:
        return sum(t.pnl for t in self.closed_trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.closed_trades if t.pnl > 0)

    @property
    def losses(self) -> int:
        return sum(1 for t in self.closed_trades if t.pnl <= 0)

    @property
    def targets(self) -> int:
        return sum(1 for t in self.closed_trades if t.exit_reason == "target")

    @property
    def stops(self) -> int:
        return sum(1 for t in self.closed_trades if t.exit_reason == "stop")

    @property
    def avg_hold_minutes(self) -> float:
        # Excludes orphaned trades (bug fix 2026-06-18): their entry_time is
        # unknown, so hold_minutes is hardcoded to 0 — including them here
        # would silently understate the average with a fake zero, not a real one.
        ct = [t for t in self.closed_trades if not t.orphaned]
        if not ct:
            return 0.0
        return sum(t.hold_minutes for t in ct) / len(ct)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _infer_symbol(path: Path, date_str: str) -> str:
    name = path.stem.removeprefix("paper_").removesuffix(f"_{date_str}")
    return name.replace("_", ".", 1)


def load_summary(session_date: date) -> SessionSummary:
    date_str = session_date.strftime("%Y-%m-%d")
    jsonl_files: list[Path] = []
    if cfg.logs_dir.exists():
        jsonl_files = sorted(cfg.logs_dir.glob(f"paper_US_*_{date_str}.jsonl"))

    all_events: list[dict] = []
    symbols_seen: list[str] = []

    for f in jsonl_files:
        symbol = _infer_symbol(f, date_str)
        if symbol not in symbols_seen:
            symbols_seen.append(symbol)
        try:
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    evt = json.loads(line)
                    evt.setdefault("symbol", symbol)
                    evt["_symbol"] = symbol
                    all_events.append(evt)
                except json.JSONDecodeError:
                    pass
        except OSError:
            pass

    all_events.sort(key=lambda e: e.get("ts", ""))

    pending: dict[tuple[str, str], TradeRecord] = {}
    trades: list[TradeRecord] = []
    last_bonus: dict[str, int] = {}
    risk_blocks = 0
    signal_skips = 0
    bar_evals = 0
    errors = 0

    for evt in all_events:
        etype = evt.get("event", "")
        sym = evt.get("symbol") or evt.get("_symbol", "")
        strat = evt.get("strategy", "")

        if etype == "bar_eval":
            bar_evals += 1
            last_bonus[sym] = evt.get("bonus_score", 0)

        elif etype == "risk_block":
            risk_blocks += 1

        elif etype == "signal_skip":
            signal_skips += 1

        elif etype == "error":
            errors += 1

        elif etype == "position_open":
            sym = evt.get("symbol", sym)
            key = (sym, strat)
            pending[key] = TradeRecord(
                symbol=sym,
                entry_time=evt.get("ts", ""),
                entry_price=evt.get("entry", 0.0),
                stop_price=evt.get("stop", 0.0),
                qty=evt.get("qty", 0),
                bonus=last_bonus.get(sym, 0),
                entry_slippage_bps=evt.get("slippage_bps", 0.0),
                strategy=strat,
                direction=evt.get("direction", "long"),
            )

        elif etype == "position_close":
            sym = evt.get("symbol", sym)
            key = (sym, strat)
            tr = pending.pop(key, None)
            if tr is None:
                # Bug fix 2026-06-18: this used to be silently dropped — the real,
                # already-executed PnL from this exit was excluded from
                # realized_pnl entirely, not just hidden from display. Happens
                # when a position_open lands in a PREVIOUS day's JSONL file (e.g.
                # a stuck exit_unfilled retry that finally fills after midnight).
                # Entry fields are unknown here (that event is in a different
                # day's file) — mark it clearly rather than guessing.
                tr = TradeRecord(
                    symbol=sym, entry_time="", entry_price=0.0, stop_price=0.0,
                    qty=0, strategy=strat,
                    direction=evt.get("direction", "long"), orphaned=True,
                )
            tr.exit_time = evt.get("ts", "")
            tr.exit_price = evt.get("exit", 0.0)
            tr.exit_reason = evt.get("reason", "")
            tr.pnl = evt.get("pnl", 0.0)
            tr.exit_slippage_bps = evt.get("slippage_bps", 0.0)
            trades.append(tr)

    open_at_close = list(pending.values())

    return SessionSummary(
        session_date=session_date,
        symbols=symbols_seen,
        trades=trades,
        risk_blocks=risk_blocks,
        signal_skips=signal_skips,
        bar_evals=bar_evals,
        errors=errors,
        open_at_close=open_at_close,
    )


# ---------------------------------------------------------------------------
# VIX shadow log (display-time join only — never touches live trading code).
# See scripts/fetch_vix_morning.py. Easy to delete: remove this function, its
# two call sites below, and logs/vix_daily.jsonl. Nothing else depends on it.
# ---------------------------------------------------------------------------

def _load_vix_shadow(session_date: date) -> dict | None:
    """No write-side dedup in fetch_vix_morning.py — running it twice in one day
    appends two lines for the same date. Take the LAST match (most recent run),
    not the first, so a re-run with corrected/updated data wins."""
    path = cfg.logs_dir / "vix_daily.jsonl"
    if not path.exists():
        return None
    date_str = session_date.strftime("%Y-%m-%d")
    found: dict | None = None
    try:
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("date") == date_str:
                found = rec
    except OSError:
        return None
    return found


def _vix_shadow_line(s: SessionSummary) -> str | None:
    rec = _load_vix_shadow(s.session_date)
    if rec is None:
        return None
    blocks = ", ".join(
        f">={k.rsplit('_', 1)[1]}:{'BLOCK' if v else 'ok'}"
        for k, v in rec.items() if k.startswith("would_block_")
    )
    return f"VIX shadow (not live — observational): prev_close={rec.get('vix_prev_close')}  {blocks}"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_summary(s: SessionSummary) -> str:
    date_str = s.session_date.strftime("%Y-%m-%d (%A)")
    syms = ", ".join(s.symbols) if s.symbols else "none"
    ct = s.closed_trades
    pnl = s.realized_pnl
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"

    lines = [
        f"=== moomoo-trader EOD Summary  {date_str} ===",
        f"Symbols:       {syms}",
        f"Bars evaluated:{s.bar_evals}",
        "",
    ]
    vix_line = _vix_shadow_line(s)
    if vix_line:
        lines += [vix_line, ""]

    if not ct and not s.open_at_close:
        lines += [
            "No trades today.",
            f"  Signals skipped (score < {cfg.min_signal_score}): {s.signal_skips}",
            f"  Risk blocks:   {s.risk_blocks}",
        ]
    else:
        lines += [
            f"Closed trades: {len(ct)}   (wins: {s.wins}  losses: {s.losses})",
            f"  Targets hit: {s.targets}   Stops hit: {s.stops}",
            f"  Realized P&L: {pnl_str}",
        ]
        if ct:
            lines.append(f"  Avg hold:    {s.avg_hold_minutes:.0f} min")
        lines += [
            "",
            f"Signal activity:",
            f"  Skipped (score < {cfg.min_signal_score}): {s.signal_skips}",
            f"  Risk blocks:   {s.risk_blocks}",
        ]

        if ct:
            lines += ["", "Trade detail:"]
            for tr in ct:
                entry_t = tr.entry_time[11:16] if tr.entry_time else "?"
                exit_t = tr.exit_time[11:16] if tr.exit_time else "?"
                pnl_t = f"+${tr.pnl:.2f}" if tr.pnl >= 0 else f"-${abs(tr.pnl):.2f}"
                icon = "✓" if tr.exit_reason == "target" else "✗"
                dir_tag = "[SHORT]" if tr.direction == "short" else "[LONG] "
                orphan_tag = " [ORPHANED — entry was in a previous day's log]" if tr.orphaned else ""
                lines.append(
                    f"  {dir_tag} {tr.symbol}  {entry_t}→{exit_t}  "
                    f"${tr.entry_price:.2f}→${tr.exit_price:.2f}  "
                    f"{pnl_t}  {icon}{tr.exit_reason}  {tr.hold_minutes}m{orphan_tag}"
                )

    if s.open_at_close:
        lines += ["", "Still open at end of session:"]
        for tr in s.open_at_close:
            entry_t = tr.entry_time[11:16] if tr.entry_time else "?"
            dir_tag = "[SHORT]" if tr.direction == "short" else "[LONG] "
            lines.append(
                f"  {dir_tag} {tr.symbol}  entered {entry_t} @ ${tr.entry_price:.2f}  "
                f"stop=${tr.stop_price:.2f}  qty={tr.qty}"
            )

    if s.errors:
        lines += ["", f"Errors logged: {s.errors}  (check journalctl)"]

    lines.append("")
    return "\n".join(lines)


def format_discord(s: SessionSummary) -> str:
    ct = s.closed_trades
    pnl = s.realized_pnl
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    date_str = s.session_date.strftime("%Y-%m-%d")

    if not ct and not s.open_at_close:
        msg = (
            f"**moomoo-trader EOD {date_str}** — no trades today  "
            f"({s.signal_skips} skipped, {s.risk_blocks} risk blocks)"
        )
        vix_line = _vix_shadow_line(s)
        return f"{msg}\n  _{vix_line}_" if vix_line else msg

    win_str = f"{s.wins}/{len(ct)}" if ct else "—"
    lines = [
        f"**moomoo-trader EOD {date_str}**",
        f"Trades: {len(ct)}  Win: {win_str}  P&L: **{pnl_str}**",
        f"Targets: {s.targets}  Stops: {s.stops}",
    ]
    vix_line = _vix_shadow_line(s)
    if vix_line:
        lines.append(f"  _{vix_line}_")
    for tr in ct:
        pnl_t = f"+${tr.pnl:.2f}" if tr.pnl >= 0 else f"-${abs(tr.pnl):.2f}"
        icon = "✅" if tr.exit_reason == "target" else "🛑"
        dir_tag = " (short)" if tr.direction == "short" else ""
        orphan_tag = " ⚠️orphaned-entry" if tr.orphaned else ""
        lines.append(f"  {icon} {tr.symbol}{dir_tag} {pnl_t} ({tr.hold_minutes}m){orphan_tag}")
    if s.open_at_close:
        lines.append(f"  ⏳ {len(s.open_at_close)} position(s) still open")

    return "\n".join(lines)


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="moomoo-trader end-of-day summary")
    parser.add_argument("--date", help="Session date YYYY-MM-DD (default: today)")
    parser.add_argument("--post-discord", action="store_true",
                        help="Post summary to Discord webhook (requires DISCORD_WEBHOOK_URL in .env)")
    args = parser.parse_args()

    session_date = clock.today()  # ET trading-day date, not local system date
    if args.date:
        session_date = date.fromisoformat(args.date)

    s = load_summary(session_date)

    print(format_summary(s))

    if args.post_discord:
        if not cfg.discord_webhook_url:
            print("No DISCORD_WEBHOOK_URL set in .env — skipping Discord post.")
        else:
            notify(format_discord(s))
            print("Posted to Discord.")


if __name__ == "__main__":
    main()
