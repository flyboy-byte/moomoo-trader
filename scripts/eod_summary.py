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
        ct = self.closed_trades
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
            )

        elif etype == "position_close":
            sym = evt.get("symbol", sym)
            key = (sym, strat)
            tr = pending.pop(key, None)
            if tr:
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
                lines.append(
                    f"  {tr.symbol}  {entry_t}→{exit_t}  "
                    f"${tr.entry_price:.2f}→${tr.exit_price:.2f}  "
                    f"{pnl_t}  {icon}{tr.exit_reason}  {tr.hold_minutes}m"
                )

    if s.open_at_close:
        lines += ["", "Still open at end of session:"]
        for tr in s.open_at_close:
            entry_t = tr.entry_time[11:16] if tr.entry_time else "?"
            lines.append(
                f"  {tr.symbol}  entered {entry_t} @ ${tr.entry_price:.2f}  "
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
        return (
            f"**moomoo-trader EOD {date_str}** — no trades today  "
            f"({s.signal_skips} skipped, {s.risk_blocks} risk blocks)"
        )

    win_str = f"{s.wins}/{len(ct)}" if ct else "—"
    lines = [
        f"**moomoo-trader EOD {date_str}**",
        f"Trades: {len(ct)}  Win: {win_str}  P&L: **{pnl_str}**",
        f"Targets: {s.targets}  Stops: {s.stops}",
    ]
    for tr in ct:
        pnl_t = f"+${tr.pnl:.2f}" if tr.pnl >= 0 else f"-${abs(tr.pnl):.2f}"
        icon = "✅" if tr.exit_reason == "target" else "🛑"
        lines.append(f"  {icon} {tr.symbol} {pnl_t} ({tr.hold_minutes}m)")
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

    session_date = date.today()
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
