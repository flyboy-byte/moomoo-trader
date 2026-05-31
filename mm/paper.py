"""
Paper-trading loop.

Polls OpenD every 60 seconds, evaluates the last N closed 5-min candles through
the full signal engine, and places simulated orders via OpenSecTradeContext.

Kill switch: create STOP_TRADING.txt in the project root to pause without killing
the process. Remove the file to resume.

Structured event log: every signal check, risk block, order attempt, fill, and exit
is written to logs/paper_YYYY-MM-DD.jsonl. Separate from backtest logs.
"""
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from moomoo import (
    OpenSecTradeContext,
    RET_OK,
    TrdEnv,
    TrdMarket,
    TrdSide,
    OrderType,
)

from .config import cfg
from .data import fetch_candles
from .notifications import notify, notify_entry, notify_exit
from .risk import trading_allowed, calc_qty, DailyTracker
from .signals import snapshot as signal_snapshot
from .strategy import compute_signals
from .logger import get_logger

log = get_logger("paper")

POLL_SECONDS = 60
CANDLE_LOOKBACK_DAYS = 3
MAX_CONSECUTIVE_ERRORS = 3
BACKOFF_SECONDS = 300  # 5 min after repeated failures


# ---------------------------------------------------------------------------
# Structured event log (JSONL, separate from backtest logs)
# ---------------------------------------------------------------------------

class PaperEventLog:
    """Appends structured JSON events to logs/paper_YYYY-MM-DD.jsonl."""

    def __init__(self, symbol: str) -> None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        sym_safe = symbol.replace(".", "_")
        path = cfg.logs_dir / f"paper_{sym_safe}_{date_str}.jsonl"
        cfg.logs_dir.mkdir(exist_ok=True)
        self._path = path
        self._sym = symbol

    def _write(self, event: str, **fields) -> None:
        record = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event, **fields}
        with open(self._path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def bar_eval(self, candle_ts, eval_ts: datetime, accepted: bool, close: float,
                 score: int, bonus: int, signals: dict) -> None:
        age_s = int((eval_ts - pd.Timestamp(candle_ts)).total_seconds())
        self._write("bar_eval", candle_ts=str(candle_ts), eval_ts=eval_ts.isoformat(),
                    candle_age_s=age_s, accepted=accepted, close=round(close, 4),
                    signal_score=score, bonus_score=bonus, signals=signals)

    def signal_skip(self, reason: str, score: int, bonus: int, min_score: int) -> None:
        self._write("signal_skip", reason=reason, score=score,
                    bonus_score=bonus, min_score=min_score)

    def risk_block(self, reason: str, **details) -> None:
        self._write("risk_block", reason=reason, **details)

    def order_attempt(self, side: str, qty: int, price: float) -> None:
        self._write("order_attempt", side=side, symbol=self._sym,
                    qty=qty, price=round(price, 4))

    def order_result(self, side: str, success: bool, order_id: str = "", error: str = "") -> None:
        self._write("order_result", side=side, success=success,
                    order_id=order_id, error=error)

    def position_open(self, entry: float, stop: float, qty: int) -> None:
        self._write("position_open", symbol=self._sym,
                    entry=round(entry, 4), stop=round(stop, 4), qty=qty)

    def position_close(self, exit_price: float, reason: str, pnl: float) -> None:
        self._write("position_close", symbol=self._sym,
                    exit=round(exit_price, 4), reason=reason, pnl=round(pnl, 4))

    def error(self, message: str) -> None:
        self._write("error", message=message)

    def info(self, message: str) -> None:
        self._write("info", message=message)


# ---------------------------------------------------------------------------
# Position state
# ---------------------------------------------------------------------------

@dataclass
class PaperPosition:
    symbol: str
    entry_time: datetime
    entry_price: float
    stop_price: float
    qty: int
    order_id: str = ""


# ---------------------------------------------------------------------------
# Position state persistence
# ---------------------------------------------------------------------------

def _position_file(symbol: str) -> Path:
    sym_safe = symbol.replace(".", "_")
    return cfg.logs_dir / f"paper_{sym_safe}_position.json"


def _save_position(pos: PaperPosition) -> None:
    d = asdict(pos)
    d["entry_time"] = str(pos.entry_time)
    _position_file(pos.symbol).write_text(json.dumps(d))
    log.info("Position state saved to disk: %s", _position_file(pos.symbol))


def _load_position(symbol: str) -> PaperPosition | None:
    path = _position_file(symbol)
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text())
        pos = PaperPosition(
            symbol=d["symbol"],
            entry_time=datetime.fromisoformat(d["entry_time"]),
            entry_price=d["entry_price"],
            stop_price=d["stop_price"],
            qty=d["qty"],
            order_id=d.get("order_id", ""),
        )
        log.warning("Recovered open position from disk: entry=%.4f stop=%.4f qty=%d",
                    pos.entry_price, pos.stop_price, pos.qty)
        return pos
    except Exception as e:
        log.error("Failed to load position state: %s — starting fresh", e)
        return None


def _clear_position(symbol: str) -> None:
    path = _position_file(symbol)
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# Trade context
# ---------------------------------------------------------------------------

@contextmanager
def trade_context():
    ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host=cfg.host,
        port=cfg.port,
    )
    try:
        yield ctx
    finally:
        ctx.close()


def _get_simulate_acc_id(ctx: OpenSecTradeContext) -> int:
    ret, data = ctx.get_acc_list()
    if ret != RET_OK:
        log.error("get_acc_list failed: %s", data)
        return 0
    sim_rows = data[data["trd_env"] == TrdEnv.SIMULATE]
    if sim_rows.empty:
        log.warning("No SIMULATE account found — using acc_id=0")
        return 0
    return int(sim_rows.iloc[0]["acc_id"])


def _place_buy(ctx, acc_id: int, symbol: str, price: float, qty: int) -> str:
    ret, data = ctx.place_order(
        price=price, qty=qty, code=symbol,
        trd_side=TrdSide.BUY, order_type=OrderType.NORMAL,
        trd_env=TrdEnv.SIMULATE, acc_id=acc_id,
    )
    if ret == RET_OK:
        order_id = str(data["order_id"].iloc[0])
        log.info("BUY  %s qty=%d price=%.4f order_id=%s", symbol, qty, price, order_id)
        return order_id
    log.error("BUY failed: %s", data)
    return ""


def _place_sell(ctx, acc_id: int, symbol: str, price: float, qty: int) -> str:
    ret, data = ctx.place_order(
        price=price, qty=qty, code=symbol,
        trd_side=TrdSide.SELL, order_type=OrderType.NORMAL,
        trd_env=TrdEnv.SIMULATE, acc_id=acc_id,
    )
    if ret == RET_OK:
        order_id = str(data["order_id"].iloc[0])
        log.info("SELL %s qty=%d price=%.4f order_id=%s", symbol, qty, price, order_id)
        return order_id
    log.error("SELL failed: %s", data)
    return ""


# ---------------------------------------------------------------------------
# Candle fetching with explicit closed-candle verification
# ---------------------------------------------------------------------------

def _latest_closed_candles(symbol: str, days: int = CANDLE_LOOKBACK_DAYS) -> pd.DataFrame:
    """Fetch recent candles and drop the last bar, which may still be forming.

    The Moomoo API can return the currently forming candle as the last row.
    We always discard it to guarantee we only evaluate closed bars.
    Logs the dropped candle's timestamp vs current wall time for auditing.
    """
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = fetch_candles(symbol=symbol, ktype=cfg.candle_ktype, start=start, end=end)
    if df.empty:
        return df

    last_bar_ts = df.iloc[-1]["time_key"]
    now = datetime.now()
    log.info(
        "Candle check: last_bar_ts=%s  eval_time=%s  — dropping last bar (may be forming)",
        last_bar_ts, now.strftime("%Y-%m-%d %H:%M:%S"),
    )
    return df.iloc[:-1].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(symbol: str | None = None) -> None:
    symbol = symbol or cfg.symbol

    if cfg.trd_env != "SIMULATE":
        log.error("TRD_ENV is '%s' — paper runner requires SIMULATE. Aborting.", cfg.trd_env)
        return

    log.info("Paper runner starting: symbol=%s ktype=%s min_signal_score=%d",
             symbol, cfg.candle_ktype, cfg.min_signal_score)
    notify(f"[PAPER] Runner started: {symbol}")

    elog = PaperEventLog(symbol)
    elog.info(f"runner_start symbol={symbol} ktype={cfg.candle_ktype} min_signal_score={cfg.min_signal_score}")

    position: PaperPosition | None = _load_position(symbol)
    if position:
        elog.info(f"recovered_position entry={position.entry_price} stop={position.stop_price} qty={position.qty}")

    acc_id: int | None = None
    daily = DailyTracker()
    consecutive_errors = 0

    while True:
        now = datetime.now()

        if not trading_allowed():
            log.info("[%s] Trading blocked — waiting", now.strftime("%H:%M:%S"))
            time.sleep(POLL_SECONDS)
            continue

        try:
            df = _latest_closed_candles(symbol)
            if len(df) < 20:
                log.warning("Not enough candles (%d) — waiting", len(df))
                time.sleep(POLL_SECONDS)
                continue

            # Run full indicator + signal engine pipeline (adds bonus_score)
            df = compute_signals(df)
            last = df.iloc[-1]

            candle_ts = last["time_key"]
            close = float(last["close"])
            sig = signal_snapshot(last)
            bonus = int(last["bonus_score"]) if "bonus_score" in last else 0

            log.info(
                "BAR %s  close=%.4f  score=%d/5  bonus=%d/%d  %s",
                candle_ts, close, sig.score, bonus, 3, sig,
            )

            elog.bar_eval(
                candle_ts=candle_ts, eval_ts=now, accepted=True,
                close=close, score=sig.score, bonus=bonus,
                signals=sig.details,
            )

            with trade_context() as tctx:
                if acc_id is None:
                    acc_id = _get_simulate_acc_id(tctx)

                if position is None:
                    core_met = bool(last["sig_bb_touch"]) and bool(last["sig_kdj_cross"])
                    bonus_met = bonus >= cfg.min_signal_score

                    if core_met and bonus_met:
                        if not daily.can_open():
                            elog.risk_block("daily_limit_reached",
                                            trades=daily.trades, pnl=daily.pnl)
                        else:
                            qty = calc_qty(close)
                            if qty == 0:
                                log.warning(
                                    "RISK BLOCK: one share of %s (%.2f) exceeds "
                                    "MAX_POSITION_DOLLARS (%.2f) — skipping",
                                    symbol, close, cfg.max_position_dollars,
                                )
                                elog.risk_block("price_exceeds_max_position",
                                                price=close,
                                                max_dollars=cfg.max_position_dollars)
                            else:
                                stop = close - cfg.atr_stop_mult * float(last["atr"])
                                elog.order_attempt("BUY", qty, close)
                                order_id = _place_buy(tctx, acc_id, symbol, close, qty)
                                elog.order_result("BUY", success=bool(order_id),
                                                  order_id=order_id)
                                if order_id:
                                    position = PaperPosition(
                                        symbol=symbol,
                                        entry_time=candle_ts,
                                        entry_price=close,
                                        stop_price=stop,
                                        qty=qty,
                                        order_id=order_id,
                                    )
                                    _save_position(position)
                                    elog.position_open(close, stop, qty)
                                    notify_entry(symbol, close, stop)
                                    log.info(
                                        "POSITION OPEN  entry=%.4f stop=%.4f qty=%d "
                                        "notional=%.2f order_id=%s",
                                        close, stop, qty, qty * close, order_id,
                                    )
                    elif core_met:
                        log.info("Signal skip: core met but bonus=%d < %d", bonus, cfg.min_signal_score)
                        elog.signal_skip("bonus_below_threshold",
                                         score=sig.score, bonus=bonus,
                                         min_score=cfg.min_signal_score)

                else:
                    exit_reason: str | None = None
                    if close >= float(last["bb_middle"]):
                        exit_reason = "TARGET_BB_MIDDLE"
                    elif cfg.exit_on_kdj_death and bool(last["kdj_death_cross"]):
                        exit_reason = "KDJ_DEATH_CROSS"
                    elif close < position.stop_price:
                        exit_reason = "STOP_LOSS"

                    if exit_reason:
                        pnl_per_share = close - position.entry_price
                        pnl_total = pnl_per_share * position.qty
                        elog.order_attempt("SELL", position.qty, close)
                        order_id = _place_sell(tctx, acc_id, symbol, close, position.qty)
                        elog.order_result("SELL", success=bool(order_id), order_id=order_id)
                        daily.record_trade(pnl_total)
                        _clear_position(symbol)
                        elog.position_close(close, exit_reason, pnl_total)
                        notify_exit(symbol, close, exit_reason, pnl_total)
                        log.info(
                            "POSITION CLOSED  exit=%.4f qty=%d pnl/share=%+.4f "
                            "pnl_total=%+.4f reason=%s",
                            close, position.qty, pnl_per_share, pnl_total, exit_reason,
                        )
                        position = None

        except KeyboardInterrupt:
            log.info("Paper runner stopped by user")
            elog.info("runner_stop reason=keyboard_interrupt")
            notify(f"[PAPER] Runner stopped: {symbol}")
            break
        except Exception as e:
            consecutive_errors += 1
            log.error("Loop error #%d: %s", consecutive_errors, e, exc_info=True)
            elog.error(str(e))
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                wait = BACKOFF_SECONDS
                log.warning("%d consecutive errors — backing off %ds", consecutive_errors, wait)
                notify(f"[PAPER] {consecutive_errors} consecutive errors, backing off {wait}s")
                time.sleep(wait)
                consecutive_errors = 0
                continue
        else:
            consecutive_errors = 0

        time.sleep(POLL_SECONDS)  # single-symbol loop end


# ---------------------------------------------------------------------------
# Multi-symbol loop
# ---------------------------------------------------------------------------

def run_multi(symbols: list[str] | None = None) -> None:
    """Run the paper loop across multiple symbols sequentially each poll cycle.

    Shares one DailyTracker (total trades/loss across all symbols).
    Each symbol has its own position state and event log.
    """
    symbols = symbols or cfg.symbols

    if cfg.trd_env != "SIMULATE":
        log.error("TRD_ENV is '%s' — paper runner requires SIMULATE. Aborting.", cfg.trd_env)
        return

    log.info("Multi-symbol paper runner: %s  ktype=%s  min_signal_score=%d",
             symbols, cfg.candle_ktype, cfg.min_signal_score)
    notify(f"[PAPER] Multi runner started: {', '.join(symbols)}")

    positions: dict[str, PaperPosition | None] = {
        sym: _load_position(sym) for sym in symbols
    }
    elogs: dict[str, PaperEventLog] = {sym: PaperEventLog(sym) for sym in symbols}
    acc_id: int | None = None
    daily = DailyTracker()
    consecutive_errors = 0

    for sym, pos in positions.items():
        if pos:
            elogs[sym].info(f"recovered_position entry={pos.entry_price} stop={pos.stop_price} qty={pos.qty}")

    while True:
        if not trading_allowed():
            log.info("Trading blocked — waiting")
            time.sleep(POLL_SECONDS)
            continue

        try:
            with trade_context() as tctx:
                if acc_id is None:
                    acc_id = _get_simulate_acc_id(tctx)
                for symbol in symbols:
                    _eval_symbol(symbol, tctx, acc_id, positions, elogs, daily)

        except KeyboardInterrupt:
            log.info("Multi runner stopped by user")
            notify("[PAPER] Multi runner stopped")
            break
        except Exception as e:
            consecutive_errors += 1
            log.error("Multi loop error #%d: %s", consecutive_errors, e, exc_info=True)
            for elog in elogs.values():
                elog.error(str(e))
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                log.warning("%d errors — backing off %ds", consecutive_errors, BACKOFF_SECONDS)
                notify(f"[PAPER] {consecutive_errors} errors, backing off {BACKOFF_SECONDS}s")
                time.sleep(BACKOFF_SECONDS)
                consecutive_errors = 0
                continue
        else:
            consecutive_errors = 0

        time.sleep(POLL_SECONDS)


def _eval_symbol(symbol: str, tctx, acc_id: int,
                 positions: dict, elogs: dict, daily: DailyTracker) -> None:
    """Evaluate one symbol within the multi-symbol loop."""
    elog = elogs[symbol]
    now = datetime.now()

    df = _latest_closed_candles(symbol)
    if len(df) < 20:
        log.warning("%s: not enough candles (%d)", symbol, len(df))
        return

    df = compute_signals(df)
    last = df.iloc[-1]

    candle_ts = last["time_key"]
    close = float(last["close"])
    sig = signal_snapshot(last)
    bonus = int(last["bonus_score"]) if "bonus_score" in last else 0

    log.info("%-8s  BAR %s  close=%.4f  score=%d/5  bonus=%d/3  %s",
             symbol, candle_ts, close, sig.score, bonus, sig)
    elog.bar_eval(candle_ts=candle_ts, eval_ts=now, accepted=True,
                  close=close, score=sig.score, bonus=bonus, signals=sig.details)

    position = positions[symbol]

    if position is None:
        core_met = bool(last["sig_bb_touch"]) and bool(last["sig_kdj_cross"])
        bonus_met = bonus >= cfg.min_signal_score

        if core_met and bonus_met:
            if not daily.can_open():
                elog.risk_block("daily_limit_reached", trades=daily.trades, pnl=daily.pnl)
            else:
                qty = calc_qty(close)
                if qty == 0:
                    log.warning("RISK BLOCK %s: price %.2f exceeds MAX_POSITION_DOLLARS %.2f",
                                symbol, close, cfg.max_position_dollars)
                    elog.risk_block("price_exceeds_max_position", price=close,
                                    max_dollars=cfg.max_position_dollars)
                else:
                    stop = close - cfg.atr_stop_mult * float(last["atr"])
                    elog.order_attempt("BUY", qty, close)
                    order_id = _place_buy(tctx, acc_id, symbol, close, qty)
                    elog.order_result("BUY", success=bool(order_id), order_id=order_id)
                    if order_id:
                        pos = PaperPosition(symbol=symbol, entry_time=candle_ts,
                                            entry_price=close, stop_price=stop,
                                            qty=qty, order_id=order_id)
                        positions[symbol] = pos
                        _save_position(pos)
                        elog.position_open(close, stop, qty)
                        notify_entry(symbol, close, stop)
                        log.info("%-8s  OPEN  entry=%.4f stop=%.4f qty=%d",
                                 symbol, close, stop, qty)
        elif core_met:
            log.info("%-8s  SKIP  bonus=%d < %d", symbol, bonus, cfg.min_signal_score)
            elog.signal_skip("bonus_below_threshold", score=sig.score,
                             bonus=bonus, min_score=cfg.min_signal_score)
    else:
        exit_reason: str | None = None
        if close >= float(last["bb_middle"]):
            exit_reason = "TARGET_BB_MIDDLE"
        elif cfg.exit_on_kdj_death and bool(last["kdj_death_cross"]):
            exit_reason = "KDJ_DEATH_CROSS"
        elif close < position.stop_price:
            exit_reason = "STOP_LOSS"

        if exit_reason:
            pnl_per_share = close - position.entry_price
            pnl_total = pnl_per_share * position.qty
            elog.order_attempt("SELL", position.qty, close)
            order_id = _place_sell(tctx, acc_id, symbol, close, position.qty)
            elog.order_result("SELL", success=bool(order_id), order_id=order_id)
            daily.record_trade(pnl_total)
            _clear_position(symbol)
            positions[symbol] = None
            elog.position_close(close, exit_reason, pnl_total)
            notify_exit(symbol, close, exit_reason, pnl_total)
            log.info("%-8s  CLOSE exit=%.4f pnl=%+.4f reason=%s",
                     symbol, close, pnl_total, exit_reason)
