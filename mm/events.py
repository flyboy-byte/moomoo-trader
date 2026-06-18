"""Structured event logging and position state for the paper runner.

Contains:
- PaperEventLog  — writes JSONL events to logs/paper_SYMBOL_DATE.jsonl
- PaperPosition  — dataclass holding open position state
- Position file  — persist/restore (symbol, strategy) state across restarts
- ORB traded     — persist/restore one-trade-per-day enforcement across restarts
"""
import json
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import clock
from . import config as _config
from .logger import get_logger

log = get_logger("paper")


# ---------------------------------------------------------------------------
# Structured event log (JSONL, separate from backtest logs)
# ---------------------------------------------------------------------------

class PaperEventLog:
    """Appends structured JSON events to logs/paper_SYMBOL_YYYY-MM-DD.jsonl.

    Each event includes a strategy tag so multi-strategy runs are distinguishable.
    One file per symbol per day — all strategies for that symbol share the file.

    Bug fix 2026-06-18: filename date and event `ts` used to come from clock.now()
    (naive server-local time — UTC on the VPS, America/Denver locally), not ET.
    Same bug class as clock.today() (mm/clock.py): a VPS-recorded ORB entry at
    13:30 ET was logged as ts="...T17:30:02" with no timezone label, looking like
    an after-hours trade. Now uses clock.today()/clock.now_et() so `ts` matches
    candle_ts/eval_ts (already naive ET) and diagnose_logs.py's market-hours
    staleness check (which compares ts.hour against 9:30-16:00) is correct again.
    """

    def __init__(self, symbol: str) -> None:
        _config.cfg.logs_dir.mkdir(exist_ok=True)
        self._sym_safe = symbol.replace(".", "_")
        self._sym = symbol

    @property
    def _path(self) -> Path:
        date_str = clock.today().strftime("%Y-%m-%d")
        return _config.cfg.logs_dir / f"paper_{self._sym_safe}_{date_str}.jsonl"

    def _write(self, event: str, strategy: str = "", **fields) -> None:
        record = {"ts": clock.now_et().isoformat(timespec="seconds"), "event": event,
                  "strategy": strategy, **fields}
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            print(f"[JSONL WRITE FAIL] {json.dumps(record)} err={e}", file=sys.stderr)

    def bar_eval(self, candle_ts, eval_ts: datetime, accepted: bool, close: float,
                 score: int, bonus: int, signals: dict, strategy: str = "",
                 regime_label: str = "") -> None:
        age_s = int((eval_ts - pd.Timestamp(candle_ts)).total_seconds())
        self._write("bar_eval", strategy=strategy, candle_ts=str(candle_ts),
                    eval_ts=eval_ts.isoformat(), candle_age_s=age_s, accepted=accepted,
                    close=round(close, 4), signal_score=score, bonus_score=bonus,
                    regime_label=regime_label, signals=signals)

    def signal_skip(self, reason: str, score: int, bonus: int, min_score: int,
                    strategy: str = "") -> None:
        self._write("signal_skip", strategy=strategy, reason=reason, score=score,
                    bonus_score=bonus, min_score=min_score)

    def risk_block(self, reason: str, strategy: str = "", **details) -> None:
        self._write("risk_block", strategy=strategy, reason=reason, **details)

    def order_attempt(self, side: str, qty: int, price: float, strategy: str = "") -> None:
        self._write("order_attempt", strategy=strategy, side=side, symbol=self._sym,
                    qty=qty, price=round(price, 4))

    def order_result(self, side: str, success: bool, order_id: str = "",
                     error: str = "", strategy: str = "") -> None:
        self._write("order_result", strategy=strategy, side=side, success=success,
                    order_id=order_id, error=error)

    def position_open(self, entry: float, stop: float, qty: int | float,
                      strategy: str = "", direction: str = "long",
                      intended_price: float = 0.0, **extra) -> None:
        intended = intended_price if intended_price > 0 else entry
        slippage_bps = round((entry - intended) / intended * 10000, 1)
        self._write("position_open", strategy=strategy, symbol=self._sym,
                    entry=round(entry, 4), stop=round(stop, 4),
                    qty=round(qty, 6) if isinstance(qty, float) else qty,
                    direction=direction, slippage_bps=slippage_bps, vix_at_entry=None,
                    **extra)

    def position_close(self, exit_price: float, reason: str, pnl: float,
                       hold_bars: int = 0, strategy: str = "",
                       direction: str = "long", intended_price: float = 0.0,
                       **extra) -> None:
        intended = intended_price if intended_price > 0 else exit_price
        slippage_bps = round((exit_price - intended) / intended * 10000, 1)
        self._write("position_close", strategy=strategy, symbol=self._sym,
                    exit=round(exit_price, 4), reason=reason, pnl=round(pnl, 4),
                    hold_bars=hold_bars, direction=direction, slippage_bps=slippage_bps,
                    **extra)

    def error(self, message: str, strategy: str = "") -> None:
        self._write("error", strategy=strategy, message=message)

    def info(self, message: str, strategy: str = "") -> None:
        self._write("info", strategy=strategy, message=message)


# ---------------------------------------------------------------------------
# Position state
# ---------------------------------------------------------------------------

@dataclass
class PaperPosition:
    symbol: str
    strategy: str
    entry_time: datetime
    entry_price: float
    stop_price: float
    qty: int | float
    order_id: str = ""
    target_price: float = 0.0  # fixed target for ORB; 0 = not used (bb_kdj/vwap use dynamic targets)
    direction: str = "long"    # "long" or "short"


# ---------------------------------------------------------------------------
# Position state persistence — keyed by (symbol, strategy)
# ---------------------------------------------------------------------------

def _position_file(symbol: str, strategy: str) -> Path:
    sym_safe = symbol.replace(".", "_")
    return _config.cfg.logs_dir / f"paper_{sym_safe}_{strategy}_position.json"


def _save_position(pos: PaperPosition) -> None:
    d = asdict(pos)
    d["entry_time"] = str(pos.entry_time)
    path = _position_file(pos.symbol, pos.strategy)
    path.write_text(json.dumps(d))
    path.chmod(0o600)
    log.info("Position state saved: %s/%s", pos.symbol, pos.strategy)


def _load_position(symbol: str, strategy: str) -> PaperPosition | None:
    path = _position_file(symbol, strategy)
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text())
        pos = PaperPosition(
            symbol=d["symbol"],
            strategy=d.get("strategy", strategy),
            entry_time=datetime.fromisoformat(d["entry_time"]),
            entry_price=d["entry_price"],
            stop_price=d["stop_price"],
            qty=d["qty"],
            order_id=d.get("order_id", ""),
            target_price=d.get("target_price", 0.0),
            direction=d.get("direction", "long"),
        )
        log.warning("Recovered open position [%s/%s]: entry=%.4f stop=%.4f qty=%s dir=%s",
                    symbol, strategy, pos.entry_price, pos.stop_price, pos.qty, pos.direction)
        return pos
    except Exception as e:
        log.error("Failed to load position state [%s/%s]: %s — starting fresh",
                  symbol, strategy, e)
        return None


def _clear_position(symbol: str, strategy: str) -> None:
    path = _position_file(symbol, strategy)
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# ORB one-trade-per-day persistence
# ---------------------------------------------------------------------------

def _orb_traded_file(symbol: str) -> Path:
    return _config.cfg.logs_dir / f"paper_{symbol.replace('.', '_')}_orb_traded.json"


def _load_orb_traded(symbols: list[str]) -> dict[str, date]:
    """Load the last ORB entry date per symbol. Used to enforce one trade per day on restart."""
    result: dict[str, date] = {}
    for sym in symbols:
        path = _orb_traded_file(sym)
        if path.exists():
            try:
                d = json.loads(path.read_text())
                result[sym] = date.fromisoformat(d["date"])
            except Exception:
                pass
    return result


def _save_orb_traded(symbol: str, traded_date: date) -> None:
    _orb_traded_file(symbol).write_text(json.dumps({"date": str(traded_date)}))
