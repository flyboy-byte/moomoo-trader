"""
Paper-trading loop.

Polls OpenD every 60 seconds, evaluates the last N closed 5-min candles through
the full signal engine, and places simulated orders via OpenSecTradeContext.

Supports multiple simultaneous strategies on the same symbols. Each (symbol, strategy)
pair has independent position state and P&L tracking. Candles are fetched once per
symbol per poll and shared across all active strategies.

Active strategies are controlled by STRATEGIES in .env (comma-separated list of
"bb_kdj" and/or "vwap"). Defaults to STRATEGY_TYPE for backward compatibility.

Kill switch: create STOP_TRADING.txt in the project root to pause without killing
the process. Remove the file to resume.

Structured event log: every signal check, risk block, order attempt, fill, and exit
is written to logs/paper_SYMBOL_YYYY-MM-DD.jsonl with a strategy tag on each event.
"""
import json
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
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
from .indicators import add_all
from .notifications import notify, notify_entry, notify_exit
from .orb_strategy import _build_opening_ranges, ORB_MINUTES, ORB_TARGET_MULT, ORB_VOL_MULT
from .risk import trading_allowed, calc_qty, DailyTracker, market_open, seconds_until_open
from .signals import snapshot as signal_snapshot
from .strategy import compute_signals
from .vwap_signals import snapshot_vwap
from .vwap_strategy import compute_vwap_signals, VWAPSignal
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
    """Appends structured JSON events to logs/paper_SYMBOL_YYYY-MM-DD.jsonl.

    Each event includes a strategy tag so multi-strategy runs are distinguishable.
    One file per symbol per day — all strategies for that symbol share the file.
    """

    def __init__(self, symbol: str) -> None:
        cfg.logs_dir.mkdir(exist_ok=True)
        self._sym_safe = symbol.replace(".", "_")
        self._sym = symbol

    @property
    def _path(self) -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        return cfg.logs_dir / f"paper_{self._sym_safe}_{date_str}.jsonl"

    def _write(self, event: str, strategy: str = "", **fields) -> None:
        record = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event,
                  "strategy": strategy, **fields}
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            print(f"[JSONL WRITE FAIL] {json.dumps(record)} err={e}", file=sys.stderr)

    def bar_eval(self, candle_ts, eval_ts: datetime, accepted: bool, close: float,
                 score: int, bonus: int, signals: dict, strategy: str = "") -> None:
        age_s = int((eval_ts - pd.Timestamp(candle_ts)).total_seconds())
        self._write("bar_eval", strategy=strategy, candle_ts=str(candle_ts),
                    eval_ts=eval_ts.isoformat(), candle_age_s=age_s, accepted=accepted,
                    close=round(close, 4), signal_score=score, bonus_score=bonus,
                    signals=signals)

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

    def position_open(self, entry: float, stop: float, qty: int,
                      strategy: str = "") -> None:
        self._write("position_open", strategy=strategy, symbol=self._sym,
                    entry=round(entry, 4), stop=round(stop, 4), qty=qty)

    def position_close(self, exit_price: float, reason: str, pnl: float,
                       strategy: str = "") -> None:
        self._write("position_close", strategy=strategy, symbol=self._sym,
                    exit=round(exit_price, 4), reason=reason, pnl=round(pnl, 4))

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
    qty: int
    order_id: str = ""
    target_price: float = 0.0  # fixed target for ORB; 0 = not used (bb_kdj/vwap use dynamic targets)


# ---------------------------------------------------------------------------
# Position state persistence — keyed by (symbol, strategy)
# ---------------------------------------------------------------------------

def _position_file(symbol: str, strategy: str) -> Path:
    sym_safe = symbol.replace(".", "_")
    return cfg.logs_dir / f"paper_{sym_safe}_{strategy}_position.json"


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
        )
        log.warning("Recovered open position [%s/%s]: entry=%.4f stop=%.4f qty=%d",
                    symbol, strategy, pos.entry_price, pos.stop_price, pos.qty)
        return pos
    except Exception as e:
        log.error("Failed to load position state [%s/%s]: %s — starting fresh",
                  symbol, strategy, e)
        return None


def _clear_position(symbol: str, strategy: str) -> None:
    path = _position_file(symbol, strategy)
    if path.exists():
        path.unlink()


def _orb_traded_file(symbol: str) -> Path:
    return cfg.logs_dir / f"paper_{symbol.replace('.', '_')}_orb_traded.json"


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
    """
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = fetch_candles(symbol=symbol, ktype=cfg.candle_ktype, start=start, end=end)
    if df.empty:
        return df

    last_bar_ts = df.iloc[-1]["time_key"]
    now = datetime.now()
    from zoneinfo import ZoneInfo
    now_et = datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    age_min = (now_et - pd.Timestamp(last_bar_ts)).total_seconds() / 60
    log.info(
        "Candle check: last_bar_ts=%s  eval_time=%s  age=%.0fmin — dropping last bar (may be forming)",
        last_bar_ts, now.strftime("%Y-%m-%d %H:%M:%S"), age_min,
    )
    if age_min > 15:
        log.warning("Stale candles (%.0f min old) — skipping eval", age_min)
        return pd.DataFrame()
    return df.iloc[:-1].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Per-strategy evaluation — called once per (symbol, strategy) per poll
# ---------------------------------------------------------------------------

def _eval_bb_kdj(
    symbol: str, df_signals: pd.DataFrame, tctx, acc_id: int,
    position: PaperPosition | None, elog: PaperEventLog, daily: DailyTracker,
) -> PaperPosition | None:
    """Evaluate BB+KDJ strategy for one symbol on a pre-annotated DataFrame."""
    last = df_signals.iloc[-1]
    candle_ts = last["time_key"]
    close = float(last["close"])
    now = datetime.now()

    sig = signal_snapshot(last)
    bonus = int(last["bonus_score"]) if "bonus_score" in last else 0
    log.info("%-8s [bb_kdj] BAR %s  close=%.4f  score=%d/5  bonus=%d/3  %s",
             symbol, candle_ts, close, sig.score, bonus, sig)
    elog.bar_eval(candle_ts=candle_ts, eval_ts=now, accepted=True,
                  close=close, score=sig.score, bonus=bonus,
                  signals=sig.details, strategy="bb_kdj")

    if position is None:
        if cfg.strategy_mode == "permissive":
            core_met = bool(last["sig_bb_touch"])
            bonus_met = bonus >= 1
        else:
            if cfg.kdj_window_bars > 0:
                window = min(cfg.kdj_window_bars + 1, len(df_signals))
                kdj_met = bool(df_signals["kdj_golden_cross"].iloc[-window:].any())
            else:
                kdj_met = bool(last["sig_kdj_cross"])
            core_met = bool(last["sig_bb_touch"]) and kdj_met
            bonus_met = bonus >= cfg.min_signal_score

        if core_met and bonus_met:
            if not daily.can_open():
                elog.risk_block("daily_limit_reached", strategy="bb_kdj",
                                trades=daily.trades, pnl=daily.pnl)
            else:
                qty = calc_qty(close, symbol)
                cap = cfg.symbol_size_overrides.get(symbol, cfg.max_position_dollars)
                if qty == 0:
                    log.warning("RISK BLOCK [bb_kdj] %s: price %.2f exceeds cap %.2f",
                                symbol, close, cap)
                    elog.risk_block("price_exceeds_max_position", strategy="bb_kdj",
                                    price=close, max_dollars=cap)
                else:
                    stop = close - cfg.atr_stop_mult * float(last["atr"])
                    elog.order_attempt("BUY", qty, close, strategy="bb_kdj")
                    order_id = _place_buy(tctx, acc_id, symbol, close, qty)
                    elog.order_result("BUY", success=bool(order_id),
                                      order_id=order_id, strategy="bb_kdj")
                    if order_id:
                        position = PaperPosition(
                            symbol=symbol, strategy="bb_kdj",
                            entry_time=candle_ts, entry_price=close,
                            stop_price=stop, qty=qty, order_id=order_id,
                        )
                        _save_position(position)
                        elog.position_open(close, stop, qty, strategy="bb_kdj")
                        notify_entry(symbol, close, stop)
                        log.info("%-8s [bb_kdj] OPEN  entry=%.4f stop=%.4f qty=%d",
                                 symbol, close, stop, qty)
        elif core_met:
            log.info("%-8s [bb_kdj] SKIP  bonus=%d < %d", symbol, bonus, cfg.min_signal_score)
            elog.signal_skip("bonus_below_threshold", score=sig.score,
                             bonus=bonus, min_score=cfg.min_signal_score, strategy="bb_kdj")
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
            elog.order_attempt("SELL", position.qty, close, strategy="bb_kdj")
            order_id = _place_sell(tctx, acc_id, symbol, close, position.qty)
            elog.order_result("SELL", success=bool(order_id),
                              order_id=order_id, strategy="bb_kdj")
            daily.record_trade(pnl_total)
            _clear_position(symbol, "bb_kdj")
            elog.position_close(close, exit_reason, pnl_total, strategy="bb_kdj")
            notify_exit(symbol, close, exit_reason, pnl_total)
            log.info("%-8s [bb_kdj] CLOSE exit=%.4f pnl=%+.4f reason=%s",
                     symbol, close, pnl_total, exit_reason)
            position = None

    return position


def _eval_vwap(
    symbol: str, df_signals: pd.DataFrame, tctx, acc_id: int,
    position: PaperPosition | None, elog: PaperEventLog, daily: DailyTracker,
) -> PaperPosition | None:
    """Evaluate VWAP strategy for one symbol on a pre-annotated DataFrame."""
    last = df_signals.iloc[-1]
    candle_ts = last["time_key"]
    close = float(last["close"])
    now = datetime.now()

    vsig = snapshot_vwap(last)
    log.info("%-8s [vwap]   BAR %s  close=%.4f  vwap=%.4f  dist=%.2fATR  entry=%s",
             symbol, candle_ts, close, vsig.vwap, vsig.distance_atr, vsig.entry_ready)
    elog.bar_eval(candle_ts=candle_ts, eval_ts=now, accepted=True,
                  close=close, score=int(vsig.entry_ready), bonus=0,
                  signals=vsig.details, strategy="vwap")

    if position is None:
        entry_ok = (bool(last.get("vwap_entry", False)) and
                    float(last.get("session_return", 0)) > -0.015)
        if entry_ok:
            if not daily.can_open():
                elog.risk_block("daily_limit_reached", strategy="vwap",
                                trades=daily.trades, pnl=daily.pnl)
            else:
                qty = calc_qty(close, symbol)
                cap = cfg.symbol_size_overrides.get(symbol, cfg.max_position_dollars)
                if qty == 0:
                    log.warning("RISK BLOCK [vwap] %s: price %.2f exceeds cap %.2f",
                                symbol, close, cap)
                    elog.risk_block("price_exceeds_max_position", strategy="vwap",
                                    price=close, max_dollars=cap)
                else:
                    stop = close - cfg.vwap_stop_mult * float(last["atr"])
                    elog.order_attempt("BUY", qty, close, strategy="vwap")
                    order_id = _place_buy(tctx, acc_id, symbol, close, qty)
                    elog.order_result("BUY", success=bool(order_id),
                                      order_id=order_id, strategy="vwap")
                    if order_id:
                        position = PaperPosition(
                            symbol=symbol, strategy="vwap",
                            entry_time=candle_ts, entry_price=close,
                            stop_price=stop, qty=qty, order_id=order_id,
                        )
                        _save_position(position)
                        elog.position_open(close, stop, qty, strategy="vwap")
                        notify_entry(symbol, close, stop)
                        log.info("%-8s [vwap]   OPEN  entry=%.4f stop=%.4f qty=%d",
                                 symbol, close, stop, qty)
    else:
        from datetime import time as dtime
        exit_reason: str | None = None
        bar_time = pd.Timestamp(candle_ts).time()
        if bar_time >= dtime(15, 45):
            exit_reason = "TIME_STOP"
        elif close >= float(last["vwap"]):
            exit_reason = "VWAP_TARGET"
        elif close < position.stop_price:
            exit_reason = "VWAP_STOP"

        if exit_reason:
            pnl_per_share = close - position.entry_price
            pnl_total = pnl_per_share * position.qty
            elog.order_attempt("SELL", position.qty, close, strategy="vwap")
            order_id = _place_sell(tctx, acc_id, symbol, close, position.qty)
            elog.order_result("SELL", success=bool(order_id),
                              order_id=order_id, strategy="vwap")
            daily.record_trade(pnl_total)
            _clear_position(symbol, "vwap")
            elog.position_close(close, exit_reason, pnl_total, strategy="vwap")
            notify_exit(symbol, close, exit_reason, pnl_total)
            log.info("%-8s [vwap]   CLOSE exit=%.4f pnl=%+.4f reason=%s",
                     symbol, close, pnl_total, exit_reason)
            position = None

    return position


def _eval_vwap_pb(
    symbol: str, df_signals: pd.DataFrame, tctx, acc_id: int,
    position: PaperPosition | None, elog: PaperEventLog, daily: DailyTracker,
) -> PaperPosition | None:
    """Evaluate VWAP Pullback strategy (flush-and-reclaim) for one symbol.

    Entry: candle wicks below VWAP (low < vwap) but closes above it, with
    session VWAP cross count <= cfg.vwap_pb_max_crosses (no-chop filter).
    Exit: close < vwap (level lost), ATR stop, or 15:45 time stop.
    """
    from .vwap_pullback import _add_session_cross_count
    from datetime import time as dtime

    # Symbol whitelist check
    if cfg.vwap_pb_symbols and symbol not in cfg.vwap_pb_symbols:
        return position

    df = _add_session_cross_count(df_signals)
    last = df.iloc[-1]
    candle_ts = last["time_key"]
    close = float(last["close"])
    vwap = float(last["vwap"]) if not pd.isna(last.get("vwap")) else None
    now = datetime.now()

    if vwap is None:
        return position

    bar_clock = pd.Timestamp(candle_ts).time()
    is_time_stop = bar_clock >= dtime(15, 45)

    log.info("%-8s [vwap_pb] BAR %s  close=%.4f  vwap=%.4f  crosses=%d",
             symbol, candle_ts, close, vwap, int(last.get("vwap_cross_count", 0)))
    elog.bar_eval(candle_ts=candle_ts, eval_ts=now, accepted=True,
                  close=close, score=0, bonus=0,
                  signals={"cross_count": int(last.get("vwap_cross_count", 0)),
                           "close_above_vwap": close > vwap},
                  strategy="vwap_pb")

    if position is not None:
        exit_reason: str | None = None
        if is_time_stop:
            exit_reason = "TIME_STOP"
        elif close < vwap:
            exit_reason = "VWAP_LOST"
        elif close < position.stop_price:
            exit_reason = "STOP"

        if exit_reason:
            pnl_per_share = close - position.entry_price
            pnl_total = pnl_per_share * position.qty
            elog.order_attempt("SELL", position.qty, close, strategy="vwap_pb")
            order_id = _place_sell(tctx, acc_id, symbol, close, position.qty)
            elog.order_result("SELL", success=bool(order_id),
                              order_id=order_id, strategy="vwap_pb")
            daily.record_trade(pnl_total)
            _clear_position(symbol, "vwap_pb")
            elog.position_close(close, exit_reason, pnl_total, strategy="vwap_pb")
            notify_exit(symbol, close, exit_reason, pnl_total)
            log.info("%-8s [vwap_pb] CLOSE exit=%.4f pnl=%+.4f reason=%s",
                     symbol, close, pnl_total, exit_reason)
            position = None

    elif not is_time_stop and bar_clock >= dtime(9, 45):
        wick_below = float(last["low"]) < vwap
        close_above = close > vwap
        no_chop = int(last.get("vwap_cross_count", 0)) <= cfg.vwap_pb_max_crosses
        quiet_bar = float(last.get("volume", 0)) < float(last.get("volume_ma", float("inf")))

        if wick_below and close_above and no_chop and quiet_bar:
            if not daily.can_open():
                elog.risk_block("daily_limit_reached", strategy="vwap_pb",
                                trades=daily.trades, pnl=daily.pnl)
            else:
                qty = calc_qty(close, symbol)
                cap = cfg.symbol_size_overrides.get(symbol, cfg.max_position_dollars)
                if qty == 0:
                    log.warning("RISK BLOCK [vwap_pb] %s: price %.2f exceeds cap %.2f",
                                symbol, close, cap)
                    elog.risk_block("price_exceeds_max_position", strategy="vwap_pb",
                                    price=close, max_dollars=cap)
                else:
                    stop = close - cfg.vwap_pb_stop_mult * float(last["atr"])
                    elog.order_attempt("BUY", qty, close, strategy="vwap_pb")
                    order_id = _place_buy(tctx, acc_id, symbol, close, qty)
                    elog.order_result("BUY", success=bool(order_id),
                                      order_id=order_id, strategy="vwap_pb")
                    if order_id:
                        position = PaperPosition(
                            symbol=symbol, strategy="vwap_pb",
                            entry_time=candle_ts, entry_price=close,
                            stop_price=stop, qty=qty, order_id=order_id,
                        )
                        _save_position(position)
                        elog.position_open(close, stop, qty, strategy="vwap_pb")
                        notify_entry(symbol, close, stop)
                        log.info("%-8s [vwap_pb] OPEN  entry=%.4f stop=%.4f qty=%d",
                                 symbol, close, stop, qty)

    return position


def _eval_orb(
    symbol: str, df_raw: pd.DataFrame, tctx, acc_id: int,
    position: PaperPosition | None, elog: PaperEventLog, daily: DailyTracker,
    already_entered: bool = False,
) -> PaperPosition | None:
    """Evaluate ORB strategy (long-only) for one symbol.

    Short entries are skipped in the live runner — they require TrdSide.SELL_SHORT
    with margin handling not yet wired up. Backtest PnL includes shorts; live will be
    long-only. Net effect: roughly half the trade frequency of the backtest.

    already_entered: True if ORB already traded today for this symbol. Enforces the
    one-trade-per-day rule across process restarts (state persisted to disk).
    """
    from datetime import time as dtime

    df = add_all(df_raw.copy())
    last = df.iloc[-1]
    candle_ts = last["time_key"]
    close = float(last["close"])
    bar_time = pd.Timestamp(candle_ts)
    bar_date = bar_time.date()
    bar_clock = bar_time.time()
    now = datetime.now()
    is_time_stop = bar_clock >= dtime(15, 45)

    ranges = _build_opening_ranges(df)
    or_info = ranges.get(bar_date)
    or_valid = or_info is not None and or_info["valid"]

    signals_dict = {
        "or_valid": or_valid,
        "or_high": round(or_info["high"], 4) if or_info else None,
        "or_low": round(or_info["low"], 4) if or_info else None,
        "above_or_high": bool(close > or_info["high"]) if or_info else False,
    }
    log.info("%-8s [orb]    BAR %s  close=%.4f  or_valid=%s", symbol, candle_ts, close, or_valid)
    elog.bar_eval(candle_ts=candle_ts, eval_ts=now, accepted=True,
                  close=close, score=int(or_valid), bonus=0,
                  signals=signals_dict, strategy="orb")

    if position is not None:
        exit_reason: str | None = None
        if is_time_stop:
            exit_reason = "TIME_STOP"
        elif position.target_price > 0 and close >= position.target_price:
            exit_reason = "TARGET"
        elif close <= position.stop_price:
            exit_reason = "STOP"

        if exit_reason:
            pnl_per_share = close - position.entry_price
            pnl_total = pnl_per_share * position.qty
            elog.order_attempt("SELL", position.qty, close, strategy="orb")
            order_id = _place_sell(tctx, acc_id, symbol, close, position.qty)
            elog.order_result("SELL", success=bool(order_id),
                              order_id=order_id, strategy="orb")
            daily.record_trade(pnl_total)
            _clear_position(symbol, "orb")
            elog.position_close(close, exit_reason, pnl_total, strategy="orb")
            notify_exit(symbol, close, exit_reason, pnl_total)
            log.info("%-8s [orb]    CLOSE exit=%.4f pnl=%+.4f reason=%s",
                     symbol, close, pnl_total, exit_reason)
            position = None

    elif or_valid and not is_time_stop and not already_entered:
        or_high = or_info["high"]
        or_low = or_info["low"]
        or_range = or_high - or_low
        orb_mins = cfg.orb_minutes_overrides.get(symbol, cfg.orb_minutes)
        cutoff = dtime(9, 30 + orb_mins) if 30 + orb_mins < 60 else \
                 dtime(10, (30 + orb_mins) % 60)
        vol_ok = float(last.get("volume", 0)) > ORB_VOL_MULT * float(last.get("volume_ma", 1))

        if bar_clock >= cutoff and close > or_high and vol_ok:
            if not daily.can_open():
                elog.risk_block("daily_limit_reached", strategy="orb",
                                trades=daily.trades, pnl=daily.pnl)
            else:
                qty = calc_qty(close, symbol)
                cap = cfg.symbol_size_overrides.get(symbol, cfg.max_position_dollars)
                if qty == 0:
                    log.warning("RISK BLOCK [orb] %s: price %.2f exceeds cap %.2f",
                                symbol, close, cap)
                    elog.risk_block("price_exceeds_max_position", strategy="orb",
                                    price=close, max_dollars=cap)
                else:
                    stop = or_low
                    target = close + ORB_TARGET_MULT * or_range
                    elog.order_attempt("BUY", qty, close, strategy="orb")
                    order_id = _place_buy(tctx, acc_id, symbol, close, qty)
                    elog.order_result("BUY", success=bool(order_id),
                                      order_id=order_id, strategy="orb")
                    if order_id:
                        position = PaperPosition(
                            symbol=symbol, strategy="orb",
                            entry_time=candle_ts, entry_price=close,
                            stop_price=stop, target_price=target,
                            qty=qty, order_id=order_id,
                        )
                        _save_position(position)
                        elog.position_open(close, stop, qty, strategy="orb")
                        notify_entry(symbol, close, stop)
                        log.info("%-8s [orb]    OPEN  entry=%.4f stop=%.4f target=%.4f qty=%d",
                                 symbol, close, stop, target, qty)

    return position


def _trigger_eod_summary() -> None:
    """Load today's JSONL and post EOD summary to Discord (no-op if webhook not set)."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "eod_summary",
            Path(__file__).parent.parent / "scripts" / "eod_summary.py",
        )
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        s = mod.load_summary(date.today())
        log.info("EOD: %d closed trades  pnl=%+.2f", len(s.closed_trades), s.realized_pnl)
        if cfg.discord_webhook_url:
            notify(mod.format_discord(s))
    except Exception as e:
        log.warning("EOD summary failed: %s", e)


# ---------------------------------------------------------------------------
# Multi-symbol loop — fetches candles once, runs all active strategies
# ---------------------------------------------------------------------------

def run_multi(symbols: list[str] | None = None) -> None:
    """Run the paper loop across multiple symbols and strategies each poll cycle.

    Candles are fetched once per symbol. All active strategies evaluate the same
    bar. Each (symbol, strategy) pair has independent position state.

    Active strategies: cfg.active_strategies (from STRATEGIES env var).
    Shared DailyTracker: combined daily loss/trade limit across all strategies.
    """
    symbols = symbols or cfg.symbols
    strategies = cfg.active_strategies

    if cfg.trd_env != "SIMULATE":
        log.error("TRD_ENV is '%s' — paper runner requires SIMULATE. Aborting.", cfg.trd_env)
        return

    log.info("Multi runner: symbols=%s  strategies=%s  ktype=%s  min_signal_score=%d",
             symbols, strategies, cfg.candle_ktype, cfg.min_signal_score)
    notify(f"[PAPER] Multi runner started: {', '.join(symbols)} | {', '.join(strategies)}")

    # positions[(symbol, strategy)] = PaperPosition | None
    positions: dict[tuple[str, str], PaperPosition | None] = {
        (sym, strat): _load_position(sym, strat)
        for sym in symbols
        for strat in strategies
    }
    # One event log per symbol (all strategies share the file, tagged per event)
    elogs: dict[str, PaperEventLog] = {sym: PaperEventLog(sym) for sym in symbols}

    # ORB one-trade-per-day enforcement (persisted across restarts)
    orb_traded: dict[str, date] = _load_orb_traded(symbols)

    acc_id: int | None = None
    daily = DailyTracker()
    consecutive_errors = 0
    _was_market_open: bool = False
    _session_day: date = date.today()

    for (sym, strat), pos in positions.items():
        if pos:
            elogs[sym].info(
                f"recovered_position entry={pos.entry_price} stop={pos.stop_price} qty={pos.qty}",
                strategy=strat,
            )

    while True:
        _is_market_open = market_open()
        today = date.today()

        # New calendar day — heartbeat so you know it's alive
        if today != _session_day:
            _session_day = today
            notify(f"[PAPER] New session {today} | {', '.join(symbols)} | {', '.join(strategies)}")

        # Market just closed — post EOD summary
        if _was_market_open and not _is_market_open:
            _trigger_eod_summary()
        _was_market_open = _is_market_open

        if not _is_market_open:
            secs = seconds_until_open()
            log.info("Market closed — sleeping %.0f min until near open", secs / 60)
            time.sleep(max(secs, POLL_SECONDS))
            continue

        if not trading_allowed():
            log.info("Trading blocked — waiting")
            time.sleep(POLL_SECONDS)
            continue

        try:
            with trade_context() as tctx:
                if acc_id is None:
                    acc_id = _get_simulate_acc_id(tctx)
                for symbol in symbols:
                    _eval_symbol_all_strategies(
                        symbol, strategies, tctx, acc_id, positions, elogs, daily,
                        orb_traded=orb_traded,
                    )

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


def _eval_symbol_all_strategies(
    symbol: str,
    strategies: list[str],
    tctx,
    acc_id: int,
    positions: dict[tuple[str, str], PaperPosition | None],
    elogs: dict[str, PaperEventLog],
    daily: DailyTracker,
    orb_traded: dict[str, date] | None = None,
) -> None:
    """Fetch candles once for symbol, then evaluate each active strategy."""
    elog = elogs[symbol]

    df_raw = _latest_closed_candles(symbol)
    if len(df_raw) < 20:
        log.warning("%s: not enough candles (%d)", symbol, len(df_raw))
        return

    # Annotate once per strategy type needed (avoid double compute_signals)
    df_bb: pd.DataFrame | None = None
    df_vwap: pd.DataFrame | None = None

    for strat in strategies:
        if strat == "bb_kdj":
            if df_bb is None:
                df_bb = compute_signals(df_raw)
            positions[(symbol, strat)] = _eval_bb_kdj(
                symbol, df_bb, tctx, acc_id,
                positions[(symbol, strat)], elog, daily,
            )
        elif strat == "vwap":
            if df_vwap is None:
                df_vwap = compute_vwap_signals(df_raw)
            positions[(symbol, strat)] = _eval_vwap(
                symbol, df_vwap, tctx, acc_id,
                positions[(symbol, strat)], elog, daily,
            )
        elif strat == "orb":
            prev_pos = positions[(symbol, strat)]
            already_entered = (orb_traded or {}).get(symbol) == date.today()
            positions[(symbol, strat)] = _eval_orb(
                symbol, df_raw, tctx, acc_id,
                prev_pos, elog, daily,
                already_entered=already_entered,
            )
            # New position just opened — persist the traded date so restarts can't re-enter
            if prev_pos is None and positions[(symbol, strat)] is not None:
                if orb_traded is not None:
                    orb_traded[symbol] = date.today()
                    _save_orb_traded(symbol, date.today())
        elif strat == "vwap_pb":
            if df_bb is None:
                df_bb = compute_signals(df_raw)
            positions[(symbol, strat)] = _eval_vwap_pb(
                symbol, df_bb, tctx, acc_id,
                positions[(symbol, strat)], elog, daily,
            )
        else:
            log.warning("Unknown strategy '%s' — skipping", strat)


# ---------------------------------------------------------------------------
# Single-symbol entry point (backward compat)
# ---------------------------------------------------------------------------

def run(symbol: str | None = None) -> None:
    """Single-symbol paper runner. Wraps run_multi for backward compatibility."""
    symbol = symbol or cfg.symbol
    run_multi(symbols=[symbol])
