#!/usr/bin/env python3
"""Live terminal dashboard for moomoo-trader paper sessions.

Reads today's JSONL event logs and position JSON files from logs/.
No OpenD connection needed — pure file-based.

Usage:
    python scripts/dashboard.py
    python scripts/dashboard.py --date 2026-06-01   # review a past session
"""
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.config import cfg

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import (
    DataTable, Footer, Header, Label,
    RichLog, Static, TabbedContent, TabPane,
)

PROJECT_ROOT = Path(__file__).parent.parent
ET = ZoneInfo("America/New_York")
REFRESH_SECS = 5

# ---------------------------------------------------------------------------
# Data model
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
    direction: str = "long"

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
class SessionState:
    session_date: date
    updated_at: datetime
    kill_switch: bool
    jsonl_files: list[Path]
    open_positions: dict[str, dict]   # symbol -> position dict
    trades: list[TradeRecord]
    signal_events: list[dict]
    raw_events: list[dict]

    @property
    def realized_pnl(self) -> float:
        return sum(t.pnl for t in self.trades if t.closed)

    @property
    def daily_loss(self) -> float:
        return sum(-t.pnl for t in self.trades if t.closed and t.pnl < 0)

    @property
    def closed_trades(self) -> list[TradeRecord]:
        return [t for t in self.trades if t.closed]

    @property
    def win_rate_str(self) -> str:
        ct = self.closed_trades
        if not ct:
            return "—"
        wins = sum(1 for t in ct if t.pnl > 0)
        return f"{wins}/{len(ct)} ({100 * wins // len(ct)}%)"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _infer_symbol(path: Path, date_str: str) -> str:
    """'paper_US_SPY_2026-06-01.jsonl' -> 'US.SPY'"""
    name = path.stem.removeprefix("paper_").removesuffix(f"_{date_str}")
    return name.replace("_", ".", 1)


def _market_status() -> str:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return "CLOSED (weekend)"
    h, m = now.hour, now.minute
    if (9, 30) <= (h, m) < (16, 0):
        return "[bold green]OPEN[/]"
    if (h, m) < (9, 30):
        return "pre-market"
    return "after hours"


def load_state(session_date: date) -> SessionState:
    date_str = session_date.strftime("%Y-%m-%d")

    jsonl_files: list[Path] = []
    if cfg.logs_dir.exists():
        jsonl_files = sorted(cfg.logs_dir.glob(f"paper_US_*_{date_str}.jsonl"))

    all_events: list[dict] = []
    for f in jsonl_files:
        symbol = _infer_symbol(f, date_str)
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

    # Reconstruct trade pairs from events
    pending: dict[str, TradeRecord] = {}
    trades: list[TradeRecord] = []
    last_bonus: dict[str, int] = {}

    for evt in all_events:
        etype = evt.get("event", "")
        sym = evt.get("symbol") or evt.get("_symbol", "")

        if etype == "bar_eval":
            last_bonus[sym] = evt.get("bonus_score", 0)

        elif etype == "position_open":
            sym = evt.get("symbol", sym)
            pending[sym] = TradeRecord(
                symbol=sym,
                entry_time=evt.get("ts", ""),
                entry_price=evt.get("entry", 0.0),
                stop_price=evt.get("stop", 0.0),
                qty=evt.get("qty", 0),
                bonus=last_bonus.get(sym, 0),
                direction=evt.get("direction", "long"),
            )

        elif etype == "position_close":
            sym = evt.get("symbol", sym)
            tr = pending.pop(sym, None)
            if tr:
                tr.exit_time = evt.get("ts", "")
                tr.exit_price = evt.get("exit", 0.0)
                tr.exit_reason = evt.get("reason", "")
                tr.pnl = evt.get("pnl", 0.0)
                trades.append(tr)

    # Positions still open at end of events (no close seen yet)
    for tr in pending.values():
        trades.append(tr)

    # Notable signal events for Signals tab
    notable = {"signal_skip", "risk_block", "position_open", "position_close"}
    signal_events = [
        e for e in all_events
        if e.get("event") in notable
        or (e.get("event") == "bar_eval"
            and e.get("accepted", False)
            and e.get("bonus_score", 0) >= 1)
    ]

    # Open positions from persisted JSON files (authoritative source)
    open_positions: dict[str, dict] = {}
    if cfg.logs_dir.exists():
        for pf in cfg.logs_dir.glob("paper_US_*_position.json"):
            try:
                pos = json.loads(pf.read_text())
                sym = pos.get("symbol", "")
                if sym:
                    open_positions[sym] = pos
            except (json.JSONDecodeError, OSError):
                pass

    return SessionState(
        session_date=session_date,
        updated_at=datetime.now(),
        kill_switch=(PROJECT_ROOT / "STOP_TRADING.txt").exists(),
        jsonl_files=jsonl_files,
        open_positions=open_positions,
        trades=sorted(trades, key=lambda t: t.entry_time, reverse=True),
        signal_events=signal_events,
        raw_events=all_events,
    )


# ---------------------------------------------------------------------------
# Textual app
# ---------------------------------------------------------------------------

class MoomooDashboard(App):
    TITLE = "moomoo-trader"
    CSS = """
    Screen { background: $surface; }

    #status_bar {
        height: 3;
        padding: 0 2;
        content-align: left middle;
        background: $boost;
        border-bottom: solid $primary;
    }

    #section_label {
        color: $text-muted;
        text-style: bold;
        padding: 1 1 0 1;
    }

    .bottom_row {
        height: auto;
        margin-top: 1;
    }

    #stats_panel {
        width: 1fr;
        padding: 1 2;
        border: solid $panel;
        margin-right: 1;
    }

    #config_panel {
        width: 1fr;
        padding: 1 2;
        border: solid $panel;
    }

    #trades_summary {
        height: 3;
        padding: 0 2;
        content-align: left middle;
        background: $boost;
        border-top: solid $primary;
    }

    DataTable { height: auto; }

    RichLog {
        height: 1fr;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh now"),
    ]

    def __init__(self, session_date: date) -> None:
        super().__init__()
        self.session_date = session_date
        self._log_cursor = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent():
            with TabPane("Overview", id="tab_overview"):
                yield Static("", id="status_bar")
                yield Label("  OPEN POSITIONS", id="section_label")
                yield DataTable(id="pos_table", cursor_type="none")
                with Horizontal(classes="bottom_row"):
                    yield Static("", id="stats_panel")
                    yield Static("", id="config_panel")
            with TabPane("Trades", id="tab_trades"):
                yield DataTable(id="trades_table")
                yield Static("", id="trades_summary")
            with TabPane("Signals", id="tab_signals"):
                yield DataTable(id="signals_table")
            with TabPane("Log", id="tab_log"):
                yield RichLog(id="event_log", markup=True, auto_scroll=True)
        yield Footer()

    def on_mount(self) -> None:
        self._setup_tables()
        self._do_refresh()
        self.set_interval(REFRESH_SECS, self._do_refresh)

    def _setup_tables(self) -> None:
        pos = self.query_one("#pos_table", DataTable)
        pos.add_columns("Symbol", "Qty", "Entry $", "Stop $", "Entered", "Bonus")

        tr = self.query_one("#trades_table", DataTable)
        tr.add_columns("Entered", "Symbol", "Qty", "Entry $", "Exit $", "P&L", "Type", "Hold", "Bonus")

        sig = self.query_one("#signals_table", DataTable)
        sig.add_columns("Time", "Symbol", "Event", "Close $", "Score", "Bonus", "Detail")

    def action_refresh(self) -> None:
        self._do_refresh()

    def _do_refresh(self) -> None:
        s = load_state(self.session_date)
        self._update_overview(s)
        self._update_trades(s)
        self._update_signals(s)
        self._append_log(s)

    # ---- Overview tab -------------------------------------------------------

    def _update_overview(self, s: SessionState) -> None:
        ks = ("[bold red]ON — TRADING PAUSED[/]" if s.kill_switch
              else "[bold green]OFF[/]")
        mkt = _market_status()
        files = (", ".join(f.stem for f in s.jsonl_files)
                 if s.jsonl_files else "no session files for today")
        ts = s.updated_at.strftime("%H:%M:%S")
        self.query_one("#status_bar", Static).update(
            f"Kill switch: {ks}   Market: {mkt}   {files}   [dim]updated {ts}[/]"
        )

        # Positions: one row per configured symbol
        tbl = self.query_one("#pos_table", DataTable)
        tbl.clear()
        for sym in cfg.symbols:
            pos = s.open_positions.get(sym)
            if pos:
                et = ""
                if pos.get("entry_time"):
                    try:
                        et = datetime.fromisoformat(str(pos["entry_time"])).strftime("%H:%M")
                    except ValueError:
                        et = str(pos.get("entry_time", ""))[:16]
                is_short = pos.get("direction", "long") == "short"
                sym_label = Text(f"{sym} {'▼SHORT' if is_short else '▲LONG'}",
                                 style="bold red" if is_short else "bold green")
                tbl.add_row(
                    sym_label,
                    str(pos.get("qty", 0)),
                    f"${pos.get('entry_price', 0):.2f}",
                    f"${pos.get('stop_price', 0):.2f}",
                    et,
                    "—",
                )
            else:
                tbl.add_row(Text(sym, style="dim"), "—", Text("flat", style="dim"),
                            "—", "—", "—")

        # Stats
        ct = s.closed_trades
        pnl = s.realized_pnl
        pnl_c = "green" if pnl >= 0 else "red"
        loss_pct = min(s.daily_loss / cfg.max_daily_loss, 1.0) if cfg.max_daily_loss else 0
        filled = int(loss_pct * 10)
        loss_bar = f"[red]{'█' * filled}[/][dim]{'░' * (10 - filled)}[/]"
        self.query_one("#stats_panel", Static).update(
            f"[bold]TODAY[/]\n\n"
            f"Trades:     {len(ct)} / {cfg.max_trades_per_day}\n"
            f"Realized:   [{pnl_c}]${pnl:+.2f}[/]\n"
            f"Daily loss: ${s.daily_loss:.2f} / ${cfg.max_daily_loss:.2f}  {loss_bar}\n"
            f"Win rate:   {s.win_rate_str}"
        )

        syms = ", ".join(cfg.symbols)
        self.query_one("#config_panel", Static).update(
            f"[bold]CONFIG[/]\n\n"
            f"Symbols:  {syms}\n"
            f"Score ≥:  {cfg.min_signal_score}\n"
            f"ATR mult: {cfg.atr_stop_mult}×\n"
            f"Cap:      ${cfg.max_position_dollars:.0f}\n"
            f"KType:    {cfg.candle_ktype}"
        )

    # ---- Trades tab ---------------------------------------------------------

    def _update_trades(self, s: SessionState) -> None:
        tbl = self.query_one("#trades_table", DataTable)
        tbl.clear()

        for tr in s.trades:
            pnl_cell = (
                Text(f"+${tr.pnl:.2f}", style="bold green") if tr.pnl > 0
                else Text(f"-${abs(tr.pnl):.2f}", style="bold red") if tr.pnl < 0
                else Text("open", style="dim yellow")
            )
            exit_str = f"${tr.exit_price:.2f}" if tr.exit_price else "—"
            hold = f"{tr.hold_minutes}m" if tr.hold_minutes else "—"
            type_cell = (
                Text("✓ target", style="green") if tr.exit_reason == "target"
                else Text("✗ stop", style="red") if tr.exit_reason == "stop"
                else Text("open", style="dim yellow") if not tr.exit_reason
                else Text(tr.exit_reason, style="dim")
            )
            entered = tr.entry_time[11:16] if tr.entry_time else "?"
            is_short = tr.direction == "short"
            sym_cell = Text(f"{tr.symbol} {'▼S' if is_short else ''}",
                            style="red" if is_short else "")
            tbl.add_row(
                entered, sym_cell, str(tr.qty),
                f"${tr.entry_price:.2f}", exit_str,
                pnl_cell, type_cell, hold, str(tr.bonus),
            )

        ct = s.closed_trades
        pnl = s.realized_pnl
        pnl_c = "green" if pnl >= 0 else "red"
        self.query_one("#trades_summary", Static).update(
            f"Realized P&L: [{pnl_c}]${pnl:+.2f}[/]   "
            f"Win rate: {s.win_rate_str}   "
            f"Closed: {len(ct)}"
        )

    # ---- Signals tab --------------------------------------------------------

    def _update_signals(self, s: SessionState) -> None:
        tbl = self.query_one("#signals_table", DataTable)
        tbl.clear()

        for evt in reversed(s.signal_events[-300:]):
            ts = (evt.get("ts") or "")[:16].replace("T", " ")
            sym = evt.get("symbol") or evt.get("_symbol", "")
            etype = evt.get("event", "")
            close_str = f"${evt.get('close', 0):.2f}" if evt.get("close") else "—"
            score_str = str(evt.get("signal_score", "—"))
            bonus_str = str(evt.get("bonus_score", "—"))

            if etype == "position_open":
                ev_cell = Text("▲ ENTRY", style="bold green")
                detail = (f"qty={evt.get('qty', '?')}  "
                          f"stop=${evt.get('stop', 0):.2f}")
            elif etype == "position_close":
                reason = evt.get("reason", "")
                pnl_v = evt.get("pnl", 0)
                ev_cell = (Text("▼ EXIT target", style="bold green")
                           if reason == "target"
                           else Text("▼ EXIT stop", style="bold red"))
                detail = f"pnl={pnl_v:+.2f}  exit=${evt.get('exit', 0):.2f}"
            elif etype == "risk_block":
                ev_cell = Text("⚠ RISK BLOCK", style="yellow")
                detail = evt.get("reason", "")
            elif etype == "signal_skip":
                ev_cell = Text("⊘ skip", style="dim")
                detail = (f"score {evt.get('score', '?')} "
                          f"< {evt.get('min_score', '?')}")
            elif etype == "bar_eval":
                ev_cell = Text("◉ signal", style="cyan")
                sigs = evt.get("signals", {})
                detail = " + ".join(
                    k.replace("sig_", "") for k, v in sigs.items() if v
                )
            else:
                ev_cell = Text(etype, style="dim")
                detail = ""

            tbl.add_row(ts, sym, ev_cell, close_str, score_str, bonus_str, detail)

    # ---- Log tab (append-only) ----------------------------------------------

    def _append_log(self, s: SessionState) -> None:
        log_widget = self.query_one("#event_log", RichLog)
        new_events = s.raw_events[self._log_cursor:]
        if not new_events:
            return

        colors = {
            "position_open": "bold green",
            "position_close": "green",
            "risk_block": "yellow",
            "signal_skip": "dim",
            "order_attempt": "cyan",
            "order_result": "cyan",
            "error": "bold red",
            "info": "blue",
            "bar_eval": "dim",
        }

        for evt in new_events:
            etype = evt.get("event", "unknown")
            ts = (evt.get("ts") or "")[:19].replace("T", " ")
            sym = evt.get("_symbol", "")
            color = colors.get(etype, "white")
            if etype == "position_close":
                color = "bold green" if evt.get("reason") == "target" else "bold red"

            fields = {
                k: v for k, v in evt.items()
                if not k.startswith("_") and k not in ("ts", "event", "symbol")
                and k != "signals"  # too noisy; signals sub-dict shown inline below
            }
            # Inline signal flags from bar_eval
            sigs = evt.get("signals", {})
            if sigs:
                fields["signals"] = "+".join(k.replace("sig_", "") for k, v in sigs.items() if v) or "none"

            fields_str = "  ".join(f"[dim]{k}=[/]{v}" for k, v in fields.items())
            log_widget.write(
                f"[dim]{ts}[/]  [{color}]{etype:<18}[/]  "
                f"[dim cyan]{sym:<8}[/]  {fields_str}"
            )

        self._log_cursor = len(s.raw_events)


# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="moomoo-trader live dashboard")
    parser.add_argument("--date", help="Session date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    session_date = date.today()
    if args.date:
        session_date = date.fromisoformat(args.date)

    MoomooDashboard(session_date=session_date).run()


if __name__ == "__main__":
    main()
