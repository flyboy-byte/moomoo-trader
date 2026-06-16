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
import math
from dataclasses import field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from . import clock
from .config import cfg, validate_config
from .events import (
    PaperEventLog, PaperPosition,
    _position_file, _save_position, _load_position, _clear_position,
    _orb_traded_file, _load_orb_traded, _save_orb_traded,
)
from .execution import (
    _orphan_warned, _order_status, _reconcile_positions,
    trade_context, _get_simulate_acc_id,
    _place_buy, _place_sell, _place_short, _place_cover,
    _exit_unfilled_notified, _confirm_fill, _cancel_order,
    _execute_entry, _execute_exit,
)
from .data import fetch_candles
from .indicators import add_all
from .notifications import notify, notify_entry, notify_exit
from .orb_strategy import _build_opening_ranges
from .risk import trading_allowed, calc_qty, calc_qty_fractional, calc_qty_risk, per_slot_dollars, DailyTracker
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
# Per-position sizing — fractional or whole shares
# ---------------------------------------------------------------------------

# Populated at run_multi() startup when TOTAL_CAPITAL is set.
_slot_dollars: float = 0.0

# Tracks the last candle_ts for which an entry was attempted per (symbol, strategy).
# Prevents the 60s poll from retrying the same failed order on every tick until a new candle arrives.
_entry_attempted: dict[tuple[str, str], str] = {}


def _qty(price: float, symbol: str, stop: float | None = None) -> int | float:
    """Return order qty using risk-normalized, fractional, or whole-share logic.

    When RISK_DOLLARS_PER_TRADE is set and the caller provides the stop price:
    qty = risk_dollars / stop_distance, capped by the position dollar cap —
    every trade risks the same dollars regardless of volatility.

    Else, when TOTAL_CAPITAL is set and FRACTIONAL_SHARES=true: returns float qty
    derived from the pre-computed per-slot dollar allocation.
    Falls back to whole-share calc_qty() when fractional result < 1 — Moomoo
    rejects sub-share orders with "Invalid quantity" and the trade is silently lost.
    Also falls back when TOTAL_CAPITAL is not set or FRACTIONAL_SHARES=false.
    """
    if cfg.risk_dollars_per_trade > 0 and stop is not None:
        return calc_qty_risk(price, stop, cfg.risk_dollars_per_trade, _position_cap(symbol))
    if _slot_dollars > 0 and cfg.fractional_shares:
        qty = calc_qty_fractional(price, _slot_dollars)
        if qty >= 1:
            return qty
        log.warning("Fractional qty %.6f < 1 for %s at %.2f — falling back to whole-share",
                    qty, symbol, price)
    return calc_qty(price, symbol)


def _position_cap(symbol: str) -> float:
    """Dollar cap for risk-block logging — slot dollars if capital mode, else per-symbol cap."""
    if _slot_dollars > 0:
        return _slot_dollars
    return cfg.symbol_size_overrides.get(symbol, cfg.max_position_dollars)


# ---------------------------------------------------------------------------
# Candle fetching with explicit closed-candle verification
# ---------------------------------------------------------------------------

def _latest_closed_candles(symbol: str, days: int = CANDLE_LOOKBACK_DAYS) -> pd.DataFrame:
    """Fetch recent candles and drop the last bar, which may still be forming.

    The Moomoo API can return the currently forming candle as the last row.
    We always discard it to guarantee we only evaluate closed bars.

    Stale check is applied to the bar AFTER dropping the forming row — i.e. the
    bar that will actually be evaluated. Checking the forming bar's age is wrong:
    a same-day partial bar has age ~0 but the second-to-last could be from yesterday.
    """
    end = clock.now().strftime("%Y-%m-%d")
    start = (clock.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = fetch_candles(symbol=symbol, ktype=cfg.candle_ktype, start=start, end=end)
    if df.empty:
        return df

    if len(df) < 2:
        log.warning("%s: fewer than 2 candles returned — skipping", symbol)
        return pd.DataFrame()

    # Drop the last (possibly still-forming) bar first
    df = df.iloc[:-1].reset_index(drop=True)

    # NOW check staleness of the bar we'll actually evaluate
    last_closed_ts = df.iloc[-1]["time_key"]
    now_et = clock.now_et()
    age_min = (now_et - pd.Timestamp(last_closed_ts)).total_seconds() / 60
    log.info(
        "Candle check: last_closed=%s  age=%.0fmin",
        last_closed_ts, age_min,
    )
    if age_min > 15:
        log.warning("Stale candles: last closed bar %s is %.0f min old — skipping eval",
                    last_closed_ts, age_min)
        return pd.DataFrame()
    return df


# ---------------------------------------------------------------------------
# Per-strategy evaluation — called once per (symbol, strategy) per poll
# ---------------------------------------------------------------------------

def _kdj_cross_age(df_signals: pd.DataFrame, max_lookback: int = 50) -> int | None:
    """Bars since the most recent KDJ golden cross (0 = current bar).

    Logged on every bb_kdj bar_eval/position_open so live w>0 trades can be
    post-hoc split into the same-bar (w=0) subset vs diluted window entries.
    Returns None if no cross within max_lookback bars.
    """
    if "kdj_golden_cross" not in df_signals.columns:
        return None
    tail = df_signals["kdj_golden_cross"].tail(max_lookback).tolist()
    for age, fired in enumerate(reversed(tail)):
        if bool(fired):
            return age
    return None


def _eval_bb_kdj(
    symbol: str, df_signals: pd.DataFrame, tctx, acc_id: int,
    position: PaperPosition | None, elog: PaperEventLog, daily: DailyTracker,
) -> PaperPosition | None:
    """Evaluate BB+KDJ strategy for one symbol on a pre-annotated DataFrame."""
    last = df_signals.iloc[-1]
    candle_ts = last["time_key"]
    close = float(last["close"])
    now = clock.now_et()

    sig = signal_snapshot(last)
    bonus = int(last["bonus_score"]) if "bonus_score" in last else 0
    bb_lower = round(float(last["bb_lower"]), 4) if "bb_lower" in last else None
    bb_middle = round(float(last["bb_middle"]), 4) if "bb_middle" in last else None
    log.info("%-8s [bb_kdj] BAR %s  close=%.4f  bb_lower=%.4f  score=%d/5  bonus=%d/3  %s",
             symbol, candle_ts, close, bb_lower or 0, sig.score, bonus, sig)
    adx = float(last["adx"]) if "adx" in last and not pd.isna(last["adx"]) else 0.0
    cross_age = _kdj_cross_age(df_signals)
    elog.bar_eval(candle_ts=candle_ts, eval_ts=now, accepted=True,
                  close=close, score=sig.score, bonus=bonus,
                  signals={**sig.details, "bb_lower": bb_lower, "bb_middle": bb_middle,
                           "kdj_cross_age": cross_age},
                  regime_label="trending" if adx > 25 else "ranging",
                  strategy="bb_kdj")

    if position is None:
        if cfg.strategy_mode == "permissive":
            core_met = bool(last["sig_bb_touch"])
            bonus_met = bonus >= 1
        else:
            effective_window = cfg.kdj_window_overrides.get(symbol, cfg.kdj_window_bars)
            if effective_window > 0:
                window = min(effective_window + 1, len(df_signals))
                kdj_met = bool(df_signals["kdj_golden_cross"].iloc[-window:].any())
            else:
                kdj_met = bool(last["sig_kdj_cross"])
            core_met = bool(last["sig_bb_touch"]) and kdj_met
            bonus_met = bonus >= cfg.min_signal_score

        if core_met and bonus_met:
            if _entry_attempted.get((symbol, "bb_kdj")) == str(candle_ts):
                pass  # already tried this candle — don't retry until next bar
            else:
                _entry_attempted[(symbol, "bb_kdj")] = str(candle_ts)
                if not daily.can_open(strategy="bb_kdj"):
                    elog.risk_block("daily_limit_reached", strategy="bb_kdj",
                                    trades=daily.trades, pnl=daily.pnl)
                else:
                    stop = close - cfg.atr_stop_mult * float(last["atr"])
                    qty = _qty(close, symbol, stop=stop)
                    cap = _position_cap(symbol)
                    if not qty:
                        log.warning("RISK BLOCK [bb_kdj] %s: price %.2f exceeds cap %.2f",
                                    symbol, close, cap)
                        elog.risk_block("price_exceeds_max_position", strategy="bb_kdj",
                                        price=close, max_dollars=cap)
                    else:
                        filled = _execute_entry(tctx, acc_id, symbol, qty, close,
                                                "bb_kdj", elog)
                        if filled:
                            order_id, fill_price, fill_qty = filled
                            position = PaperPosition(
                                symbol=symbol, strategy="bb_kdj",
                                entry_time=candle_ts, entry_price=fill_price,
                                stop_price=stop, qty=fill_qty, order_id=order_id,
                            )
                            _save_position(position)
                            elog.position_open(fill_price, stop, fill_qty, strategy="bb_kdj",
                                               intended_price=close, kdj_cross_age=cross_age)
                            notify_entry(symbol, fill_price, stop)
                            log.info("%-8s [bb_kdj] OPEN  entry=%.4f stop=%.4f qty=%s",
                                     symbol, fill_price, stop, fill_qty)
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
            fill_price = _execute_exit(tctx, acc_id, symbol, position, close,
                                       exit_reason, elog)
            if fill_price is None:
                return position  # exit unfilled — keep position, retry next poll
            pnl_total = (fill_price - position.entry_price) * position.qty
            hold_bars = int((pd.Timestamp(candle_ts) - pd.Timestamp(position.entry_time)).total_seconds() / 300)
            daily.record_trade(pnl_total, strategy="bb_kdj")
            _clear_position(symbol, "bb_kdj")
            elog.position_close(fill_price, exit_reason, pnl_total, hold_bars=hold_bars,
                                strategy="bb_kdj", direction="long", intended_price=close)
            notify_exit(symbol, fill_price, exit_reason, pnl_total)
            log.info("%-8s [bb_kdj] CLOSE exit=%.4f pnl=%+.4f reason=%s",
                     symbol, fill_price, pnl_total, exit_reason)
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
    now = clock.now_et()

    vsig = snapshot_vwap(last)
    atr_val = float(last.get("atr", 1) or 1)
    dist_atr = (vsig.vwap - close) / atr_val
    log.info("%-8s [vwap]   BAR %s  close=%.4f  vwap=%.4f  dist=%.2fATR  entry=%s",
             symbol, candle_ts, close, vsig.vwap, dist_atr, vsig.entry_ready)
    adx_vwap = float(last["adx"]) if "adx" in last and not pd.isna(last.get("adx", float("nan"))) else 0.0
    elog.bar_eval(candle_ts=candle_ts, eval_ts=now, accepted=True,
                  close=close, score=int(vsig.entry_ready), bonus=0,
                  signals=vsig.details,
                  regime_label="trending" if adx_vwap > 25 else "ranging",
                  strategy="vwap")

    if position is None:
        entry_ok = (bool(last.get("vwap_entry", False)) and
                    float(last.get("session_return", 0)) > -0.015)
        if entry_ok:
            if _entry_attempted.get((symbol, "vwap")) == str(candle_ts):
                pass  # already tried this candle — don't retry until next bar
            else:
                _entry_attempted[(symbol, "vwap")] = str(candle_ts)
                if not daily.can_open(strategy="vwap"):
                    elog.risk_block("daily_limit_reached", strategy="vwap",
                                    trades=daily.trades, pnl=daily.pnl)
                else:
                    stop = close - cfg.vwap_stop_mult * float(last["atr"])
                    qty = _qty(close, symbol, stop=stop)
                    cap = _position_cap(symbol)
                    if not qty:
                        log.warning("RISK BLOCK [vwap] %s: price %.2f exceeds cap %.2f",
                                    symbol, close, cap)
                        elog.risk_block("price_exceeds_max_position", strategy="vwap",
                                        price=close, max_dollars=cap)
                    else:
                        filled = _execute_entry(tctx, acc_id, symbol, qty, close,
                                                "vwap", elog)
                        if filled:
                            order_id, fill_price, fill_qty = filled
                            position = PaperPosition(
                                symbol=symbol, strategy="vwap",
                                entry_time=candle_ts, entry_price=fill_price,
                                stop_price=stop, qty=fill_qty, order_id=order_id,
                            )
                            _save_position(position)
                            elog.position_open(fill_price, stop, fill_qty, strategy="vwap",
                                               intended_price=close)
                            notify_entry(symbol, fill_price, stop)
                            log.info("%-8s [vwap]   OPEN  entry=%.4f stop=%.4f qty=%s",
                                     symbol, fill_price, stop, fill_qty)
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
            fill_price = _execute_exit(tctx, acc_id, symbol, position, close,
                                       exit_reason, elog)
            if fill_price is None:
                return position  # exit unfilled — keep position, retry next poll
            pnl_total = (fill_price - position.entry_price) * position.qty
            hold_bars_vwap = int((pd.Timestamp(candle_ts) - pd.Timestamp(position.entry_time)).total_seconds() / 300)
            daily.record_trade(pnl_total, strategy="vwap")
            _clear_position(symbol, "vwap")
            elog.position_close(fill_price, exit_reason, pnl_total, hold_bars=hold_bars_vwap,
                                strategy="vwap", direction="long", intended_price=close)
            notify_exit(symbol, fill_price, exit_reason, pnl_total)
            log.info("%-8s [vwap]   CLOSE exit=%.4f pnl=%+.4f reason=%s",
                     symbol, fill_price, pnl_total, exit_reason)
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
    now = clock.now_et()

    if vwap is None:
        return position

    bar_clock = pd.Timestamp(candle_ts).time()
    is_time_stop = bar_clock >= dtime(15, 45)

    wick_below = float(last["low"]) < vwap if "low" in last else False
    cross_count = int(last.get("vwap_cross_count", 0))
    log.info("%-8s [vwap_pb] BAR %s  close=%.4f  vwap=%.4f  crosses=%d  wick_below=%s",
             symbol, candle_ts, close, vwap, cross_count, wick_below)
    adx_vp = float(last["adx"]) if "adx" in last and not pd.isna(last.get("adx", float("nan"))) else 0.0
    elog.bar_eval(candle_ts=candle_ts, eval_ts=now, accepted=True,
                  close=close, score=0, bonus=0,
                  signals={"cross_count": cross_count, "close_above_vwap": close > vwap,
                           "wick_below": wick_below},
                  regime_label="trending" if adx_vp > 25 else "ranging",
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
            fill_price = _execute_exit(tctx, acc_id, symbol, position, close,
                                       exit_reason, elog)
            if fill_price is None:
                return position  # exit unfilled — keep position, retry next poll
            pnl_total = (fill_price - position.entry_price) * position.qty
            hold_bars_vp = int((pd.Timestamp(candle_ts) - pd.Timestamp(position.entry_time)).total_seconds() / 300)
            daily.record_trade(pnl_total, strategy="vwap_pb")
            _clear_position(symbol, "vwap_pb")
            elog.position_close(fill_price, exit_reason, pnl_total, hold_bars=hold_bars_vp,
                                strategy="vwap_pb", direction="long", intended_price=close)
            notify_exit(symbol, fill_price, exit_reason, pnl_total)
            log.info("%-8s [vwap_pb] CLOSE exit=%.4f pnl=%+.4f reason=%s",
                     symbol, fill_price, pnl_total, exit_reason)
            position = None

    elif not is_time_stop and bar_clock >= dtime(*cfg.vwap_pb_min_entry_time):
        wick_below = float(last["low"]) < vwap
        close_above = close > vwap
        no_chop = int(last.get("vwap_cross_count", 0)) <= cfg.vwap_pb_max_crosses
        quiet_bar = float(last.get("volume", 0)) < float(last.get("volume_ma", float("inf")))

        if wick_below and close_above and no_chop and quiet_bar:
            if _entry_attempted.get((symbol, "vwap_pb")) == str(candle_ts):
                pass  # already tried this candle — don't retry until next bar
            else:
                _entry_attempted[(symbol, "vwap_pb")] = str(candle_ts)
                if not daily.can_open(strategy="vwap_pb"):
                    elog.risk_block("daily_limit_reached", strategy="vwap_pb",
                                    trades=daily.trades, pnl=daily.pnl)
                else:
                    stop = close - cfg.vwap_pb_stop_mult * float(last["atr"])
                    qty = _qty(close, symbol, stop=stop)
                    cap = _position_cap(symbol)
                    if not qty:
                        log.warning("RISK BLOCK [vwap_pb] %s: price %.2f exceeds cap %.2f",
                                    symbol, close, cap)
                        elog.risk_block("price_exceeds_max_position", strategy="vwap_pb",
                                        price=close, max_dollars=cap)
                    else:
                        filled = _execute_entry(tctx, acc_id, symbol, qty, close,
                                                "vwap_pb", elog)
                        if filled:
                            order_id, fill_price, fill_qty = filled
                            position = PaperPosition(
                                symbol=symbol, strategy="vwap_pb",
                                entry_time=candle_ts, entry_price=fill_price,
                                stop_price=stop, qty=fill_qty, order_id=order_id,
                            )
                            _save_position(position)
                            elog.position_open(fill_price, stop, fill_qty, strategy="vwap_pb",
                                               intended_price=close)
                            notify_entry(symbol, fill_price, stop)
                            log.info("%-8s [vwap_pb] OPEN  entry=%.4f stop=%.4f qty=%s",
                                     symbol, fill_price, stop, fill_qty)

    return position


def _eval_orb(
    symbol: str, df_raw: pd.DataFrame, tctx, acc_id: int,
    position: PaperPosition | None, elog: PaperEventLog, daily: DailyTracker,
    already_entered: bool = False,
) -> PaperPosition | None:
    """Evaluate ORB strategy for one symbol. Supports long and short entries.

    Long: close > or_high + vol_ok + after_cutoff.
    Short: close < or_low + vol_ok + after_cutoff + cfg.orb_shorts_enabled.
    Kill switch: create STOP_SHORTS.txt in project root to disable short entries at runtime.

    already_entered: True if ORB already traded today for this symbol. Enforces the
    one-trade-per-day rule (long OR short) across process restarts (state persisted to disk).
    """
    from datetime import time as dtime

    df = add_all(df_raw.copy())
    last = df.iloc[-1]
    candle_ts = last["time_key"]
    close = float(last["close"])
    bar_time = pd.Timestamp(candle_ts)
    bar_date = bar_time.date()
    bar_clock = bar_time.time()
    now = clock.now_et()
    is_time_stop = bar_clock >= dtime(15, 45)

    orb_mins = cfg.orb_minutes_overrides.get(symbol, cfg.orb_minutes)
    ranges = _build_opening_ranges(df, orb_minutes=orb_mins)
    or_info = ranges.get(bar_date)
    or_valid = or_info is not None and or_info["valid"]

    signals_dict = {
        "or_valid": or_valid,
        "or_high": round(or_info["high"], 4) if or_info else None,
        "or_low": round(or_info["low"], 4) if or_info else None,
        "above_or_high": bool(close > or_info["high"]) if or_info else False,
    }
    log.info("%-8s [orb]    BAR %s  close=%.4f  or_valid=%s", symbol, candle_ts, close, or_valid)
    adx_orb = float(last["adx"]) if "adx" in last and not pd.isna(last.get("adx", float("nan"))) else 0.0
    elog.bar_eval(candle_ts=candle_ts, eval_ts=now, accepted=True,
                  close=close, score=int(or_valid), bonus=0,
                  signals=signals_dict,
                  regime_label="trending" if adx_orb > 25 else "ranging",
                  strategy="orb")

    if position is not None:
        is_short = position.direction == "short"
        exit_reason: str | None = None
        if is_time_stop:
            exit_reason = "TIME_STOP"
        elif position.target_price > 0 and (
            close <= position.target_price if is_short else close >= position.target_price
        ):
            exit_reason = "TARGET"
        elif (close >= position.stop_price if is_short else close <= position.stop_price):
            exit_reason = "STOP"

        if exit_reason:
            fill_price = _execute_exit(tctx, acc_id, symbol, position, close,
                                       exit_reason, elog)
            if fill_price is None:
                return position  # exit unfilled — keep position, retry next poll
            pnl_per_share = (position.entry_price - fill_price) if is_short else (fill_price - position.entry_price)
            pnl_total = pnl_per_share * position.qty
            hold_bars_orb = int((pd.Timestamp(candle_ts) - pd.Timestamp(position.entry_time)).total_seconds() / 300)
            daily.record_trade(pnl_total, strategy="orb")
            _clear_position(symbol, "orb")
            elog.position_close(fill_price, exit_reason, pnl_total, hold_bars=hold_bars_orb,
                                strategy="orb", direction=position.direction, intended_price=close)
            notify_exit(symbol, fill_price, exit_reason, pnl_total)
            log.info("%-8s [orb]    CLOSE [%s] exit=%.4f pnl=%+.4f reason=%s",
                     symbol, position.direction, fill_price, pnl_total, exit_reason)
            position = None

    elif or_valid and not is_time_stop and not already_entered:
        or_high = or_info["high"]
        or_low = or_info["low"]
        or_range = or_high - or_low
        cutoff = dtime(9, 30 + orb_mins) if 30 + orb_mins < 60 else \
                 dtime(10, (30 + orb_mins) % 60)
        vol = float(last.get("volume", 0))
        vol_ma = float(last.get("volume_ma", 1))
        vol_ok = vol > cfg.orb_vol_mult * vol_ma
        after_cutoff = bar_clock >= cutoff
        above_high = close > or_high
        below_low = close < or_low

        # --- Long entry ---
        if above_high and after_cutoff and not vol_ok:
            log.info("%-8s [orb]    SKIP  above_high vol_fail vol=%.0f vol_ma=%.0f ratio=%.2f",
                     symbol, vol, vol_ma, vol / vol_ma if vol_ma else 0)
            elog.signal_skip("orb_vol_fail", score=0, bonus=0, min_score=0, strategy="orb")
        elif above_high and not after_cutoff:
            log.info("%-8s [orb]    SKIP  above_high before_cutoff bar=%s cutoff=%s",
                     symbol, bar_clock, cutoff)
            elog.signal_skip("orb_before_cutoff", score=0, bonus=0, min_score=0, strategy="orb")

        if after_cutoff and above_high and vol_ok:
            if _entry_attempted.get((symbol, "orb")) == str(candle_ts):
                pass  # already tried this candle — don't retry until next bar
            else:
                _entry_attempted[(symbol, "orb")] = str(candle_ts)
                if not daily.can_open(strategy="orb"):
                    elog.risk_block("daily_limit_reached", strategy="orb",
                                    trades=daily.trades, pnl=daily.pnl)
                else:
                    stop = or_low
                    qty = _qty(close, symbol, stop=stop)
                    cap = _position_cap(symbol)
                    if not qty:
                        log.warning("RISK BLOCK [orb] %s: price %.2f exceeds cap %.2f",
                                    symbol, close, cap)
                        elog.risk_block("price_exceeds_max_position", strategy="orb",
                                        price=close, max_dollars=cap)
                    else:
                        target = close + cfg.orb_target_mult * or_range
                        filled = _execute_entry(tctx, acc_id, symbol, qty, close,
                                                "orb", elog)
                        if filled:
                            order_id, fill_price, fill_qty = filled
                            position = PaperPosition(
                                symbol=symbol, strategy="orb", direction="long",
                                entry_time=candle_ts, entry_price=fill_price,
                                stop_price=stop, target_price=target,
                                qty=fill_qty, order_id=order_id,
                            )
                            _save_position(position)
                            elog.position_open(fill_price, stop, fill_qty, strategy="orb",
                                               direction="long", intended_price=close)
                            notify_entry(symbol, fill_price, stop)
                            log.info("%-8s [orb]    OPEN  [long]  entry=%.4f stop=%.4f target=%.4f qty=%s",
                                     symbol, fill_price, stop, target, fill_qty)

        # --- Short entry ---
        elif (after_cutoff and below_low and vol_ok
              and cfg.orb_shorts_enabled
              and not (Path(__file__).parent.parent / "STOP_SHORTS.txt").exists()):
            if _entry_attempted.get((symbol, "orb")) == str(candle_ts):
                pass  # already tried this candle — don't retry until next bar
            else:
                _entry_attempted[(symbol, "orb")] = str(candle_ts)
                if not daily.can_open(strategy="orb"):
                    elog.risk_block("daily_limit_reached", strategy="orb",
                                    trades=daily.trades, pnl=daily.pnl)
                else:
                    stop = or_high
                    qty = math.floor(_qty(close, symbol, stop=stop))  # Moomoo rejects fractional short orders
                    cap = _position_cap(symbol)
                    if not qty:
                        log.warning("RISK BLOCK [orb-short] %s: price %.2f exceeds cap %.2f",
                                    symbol, close, cap)
                        elog.risk_block("price_exceeds_max_position", strategy="orb",
                                        price=close, max_dollars=cap)
                    else:
                        target = close - cfg.orb_target_mult * or_range
                        filled = _execute_entry(tctx, acc_id, symbol, qty, close,
                                                "orb", elog, direction="short")
                        if filled:
                            order_id, fill_price, fill_qty = filled
                            position = PaperPosition(
                                symbol=symbol, strategy="orb", direction="short",
                                entry_time=candle_ts, entry_price=fill_price,
                                stop_price=stop, target_price=target,
                                qty=fill_qty, order_id=order_id,
                            )
                            _save_position(position)
                            elog.position_open(fill_price, stop, fill_qty, strategy="orb",
                                               direction="short", intended_price=close)
                            notify_entry(symbol, fill_price, stop)
                            log.info("%-8s [orb]    OPEN  [short] entry=%.4f stop=%.4f target=%.4f qty=%s",
                                     symbol, fill_price, stop, target, fill_qty)
        elif below_low and after_cutoff and vol_ok and not cfg.orb_shorts_enabled:
            elog.signal_skip("orb_shorts_disabled", score=0, bonus=0, min_score=0, strategy="orb")
        elif below_low and after_cutoff and vol_ok and (Path(__file__).parent.parent / "STOP_SHORTS.txt").exists():
            elog.signal_skip("orb_shorts_kill_switch", score=0, bonus=0, min_score=0, strategy="orb")
        elif below_low and not after_cutoff:
            elog.signal_skip("orb_before_cutoff", score=0, bonus=0, min_score=0, strategy="orb")
        elif below_low and after_cutoff and not vol_ok:
            elog.signal_skip("orb_vol_fail", score=0, bonus=0, min_score=0, strategy="orb")

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
        s = mod.load_summary(clock.today())
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

    # --- Config validation (fail fast on bad .env before touching the broker) ---
    errors = validate_config()
    for msg in errors:
        if msg.startswith("CRITICAL"):
            log.error("CONFIG ERROR: %s", msg)
        else:
            log.warning("CONFIG WARNING: %s", msg)
    if any(e.startswith("CRITICAL") for e in errors):
        log.error("Aborting: critical config error(s). Fix .env and restart.")
        return

    global _slot_dollars
    if cfg.total_capital > 0:
        _slot_dollars = per_slot_dollars(len(symbols), len(strategies))
        mode = f"fractional" if cfg.fractional_shares else "whole-share"
        log.info("Capital mode: TOTAL_CAPITAL=%.2f  slots=%d  per_slot=%.4f  mode=%s",
                 cfg.total_capital, len(symbols) * len(strategies), _slot_dollars, mode)
    else:
        _slot_dollars = 0.0

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
    _session_day: date = clock.today()
    _reconcile_counter: int = 0
    _RECONCILE_EVERY: int = 15  # poll cycles (~15 min)

    for (sym, strat), pos in positions.items():
        if pos:
            elogs[sym].info(
                f"recovered_position entry={pos.entry_price} stop={pos.stop_price} qty={pos.qty}",
                strategy=strat,
            )

    # --- Startup: reconcile local position state against broker ---
    has_local_positions = any(p is not None for p in positions.values())
    if has_local_positions:
        log.info("Local positions found — reconciling against broker state...")
        try:
            with trade_context() as tctx:
                startup_acc_id = _get_simulate_acc_id(tctx)
                _reconcile_positions(tctx, startup_acc_id, positions, elogs)
                acc_id = startup_acc_id
        except Exception as e:
            log.warning("Startup reconciliation failed (%s) — proceeding with local state", e)
    else:
        log.info("No local positions to reconcile — starting fresh")

    while True:
        _is_market_open = clock.is_market_open()
        today = clock.today()

        # New calendar day — heartbeat so you know it's alive
        if today != _session_day:
            _session_day = today
            notify(f"[PAPER] New session {today} | {', '.join(symbols)} | {', '.join(strategies)}")

        # Market just closed — post EOD summary
        if _was_market_open and not _is_market_open:
            _trigger_eod_summary()
        _was_market_open = _is_market_open

        if not _is_market_open:
            secs = clock.seconds_until_open()
            log.info("Market closed — sleeping %.0f min until near open", secs / 60)
            clock.sleep(max(secs, POLL_SECONDS))
            continue

        if not trading_allowed():
            log.info("Trading blocked — waiting")
            clock.sleep(POLL_SECONDS)
            continue

        try:
            with trade_context() as tctx:
                if acc_id is None:
                    acc_id = _get_simulate_acc_id(tctx)

                _reconcile_counter += 1
                if _reconcile_counter >= _RECONCILE_EVERY:
                    _reconcile_counter = 0
                    # Run even with no local positions — catches orphaned broker
                    # positions (e.g. an exit the runner believes happened but didn't).
                    _reconcile_positions(tctx, acc_id, positions, elogs)

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
                clock.sleep(BACKOFF_SECONDS)
                consecutive_errors = 0
                continue
        else:
            consecutive_errors = 0

        clock.sleep(POLL_SECONDS)


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
            already_entered = (orb_traded or {}).get(symbol) == clock.today()
            positions[(symbol, strat)] = _eval_orb(
                symbol, df_raw, tctx, acc_id,
                prev_pos, elog, daily,
                already_entered=already_entered,
            )
            # New position just opened — persist the traded date so restarts can't re-enter
            if prev_pos is None and positions[(symbol, strat)] is not None:
                if orb_traded is not None:
                    orb_traded[symbol] = clock.today()
                    _save_orb_traded(symbol, clock.today())
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
