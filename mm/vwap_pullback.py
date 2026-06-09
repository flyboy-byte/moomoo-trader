"""
VWAP Pullback (Flush-and-Reclaim) strategy.

Entry: 5-min candle wicks below VWAP (low < vwap) but closes above it (close > vwap).
       This is the "flush and reclaim" — institutional buyers defending the VWAP benchmark.

Filters:
  - No-chop: session VWAP cross count <= VWAP_PB_MAX_CROSSES (default 2).
    If price has oscillated through VWAP >2 times today, the level has no structural
    significance and the pullback edge is void.
  - Quiet pullback: volume on the entry bar < volume_ma (no distribution selling).
  - No entry in first 15 min of session (9:30-9:45) — opening volatility.

Exit:
  - VWAP lost: close < vwap (level broken, trend failed)
  - Stop: close < entry - VWAP_PB_STOP_MULT * ATR
  - Time stop: 15:45 ET

This is structurally different from VWAP crossover (which failed):
  - Does NOT enter when price breaks above VWAP (chases momentum)
  - Enters on a test/wick of VWAP with immediate recovery (level respected)
  - Holds while price is above VWAP, exits when VWAP is lost
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time as dtime

import pandas as pd

from .indicators import add_all
from .logger import get_logger

log = get_logger("vwap_pullback")

VWAP_PB_STOP_MULT: float = float(os.getenv("VWAP_PB_STOP_MULT", "0.75"))
VWAP_PB_MAX_CROSSES: int = int(os.getenv("VWAP_PB_MAX_CROSSES", "2"))

_MARKET_OPEN = dtime(9, 30)
_NO_ENTRY_BEFORE = dtime(9, 45)
_TIME_STOP = dtime(15, 45)


@dataclass
class VWAPPBTrade:
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float
    exit_time: pd.Timestamp
    exit_price: float
    exit_reason: str
    pnl: float = field(init=False)

    def __post_init__(self) -> None:
        self.pnl = self.exit_price - self.entry_price


def _add_session_cross_count(df: pd.DataFrame) -> pd.DataFrame:
    """Add vwap_cross_count: cumulative VWAP crosses so far in the session."""
    df = df.copy()
    above = (df["close"] >= df["vwap"]).astype(int)
    same_day = df["time_key"].dt.date == df["time_key"].shift(1).dt.date
    crossed = same_day & (above != above.shift(1).fillna(above))
    dates = df["time_key"].dt.date
    df["vwap_cross_count"] = crossed.groupby(dates).cumsum().astype(int)
    return df


def run_vwap_pullback(
    df: pd.DataFrame,
    stop_mult: float = VWAP_PB_STOP_MULT,
    max_crosses: int = VWAP_PB_MAX_CROSSES,
    min_entry_time: dtime = _NO_ENTRY_BEFORE,
) -> list[VWAPPBTrade]:
    """Stateful backtest pass. Returns list of completed trades."""
    if "vwap" not in df.columns:
        df = add_all(df)
    df = _add_session_cross_count(df)

    trades: list[VWAPPBTrade] = []

    @dataclass
    class Position:
        entry_time: pd.Timestamp
        entry_price: float
        stop_price: float

    position: Position | None = None

    for _, row in df.iterrows():
        if pd.isna(row.get("vwap")) or pd.isna(row.get("atr")):
            continue

        bar_time = pd.Timestamp(row["time_key"])
        bar_clock = bar_time.time()
        close = float(row["close"])
        vwap = float(row["vwap"])
        atr = float(row["atr"])
        is_time_stop = bar_clock >= _TIME_STOP

        if position is not None:
            exit_reason: str | None = None
            if is_time_stop:
                exit_reason = "TIME_STOP"
            elif close < vwap:
                exit_reason = "VWAP_LOST"
            elif close < position.stop_price:
                exit_reason = "STOP"

            if exit_reason:
                trades.append(VWAPPBTrade(
                    entry_time=position.entry_time,
                    entry_price=position.entry_price,
                    stop_price=position.stop_price,
                    exit_time=bar_time,
                    exit_price=close,
                    exit_reason=exit_reason,
                ))
                log.info("VWAP_PB EXIT  bar=%s price=%.4f pnl=%+.4f reason=%s",
                         bar_time, close, trades[-1].pnl, exit_reason)
                position = None
            continue

        # Entry conditions
        if is_time_stop or bar_clock < min_entry_time:
            continue

        wick_below = float(row["low"]) < vwap
        close_above = close > vwap
        no_chop = int(row.get("vwap_cross_count", 0)) <= max_crosses
        quiet_bar = float(row.get("volume", 0)) < float(row.get("volume_ma", float("inf")))

        if wick_below and close_above and no_chop and quiet_bar:
            stop = close - stop_mult * atr
            position = Position(
                entry_time=bar_time,
                entry_price=close,
                stop_price=stop,
            )
            log.info("VWAP_PB ENTRY bar=%s price=%.4f stop=%.4f vwap=%.4f crosses=%d",
                     bar_time, close, stop, vwap, int(row.get("vwap_cross_count", 0)))

    return trades


def print_vwap_pb_summary(trades: list[VWAPPBTrade], symbol: str = "", days: int = 0) -> None:
    if not trades:
        print(f"VWAP Pullback {symbol}: No trades")
        return

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    pf = gross_win / gross_loss if gross_loss else 999.0

    from collections import Counter
    reasons = Counter(t.exit_reason for t in trades)

    freq = f"  ({len(trades)/days:.1f}/day)" if days else ""
    print(f"VWAP Pullback {symbol}")
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
