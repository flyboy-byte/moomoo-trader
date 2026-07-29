"""Per-strategy evaluation functions — one call per (symbol, strategy) per poll.

Contains:
- _entry_attempted   — per-candle dedup dict, prevents 60s retry on same bar
- _kdj_cross_age()   — bars since last KDJ golden cross (telemetry)
- _eval_bb_kdj()     — BB + KDJ mean-reversion strategy
- _eval_vwap()       — VWAP crossover strategy (deprecated, PF≈1.0)
- _eval_vwap_pb()    — VWAP Pullback (flush-and-reclaim)
- _eval_orb()        — Opening Range Breakout (long and short)
"""
import json
import math
from datetime import time as dtime
from pathlib import Path

import pandas as pd

from . import clock
from . import config as _config
from .morning_regime import load_regime_today, load_regime_confidence_today, score_orb_setup
from .events import PaperEventLog, PaperPosition, _save_position, _clear_position
from .execution import _execute_entry, _execute_exit
from .indicators import add_all
from .notifications import notify_entry, notify_exit
from .orb_strategy import _build_opening_ranges
from .risk import calc_qty, calc_qty_risk, DailyTracker, _qty, _position_cap
from .signals import snapshot as signal_snapshot
from .vwap_signals import snapshot_vwap
from .logger import get_logger

log = get_logger("paper")

# Tracks the last candle_ts for which an entry was attempted per (symbol, strategy).
# Prevents the 60s poll from retrying the same failed order on every tick until a new candle arrives.
_entry_attempted: dict[tuple[str, str], str] = {}


def _regime_gate(
    symbol: str,
    strategy: str,
    candle_ts,
    elog: "PaperEventLog",
    sig_score: int,
    bonus: int,
) -> bool:
    """
    Return True if the regime gate blocks entry (caller should skip entry and return position).
    When REGIME_GATE_ENABLED=false, logs a shadow event but always returns False.
    Exits are never gated — only call this inside the entry branch.
    """
    cfg = _config.cfg
    if strategy not in cfg.regime_gate_strategies:
        return False

    bar_date = pd.Timestamp(candle_ts).strftime("%Y-%m-%d")
    regime = load_regime_today(bar_date)
    would_block = regime in cfg.regime_skip_labels

    if not would_block:
        return False

    if cfg.regime_gate_enabled:
        log.info("%-8s [%s] REGIME_BLOCK  regime=%s", symbol, strategy, regime)
        elog.signal_skip("regime_gate", score=sig_score, bonus=bonus,
                         min_score=0, strategy=strategy,
                         regime=regime, gate_enabled=True)
        return True
    else:
        # Shadow mode — log what would happen but don't block
        log.info("%-8s [%s] REGIME_SHADOW  would_block=True regime=%s (gate disabled)",
                 symbol, strategy, regime)
        elog.signal_skip("regime_gate_shadow", score=sig_score, bonus=bonus,
                         min_score=0, strategy=strategy,
                         regime=regime, gate_enabled=False, would_block=True)
        return False


_vix_cache: dict[str, float | None] = {}


def _load_vix_today(date_str: str) -> float | None:
    """Return prior-day VIX close for the given trading date, or None if unavailable.
    Reads logs/vix_daily.jsonl (keyed by trading date). Cached per date."""
    if date_str in _vix_cache:
        return _vix_cache[date_str]
    cfg = _config.cfg
    vix_file = cfg.logs_dir / "vix_daily.jsonl"
    result: float | None = None
    if vix_file.exists():
        try:
            with open(vix_file) as f:
                for line in f:
                    rec = json.loads(line)
                    if rec.get("date") == date_str:
                        result = float(rec["vix_prev_close"])
                        break
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            pass
    _vix_cache[date_str] = result
    return result


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

    cfg = _config.cfg
    if position is None:
        if cfg.strategy_mode == "permissive":
            core_met = bool(last["sig_bb_touch"])
            bonus_met = bonus >= 1
        else:
            effective_window = cfg.kdj_window_overrides.get(symbol, cfg.kdj_window_bars)
            if effective_window > 0:
                # Restrict the lookback to bars from the SAME calendar day as the current
                # candle (bug fix 2026-06-17): df_signals spans multiple fetched days, so a
                # plain tail-slice could pick up a KDJ cross from the tail end of the
                # previous trading day for the first few bars of a new session.
                window = min(effective_window + 1, len(df_signals))
                candle_date = pd.Timestamp(candle_ts).date()
                tail = df_signals.iloc[-window:]
                same_day = pd.to_datetime(tail["time_key"]).dt.date == candle_date
                kdj_met = bool((tail["kdj_golden_cross"] & same_day).any())
            else:
                kdj_met = bool(last["sig_kdj_cross"])
            core_met = bool(last["sig_bb_touch"]) and kdj_met
            bonus_met = bonus >= cfg.min_signal_score

        if _regime_gate(symbol, "bb_kdj", candle_ts, elog, sig.score, bonus):
            return position

        if core_met and bonus_met:
            if _entry_attempted.get((symbol, "bb_kdj")) == str(candle_ts):
                pass
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
            result = _execute_exit(tctx, acc_id, symbol, position, close, exit_reason, elog)
            if result is None:
                return position
            fill_price, dealt_qty = result
            pnl_total = (fill_price - position.entry_price) * dealt_qty
            hold_bars = int((pd.Timestamp(candle_ts) - pd.Timestamp(position.entry_time)).total_seconds() / 300)
            daily.record_trade(pnl_total, strategy="bb_kdj")
            partial = dealt_qty < float(position.qty)
            elog.position_close(fill_price, exit_reason, pnl_total, hold_bars=hold_bars,
                                strategy="bb_kdj", direction="long", intended_price=close,
                                partial_fill=partial, dealt_qty=dealt_qty)
            notify_exit(symbol, fill_price, exit_reason, pnl_total)
            if partial:
                position.qty = position.qty - dealt_qty
                _save_position(position)
                log.warning("%-8s [bb_kdj] PARTIAL CLOSE exit=%.4f pnl=%+.4f reason=%s remaining_qty=%s",
                            symbol, fill_price, pnl_total, exit_reason, position.qty)
            else:
                _clear_position(symbol, "bb_kdj")
                log.info("%-8s [bb_kdj] CLOSE exit=%.4f pnl=%+.4f reason=%s",
                         symbol, fill_price, pnl_total, exit_reason)
                position = None

    return position


def _eval_bb_kdj_loose(
    symbol: str, df_signals: pd.DataFrame, tctx, acc_id: int,
    position: PaperPosition | None, elog: PaperEventLog, daily: DailyTracker,
) -> PaperPosition | None:
    """BB+KDJ with all entry gates relaxed — research lane only.

    Differences from _eval_bb_kdj:
    - No ADX/ranging filter: fires in choppy markets the standard strategy skips.
    - No bonus gate (MIN_SIGNAL_SCORE=0): any BB touch + KDJ cross is enough.
    Same exit logic, same sizing, same candle data. Runs independently as
    strategy='bb_kdj_loose' so its P&L is fully separable from the frozen config.
    """
    last = df_signals.iloc[-1]
    candle_ts = last["time_key"]
    close = float(last["close"])
    now = clock.now_et()

    sig = signal_snapshot(last)
    bonus = int(last["bonus_score"]) if "bonus_score" in last else 0
    bb_lower = round(float(last["bb_lower"]), 4) if "bb_lower" in last else None
    bb_middle = round(float(last["bb_middle"]), 4) if "bb_middle" in last else None
    adx = float(last["adx"]) if "adx" in last and not pd.isna(last["adx"]) else 0.0
    cross_age = _kdj_cross_age(df_signals)
    log.info("%-8s [bb_kdj_loose] BAR %s  close=%.4f  bb_lower=%.4f  score=%d/5  bonus=%d/3  adx=%.1f  %s",
             symbol, candle_ts, close, bb_lower or 0, sig.score, bonus, adx, sig)
    elog.bar_eval(candle_ts=candle_ts, eval_ts=now, accepted=True,
                  close=close, score=sig.score, bonus=bonus,
                  signals={**sig.details, "bb_lower": bb_lower, "bb_middle": bb_middle,
                           "kdj_cross_age": cross_age},
                  regime_label="trending" if adx > 25 else "ranging",
                  strategy="bb_kdj_loose")

    cfg = _config.cfg
    if position is None:
        effective_window = cfg.kdj_window_overrides.get(symbol, cfg.kdj_window_bars)
        if effective_window > 0:
            window = min(effective_window + 1, len(df_signals))
            candle_date = pd.Timestamp(candle_ts).date()
            tail = df_signals.iloc[-window:]
            same_day = pd.to_datetime(tail["time_key"]).dt.date == candle_date
            kdj_met = bool((tail["kdj_golden_cross"] & same_day).any())
        else:
            kdj_met = bool(last["sig_kdj_cross"])
        core_met = bool(last["sig_bb_touch"]) and kdj_met

        if _regime_gate(symbol, "bb_kdj_loose", candle_ts, elog, sig.score, bonus):
            return position

        if core_met:
            if _entry_attempted.get((symbol, "bb_kdj_loose")) == str(candle_ts):
                pass
            else:
                _entry_attempted[(symbol, "bb_kdj_loose")] = str(candle_ts)
                if not daily.can_open(strategy="bb_kdj_loose"):
                    elog.risk_block("daily_limit_reached", strategy="bb_kdj_loose",
                                    trades=daily.trades, pnl=daily.pnl)
                else:
                    stop = close - cfg.atr_stop_mult * float(last["atr"])
                    qty = _qty(close, symbol, stop=stop)
                    cap = _position_cap(symbol)
                    if not qty:
                        log.warning("RISK BLOCK [bb_kdj_loose] %s: price %.2f exceeds cap %.2f",
                                    symbol, close, cap)
                        elog.risk_block("price_exceeds_max_position", strategy="bb_kdj_loose",
                                        price=close, max_dollars=cap)
                    else:
                        filled = _execute_entry(tctx, acc_id, symbol, qty, close,
                                                "bb_kdj_loose", elog)
                        if filled:
                            order_id, fill_price, fill_qty = filled
                            position = PaperPosition(
                                symbol=symbol, strategy="bb_kdj_loose",
                                entry_time=candle_ts, entry_price=fill_price,
                                stop_price=stop, qty=fill_qty, order_id=order_id,
                            )
                            _save_position(position)
                            elog.position_open(fill_price, stop, fill_qty, strategy="bb_kdj_loose",
                                               intended_price=close, kdj_cross_age=cross_age)
                            notify_entry(symbol, fill_price, stop)
                            log.info("%-8s [bb_kdj_loose] OPEN  entry=%.4f stop=%.4f qty=%s",
                                     symbol, fill_price, stop, fill_qty)
    else:
        exit_reason: str | None = None
        if close >= float(last["bb_middle"]):
            exit_reason = "TARGET_BB_MIDDLE"
        elif cfg.exit_on_kdj_death and bool(last["kdj_death_cross"]):
            exit_reason = "KDJ_DEATH_CROSS"
        elif close < position.stop_price:
            exit_reason = "STOP_LOSS"

        if exit_reason:
            result = _execute_exit(tctx, acc_id, symbol, position, close, exit_reason, elog)
            if result is None:
                return position
            fill_price, dealt_qty = result
            pnl_total = (fill_price - position.entry_price) * dealt_qty
            hold_bars = int((pd.Timestamp(candle_ts) - pd.Timestamp(position.entry_time)).total_seconds() / 300)
            daily.record_trade(pnl_total, strategy="bb_kdj_loose")
            partial = dealt_qty < float(position.qty)
            elog.position_close(fill_price, exit_reason, pnl_total, hold_bars=hold_bars,
                                strategy="bb_kdj_loose", direction="long", intended_price=close,
                                partial_fill=partial, dealt_qty=dealt_qty)
            notify_exit(symbol, fill_price, exit_reason, pnl_total)
            if partial:
                position.qty = position.qty - dealt_qty
                _save_position(position)
                log.warning("%-8s [bb_kdj_loose] PARTIAL CLOSE exit=%.4f pnl=%+.4f reason=%s remaining_qty=%s",
                            symbol, fill_price, pnl_total, exit_reason, position.qty)
            else:
                _clear_position(symbol, "bb_kdj_loose")
                log.info("%-8s [bb_kdj_loose] CLOSE exit=%.4f pnl=%+.4f reason=%s",
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

    cfg = _config.cfg
    if position is None:
        entry_ok = (bool(last.get("vwap_entry", False)) and
                    float(last.get("session_return", 0)) > -0.015)
        if entry_ok:
            if _entry_attempted.get((symbol, "vwap")) == str(candle_ts):
                pass
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
        exit_reason: str | None = None
        bar_time = pd.Timestamp(candle_ts).time()
        if bar_time >= dtime(15, 45):
            exit_reason = "TIME_STOP"
        elif close >= float(last["vwap"]):
            exit_reason = "VWAP_TARGET"
        elif close < position.stop_price:
            exit_reason = "VWAP_STOP"

        if exit_reason:
            result = _execute_exit(tctx, acc_id, symbol, position, close, exit_reason, elog)
            if result is None:
                return position
            fill_price, dealt_qty = result
            pnl_total = (fill_price - position.entry_price) * dealt_qty
            hold_bars_vwap = int((pd.Timestamp(candle_ts) - pd.Timestamp(position.entry_time)).total_seconds() / 300)
            daily.record_trade(pnl_total, strategy="vwap")
            partial = dealt_qty < float(position.qty)
            elog.position_close(fill_price, exit_reason, pnl_total, hold_bars=hold_bars_vwap,
                                strategy="vwap", direction="long", intended_price=close,
                                partial_fill=partial, dealt_qty=dealt_qty)
            notify_exit(symbol, fill_price, exit_reason, pnl_total)
            if partial:
                position.qty = position.qty - dealt_qty
                _save_position(position)
                log.warning("%-8s [vwap]   PARTIAL CLOSE exit=%.4f pnl=%+.4f reason=%s remaining_qty=%s",
                            symbol, fill_price, pnl_total, exit_reason, position.qty)
            else:
                _clear_position(symbol, "vwap")
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

    cfg = _config.cfg

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
            result = _execute_exit(tctx, acc_id, symbol, position, close, exit_reason, elog)
            if result is None:
                return position
            fill_price, dealt_qty = result
            pnl_total = (fill_price - position.entry_price) * dealt_qty
            hold_bars_vp = int((pd.Timestamp(candle_ts) - pd.Timestamp(position.entry_time)).total_seconds() / 300)
            daily.record_trade(pnl_total, strategy="vwap_pb")
            partial = dealt_qty < float(position.qty)
            elog.position_close(fill_price, exit_reason, pnl_total, hold_bars=hold_bars_vp,
                                strategy="vwap_pb", direction="long", intended_price=close,
                                partial_fill=partial, dealt_qty=dealt_qty)
            notify_exit(symbol, fill_price, exit_reason, pnl_total)
            if partial:
                position.qty = position.qty - dealt_qty
                _save_position(position)
                log.warning("%-8s [vwap_pb] PARTIAL CLOSE exit=%.4f pnl=%+.4f reason=%s remaining_qty=%s",
                            symbol, fill_price, pnl_total, exit_reason, position.qty)
            else:
                _clear_position(symbol, "vwap_pb")
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
                pass
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
    cfg = _config.cfg

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
    orb_vol_mult = cfg.orb_vol_mult_overrides.get(symbol, cfg.orb_vol_mult)
    orb_target_mult = cfg.orb_target_mult_overrides.get(symbol, cfg.orb_target_mult)
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
            result = _execute_exit(tctx, acc_id, symbol, position, close, exit_reason, elog)
            if result is None:
                return position
            fill_price, dealt_qty = result
            pnl_per_share = (position.entry_price - fill_price) if is_short else (fill_price - position.entry_price)
            pnl_total = pnl_per_share * dealt_qty
            hold_bars_orb = int((pd.Timestamp(candle_ts) - pd.Timestamp(position.entry_time)).total_seconds() / 300)
            daily.record_trade(pnl_total, strategy="orb")
            partial = dealt_qty < float(position.qty)
            elog.position_close(fill_price, exit_reason, pnl_total, hold_bars=hold_bars_orb,
                                strategy="orb", direction=position.direction, intended_price=close,
                                partial_fill=partial, dealt_qty=dealt_qty)
            notify_exit(symbol, fill_price, exit_reason, pnl_total)
            if partial:
                position.qty = position.qty - dealt_qty
                _save_position(position)
                log.warning("%-8s [orb]    PARTIAL CLOSE [%s] exit=%.4f pnl=%+.4f reason=%s remaining_qty=%s",
                            symbol, position.direction, fill_price, pnl_total, exit_reason, position.qty)
            else:
                _clear_position(symbol, "orb")
                log.info("%-8s [orb]    CLOSE [%s] exit=%.4f pnl=%+.4f reason=%s",
                         symbol, position.direction, fill_price, pnl_total, exit_reason)
                position = None

    elif or_valid and not is_time_stop and not already_entered:
        # VIX gate — block all ORB entries on elevated-vol days. Fail-open: missing VIX = proceed.
        effective_vix_max = cfg.orb_vix_max_overrides.get(symbol, cfg.orb_vix_max)
        if effective_vix_max is not None:
            vix_val = _load_vix_today(bar_date.strftime("%Y-%m-%d"))
            if vix_val is not None and vix_val > effective_vix_max:
                log.info("%-8s [orb]    SKIP  orb_vix_block vix=%.2f > max=%.2f",
                         symbol, vix_val, effective_vix_max)
                elog.signal_skip("orb_vix_block", score=0, bonus=0, min_score=0,
                                 strategy="orb", vix=vix_val, threshold=effective_vix_max)
                return position

        or_high = or_info["high"]
        or_low = or_info["low"]
        or_range = or_high - or_low
        cutoff = dtime(9, 30 + orb_mins) if 30 + orb_mins < 60 else \
                 dtime(10, (30 + orb_mins) % 60)
        vol = float(last.get("volume", 0))
        vol_ma = float(last.get("volume_ma", 1))
        vol_ok = vol > orb_vol_mult * vol_ma
        after_cutoff = bar_clock >= cutoff
        above_high = close > or_high
        below_low = close < or_low

        # Late-entry cutoff: skip new entries after ORB_LATEST_ENTRY (e.g. "13:00" ET).
        if cfg.orb_latest_entry:
            h, m = (int(x) for x in cfg.orb_latest_entry.split(":"))
            if bar_clock >= dtime(h, m):
                if above_high or below_low:
                    log.info("%-8s [orb]    SKIP  orb_too_late bar=%s latest=%s",
                             symbol, bar_clock, cfg.orb_latest_entry)
                    elog.signal_skip("orb_too_late", score=0, bonus=0, min_score=0, strategy="orb")
                return position

        # ORB setup scorer — per-trade Claude confidence gate.
        # Runs when scorer is enabled; set ORB_SETUP_SCORER_ENABLED=false to disable entirely.
        if cfg.anthropic_api_key and cfg.orb_setup_scorer_enabled:
            direction = "LONG" if above_high else ("SHORT" if below_low else None)
            if direction and after_cutoff and vol_ok:
                date_str_score = bar_date.strftime("%Y-%m-%d")
                vix_for_score = _load_vix_today(date_str_score)
                morning_regime = load_regime_today(date_str_score)
                morning_regime_confidence = load_regime_confidence_today(date_str_score)
                open_time = bar_time.replace(hour=9, minute=30, second=0, microsecond=0)
                setup = {
                    "date": date_str_score,
                    "direction": direction,
                    "or_range_pct": round(or_range / close * 100, 3),
                    "vol_ratio": round(vol / vol_ma if vol_ma else 0, 2),
                    "vix": vix_for_score,
                    "regime": morning_regime,
                    "regime_confidence": morning_regime_confidence,
                    "mins_since_open": int((bar_time - open_time).total_seconds() / 60),
                }
                scored = score_orb_setup(symbol, str(candle_ts), setup)
                confidence = scored["confidence"]
                if confidence < cfg.orb_entry_min_confidence:
                    log.info("%-8s [orb]    SKIP  orb_claude_score=%.2f < min=%.2f  %s",
                             symbol, confidence, cfg.orb_entry_min_confidence, scored["reason"])
                    elog.signal_skip("orb_claude_score", score=0, bonus=0, min_score=0,
                                     strategy="orb", confidence=confidence,
                                     claude_reason=scored["reason"])
                    return position
                else:
                    log.info("%-8s [orb]    SCORE  confidence=%.2f  %s",
                             symbol, confidence, scored["reason"])

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
                pass
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
                        target = close + orb_target_mult * or_range
                        entry_limit = round(close * 1.001, 2)
                        filled = _execute_entry(tctx, acc_id, symbol, qty, entry_limit,
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
              and (not cfg.orb_short_symbols or symbol in cfg.orb_short_symbols)
              and not (Path(__file__).parent.parent / "STOP_SHORTS.txt").exists()):
            if _entry_attempted.get((symbol, "orb")) == str(candle_ts):
                pass
            else:
                _entry_attempted[(symbol, "orb")] = str(candle_ts)
                if not daily.can_open(strategy="orb"):
                    elog.risk_block("daily_limit_reached", strategy="orb",
                                    trades=daily.trades, pnl=daily.pnl)
                else:
                    stop = or_high
                    qty = math.floor(_qty(close, symbol, stop=stop))
                    cap = _position_cap(symbol)
                    if not qty:
                        log.warning("RISK BLOCK [orb-short] %s: price %.2f exceeds cap %.2f",
                                    symbol, close, cap)
                        elog.risk_block("price_exceeds_max_position", strategy="orb",
                                        price=close, max_dollars=cap)
                    else:
                        target = close - orb_target_mult * or_range
                        entry_limit = round(close * 0.999, 2)
                        filled = _execute_entry(tctx, acc_id, symbol, qty, entry_limit,
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
        elif below_low and after_cutoff and vol_ok and cfg.orb_short_symbols and symbol not in cfg.orb_short_symbols:
            elog.signal_skip("orb_shorts_symbol_excluded", score=0, bonus=0, min_score=0, strategy="orb")
        elif below_low and after_cutoff and vol_ok and (Path(__file__).parent.parent / "STOP_SHORTS.txt").exists():
            elog.signal_skip("orb_shorts_kill_switch", score=0, bonus=0, min_score=0, strategy="orb")
        elif below_low and not after_cutoff:
            elog.signal_skip("orb_before_cutoff", score=0, bonus=0, min_score=0, strategy="orb")
        elif below_low and after_cutoff and not vol_ok:
            elog.signal_skip("orb_vol_fail", score=0, bonus=0, min_score=0, strategy="orb")

    return position


def _eval_gap_fade(
    symbol: str, df_raw: pd.DataFrame, tctx, acc_id: int,
    position: PaperPosition | None, elog: PaperEventLog, daily: DailyTracker,
    already_entered: bool = False,
) -> PaperPosition | None:
    """Evaluate Gap Fade strategy for one symbol.

    Fires once per day at the 9:35 ET bar. Fades the opening gap:
    - Gap up + first-bar rejection (close < open) → short
    - Gap down + first-bar rejection (close > open) → long

    already_entered: True if gap_fade already traded today (one trade per day).
    """
    from .gap_fade import (GAP_MIN_PCT, GAP_MAX_PCT, GAP_TARGET_FILL_PCT,
                           GAP_STOP_BUFFER, GAP_SHORTS_ENABLED)

    cfg = _config.cfg

    df = add_all(df_raw.copy())
    last = df.iloc[-1]
    candle_ts = last["time_key"]
    close = float(last["close"])
    bar_time = pd.Timestamp(candle_ts)
    bar_date = bar_time.date()
    bar_clock = bar_time.time()
    now = clock.now_et()

    is_entry_bar = bar_clock == dtime(9, 35)
    is_time_stop = bar_clock >= dtime(11, 0)

    log.info("%-8s [gap_fade] BAR %s  close=%.4f", symbol, candle_ts, close)
    elog.bar_eval(candle_ts=candle_ts, eval_ts=now, accepted=True,
                  close=close, score=0, bonus=0, signals={},
                  regime_label="n/a", strategy="gap_fade")

    # --- Exit ---
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
            result = _execute_exit(tctx, acc_id, symbol, position, close, exit_reason, elog)
            if result is None:
                return position
            fill_price, dealt_qty = result
            pnl_per_share = (position.entry_price - fill_price) if is_short else (fill_price - position.entry_price)
            pnl_total = pnl_per_share * dealt_qty
            hold_bars = int((pd.Timestamp(candle_ts) - pd.Timestamp(position.entry_time)).total_seconds() / 300)
            daily.record_trade(pnl_total, strategy="gap_fade")
            partial = dealt_qty < float(position.qty)
            elog.position_close(fill_price, exit_reason, pnl_total, hold_bars=hold_bars,
                                strategy="gap_fade", direction=position.direction, intended_price=close,
                                partial_fill=partial, dealt_qty=dealt_qty)
            notify_exit(symbol, fill_price, exit_reason, pnl_total)
            if partial:
                position.qty = position.qty - dealt_qty
                _save_position(position)
                log.warning("%-8s [gap_fade] PARTIAL CLOSE [%s] exit=%.4f pnl=%+.4f reason=%s remaining=%s",
                            symbol, position.direction, fill_price, pnl_total, exit_reason, position.qty)
            else:
                _clear_position(symbol, "gap_fade")
                log.info("%-8s [gap_fade] CLOSE [%s] exit=%.4f pnl=%+.4f reason=%s",
                         symbol, position.direction, fill_price, pnl_total, exit_reason)
                position = None

    # --- Entry (9:35 bar only, one trade per day) ---
    elif is_entry_bar and not already_entered:
        # VIX gate — block entries when prior-day VIX > per-symbol threshold
        effective_gap_vix_max = cfg.gap_vix_max_overrides.get(symbol, cfg.gap_vix_max)
        if effective_gap_vix_max is not None:
            vix_val = _load_vix_today(bar_date.strftime("%Y-%m-%d"))
            if vix_val is not None and vix_val > effective_gap_vix_max:
                log.info("%-8s [gap_fade] SKIP  gap_vix_block vix=%.2f > max=%.2f",
                         symbol, vix_val, effective_gap_vix_max)
                elog.signal_skip("gap_vix_block", score=0, bonus=0, min_score=0,
                                 strategy="gap_fade", vix=vix_val,
                                 threshold=effective_gap_vix_max)
                return position

        # Derive prev_close from the last bar of the prior trading day in the window
        df["_ts_tmp"] = pd.to_datetime(df["time_key"])
        df["_date_tmp"] = df["_ts_tmp"].dt.date
        prev_day_df = df[df["_date_tmp"] < bar_date]
        if prev_day_df.empty:
            return position

        prev_close = float(prev_day_df.iloc[-1]["close"])
        today_open = float(last["open"])
        first_high = float(last["high"])
        first_low = float(last["low"])

        gap_pct = (today_open - prev_close) / prev_close

        if abs(gap_pct) < GAP_MIN_PCT or abs(gap_pct) > GAP_MAX_PCT:
            elog.signal_skip("gap_out_of_range", score=0, bonus=0, min_score=0, strategy="gap_fade")
            return position

        direction: str | None = None
        stop: float = 0.0
        target: float = 0.0

        if gap_pct > 0 and close < today_open and GAP_SHORTS_ENABLED:
            direction = "short"
            stop = round(first_high * (1 + GAP_STOP_BUFFER), 4)
            target = round(today_open - GAP_TARGET_FILL_PCT * (today_open - prev_close), 4)
        elif gap_pct < 0 and close > today_open:
            direction = "long"
            stop = round(first_low * (1 - GAP_STOP_BUFFER), 4)
            target = round(today_open + GAP_TARGET_FILL_PCT * (prev_close - today_open), 4)

        if direction is None:
            elog.signal_skip("gap_no_rejection", score=0, bonus=0, min_score=0, strategy="gap_fade")
            return position

        if _entry_attempted.get((symbol, "gap_fade")) == str(candle_ts):
            return position
        _entry_attempted[(symbol, "gap_fade")] = str(candle_ts)

        if not daily.can_open(strategy="gap_fade"):
            elog.risk_block("daily_limit_reached", strategy="gap_fade",
                            trades=daily.trades, pnl=daily.pnl)
            return position

        qty = _qty(close, symbol, stop=stop)
        if not qty:
            log.warning("RISK BLOCK [gap_fade] %s: price %.2f exceeds cap %.2f",
                        symbol, close, _position_cap(symbol))
            elog.risk_block("price_exceeds_max_position", strategy="gap_fade",
                            price=close, max_dollars=_position_cap(symbol))
            return position

        if direction == "short":
            qty = math.floor(qty)

        filled = _execute_entry(tctx, acc_id, symbol, qty, close,
                                "gap_fade", elog, direction=direction)
        if filled:
            order_id, fill_price, fill_qty = filled
            position = PaperPosition(
                symbol=symbol, strategy="gap_fade", direction=direction,
                entry_time=candle_ts, entry_price=fill_price,
                stop_price=stop, target_price=target,
                qty=fill_qty, order_id=order_id,
            )
            _save_position(position)
            elog.position_open(fill_price, stop, fill_qty, strategy="gap_fade",
                               direction=direction, intended_price=close)
            notify_entry(symbol, fill_price, stop)
            log.info("%-8s [gap_fade] OPEN  [%s]  entry=%.4f stop=%.4f target=%.4f qty=%s  gap=%+.3f%%",
                     symbol, direction, fill_price, stop, target, fill_qty, gap_pct * 100)

    return position
