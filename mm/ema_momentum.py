"""
EMA Momentum Breakout strategy — backtest engine only.

Entry: EMA5 crosses above EMA20 (golden cross) with ADX > adx_min (trending regime)
       and volume above the 20-bar MA (real participation).
       Session filter: 10:00–15:00 ET only — avoids open volatility and late-day decay.

Exit:
  - Target: close >= entry + target_mult × ATR
  - Stop:   close < EMA20 (trend structure broken) OR close < entry - stop_mult × ATR
  - Time stop: 15:45 ET

Design notes:
  - EMA5/EMA20 cross on 5-min fires in trending sessions (ADX>25), complementing
    BB+KDJ which fires in ranging sessions (ADX<25). No overlap in regime.
  - Raw cross entry can chase; a pullback-to-EMA5 variant is included in the sweep
    (entry_type="pullback": EMA5>EMA20 already AND close touches EMA5 from above).
  - Not wired into the paper runner — backtest and validate first.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time as dtime

import pandas as pd

from .indicators import add_all
from .logger import get_logger
from .backtest import profit_factor as _profit_factor  # canonical PF, never redefine

log = get_logger("ema_momentum")

EMA_TARGET_MULT: float = float(os.getenv("EMA_TARGET_MULT", "1.0"))
EMA_STOP_MULT: float = float(os.getenv("EMA_STOP_MULT", "1.0"))
EMA_ADX_MIN: float = float(os.getenv("EMA_ADX_MIN", "25.0"))

_SESSION_START = dtime(10, 0)
_TIME_STOP = dtime(15, 45)
_NO_ENTRY_AFTER = dtime(15, 0)


@dataclass
class EMAMomentumTrade:
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float
    exit_time: pd.Timestamp
    exit_price: float
    exit_reason: str
    entry_type: str  # "cross" or "pullback"
    pnl: float = field(init=False)

    def __post_init__(self) -> None:
        self.pnl = self.exit_price - self.entry_price


def run_ema_momentum(
    df: pd.DataFrame,
    target_mult: float = EMA_TARGET_MULT,
    stop_mult: float = EMA_STOP_MULT,
    adx_min: float = EMA_ADX_MIN,
    entry_type: str = "cross",  # "cross" | "pullback"
) -> list[EMAMomentumTrade]:
    """Stateful backtest pass. Returns list of completed trades.

    entry_type="cross":    enter on the bar where EMA5 first crosses above EMA20.
    entry_type="pullback": enter when EMA5>EMA20 and close pulls back to touch EMA5
                           (close <= ema5 and prior close > ema5).
    """
    if "ema5" not in df.columns:
        df = add_all(df)

    trades: list[EMAMomentumTrade] = []

    @dataclass
    class Position:
        entry_time: pd.Timestamp
        entry_price: float
        stop_price: float
        target_price: float
        entry_type: str

    position: Position | None = None
    ema5 = df["ema5"]
    ema20 = df["ema20"]

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        if pd.isna(row.get("atr")) or pd.isna(row.get("adx")):
            continue

        bar_time = pd.Timestamp(row["time_key"])
        bar_clock = bar_time.time()
        close = float(row["close"])
        atr = float(row["atr"])
        e5 = float(ema5.iloc[i])
        e20 = float(ema20.iloc[i])
        is_time_stop = bar_clock >= _TIME_STOP

        if position is not None:
            exit_reason: str | None = None
            if is_time_stop:
                exit_reason = "TIME_STOP"
            elif close >= position.target_price:
                exit_reason = "TARGET"
            elif close < e20:
                exit_reason = "EMA20_BREAK"
            elif close < position.stop_price:
                exit_reason = "STOP"

            if exit_reason:
                trades.append(EMAMomentumTrade(
                    entry_time=position.entry_time,
                    entry_price=position.entry_price,
                    stop_price=position.stop_price,
                    exit_time=bar_time,
                    exit_price=close,
                    exit_reason=exit_reason,
                    entry_type=position.entry_type,
                ))
                log.debug("EMA EXIT  %s  price=%.4f  pnl=%+.4f  reason=%s",
                          bar_time, close, trades[-1].pnl, exit_reason)
                position = None
            continue

        if is_time_stop or bar_clock < _SESSION_START or bar_clock >= _NO_ENTRY_AFTER:
            continue

        trending = float(row.get("adx", 0)) > adx_min
        vol_ok = float(row.get("volume", 0)) > float(row.get("volume_ma", 0))
        if not trending or not vol_ok:
            continue

        e5_prev = float(ema5.iloc[i - 1])
        e20_prev = float(ema20.iloc[i - 1])

        signal = False
        etype = entry_type
        if entry_type == "cross":
            signal = (e5 > e20) and (e5_prev <= e20_prev)
        elif entry_type == "pullback":
            above_cross = (e5 > e20) and (e5_prev > e20_prev)
            pullback = (close <= e5) and (float(prev["close"]) > float(prev["ema5"]))
            signal = above_cross and pullback

        if signal:
            stop = min(e20, close - stop_mult * atr)
            target = close + target_mult * atr
            position = Position(
                entry_time=bar_time,
                entry_price=close,
                stop_price=stop,
                target_price=target,
                entry_type=etype,
            )
            log.debug("EMA ENTRY bar=%s type=%s price=%.4f stop=%.4f target=%.4f adx=%.1f",
                      bar_time, etype, close, stop, target, float(row["adx"]))

    return trades


def print_ema_summary(
    trades: list[EMAMomentumTrade],
    symbol: str = "",
    days: int = 0,
) -> None:
    if not trades:
        print(f"EMA Momentum {symbol}: No trades")
        return

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    # Canonical PF (mm/backtest.py) — see the note in mm/vwap_pullback.py. Same
    # surviving `999.0` sentinel, same cause.
    pf = _profit_factor(trades)

    from collections import Counter
    reasons = Counter(t.exit_reason for t in trades)

    freq = f"  ({len(trades)/days:.1f}/day)" if days else ""
    print(f"EMA Momentum {symbol}")
    print(f"  Trades:        {len(trades)}{freq}")
    print(f"  Win rate:      {100*len(wins)/len(trades):.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Total PnL:     ${total_pnl:+.2f}")
    print(f"  Profit factor: {pf:.3f}")
    avg_hold = sum(
        (pd.Timestamp(t.exit_time) - pd.Timestamp(t.entry_time)).total_seconds() / 60
        for t in trades
    ) / len(trades)
    print(f"  Avg hold:      {avg_hold:.0f} min")
    print(f"  Exits:         {dict(reasons)}")
