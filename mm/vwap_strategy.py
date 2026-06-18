"""
VWAP momentum strategy — trade WITH VWAP direction.

Entry:  close crosses above VWAP from below (cross_up)
        AND volume > 1.2× MA (real participation)
        AND session return > -1.5% (no longs on strong down days)

Exit:   close crosses back below VWAP (momentum failed)
     OR close < entry_price - VWAP_STOP_MULT × ATR (hard stop)
     OR time >= 15:45 ET (time stop — never hold overnight)
"""
from dataclasses import dataclass, field
from datetime import time as dtime
from enum import Enum, auto

import pandas as pd

from . import config as _config
from .indicators import add_all
from .logger import get_logger
from .vwap_signals import score_vwap

log = get_logger("vwap_strategy")

_SESSION_RETURN_MIN: float = -0.015  # -1.5% directional filter
_TIME_STOP: dtime = dtime(15, 45)    # 3:45 PM ET


class VWAPSignal(Enum):
    NONE = auto()
    ENTRY = auto()
    EXIT_TARGET = auto()
    EXIT_STOP = auto()
    EXIT_TIME = auto()


@dataclass
class VWAPPosition:
    entry_idx: int
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float


@dataclass
class VWAPTrade:
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    exit_reason: str
    pnl: float = field(init=False)

    def __post_init__(self) -> None:
        self.pnl = self.exit_price - self.entry_price


def compute_vwap_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Add all indicator + VWAP signal columns to a candle DataFrame."""
    df = add_all(df)
    df = score_vwap(df)

    # Session return filter: compare each bar's close to the session open (first bar of the day)
    dates = pd.to_datetime(df["time_key"]).dt.date
    session_open = df.groupby(dates)["close"].transform("first")
    df["session_return"] = (df["close"] - session_open) / session_open.replace(0, float("nan"))

    signals = pd.Series(VWAPSignal.NONE, index=df.index, name="vwap_signal")
    # vwap_entry = cross_up + vol_confirm; session_return filter blocks strong down days
    entry_mask = df["vwap_entry"] & (df["session_return"] > _SESSION_RETURN_MIN)
    signals[entry_mask] = VWAPSignal.ENTRY
    df["vwap_signal"] = signals
    return df


def run_vwap_signals(
    df: pd.DataFrame,
    stop_mult: float | None = None,
) -> tuple[list[VWAPTrade], pd.DataFrame]:
    """Stateful bar-by-bar pass. Returns (trades, annotated_df).

    stop_mult overrides cfg.vwap_stop_mult — pass explicitly from sweeps that
    need a value different from whatever's currently in mm.config.
    """
    _stop_mult = stop_mult if stop_mult is not None else _config.cfg.vwap_stop_mult
    df = compute_vwap_signals(df)
    position: VWAPPosition | None = None
    trades: list[VWAPTrade] = []

    for i, row in df.iterrows():
        bar_time = pd.Timestamp(row["time_key"])
        is_time_stop = bar_time.time() >= _TIME_STOP

        if position is None:
            if row["vwap_signal"] == VWAPSignal.ENTRY and not is_time_stop:
                stop = row["close"] - _stop_mult * row["atr"]  # hard floor below entry
                position = VWAPPosition(
                    entry_idx=i,
                    entry_time=bar_time,
                    entry_price=row["close"],
                    stop_price=stop,
                )
                df.at[i, "vwap_signal"] = VWAPSignal.ENTRY
                log.info("VWAP ENTRY  bar=%s price=%.4f stop=%.4f vwap=%.4f",
                         bar_time, row["close"], stop, row["vwap"])
        else:
            exit_sig: VWAPSignal | None = None

            if is_time_stop:
                exit_sig = VWAPSignal.EXIT_TIME
            elif row["close"] < position.stop_price:
                exit_sig = VWAPSignal.EXIT_STOP

            # VWAP cross back down = primary exit (momentum failed)
            if exit_sig is None and row["close"] < row["vwap"]:
                exit_sig = VWAPSignal.EXIT_TARGET  # reuse EXIT_TARGET for VWAP cross-down exit

            if exit_sig is not None:
                df.at[i, "vwap_signal"] = exit_sig
                trade = VWAPTrade(
                    entry_time=position.entry_time,
                    entry_price=position.entry_price,
                    exit_time=bar_time,
                    exit_price=row["close"],
                    exit_reason=exit_sig.name,
                )
                trades.append(trade)
                log.info("VWAP EXIT   bar=%s price=%.4f pnl=%+.4f reason=%s",
                         bar_time, row["close"], trade.pnl, exit_sig.name)
                position = None

    return trades, df


def print_vwap_summary(trades: list[VWAPTrade], df: pd.DataFrame | None = None) -> None:
    if not trades:
        print("No VWAP trades.")
        return

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    pf = gross_win / gross_loss if gross_loss else float("inf")
    avg_hold = sum(
        (t.exit_time - t.entry_time).total_seconds() / 60
        for t in trades
    ) / len(trades)

    # Trades per day
    if df is not None:
        dates = pd.to_datetime(df["time_key"]).dt.date.unique()
        trading_days = len(dates)
        trades_per_day = len(trades) / trading_days if trading_days else 0
    else:
        trades_per_day = 0
        trading_days = 0

    targets = sum(1 for t in trades if t.exit_reason == "EXIT_TARGET")
    stops = sum(1 for t in trades if t.exit_reason == "EXIT_STOP")
    time_stops = sum(1 for t in trades if t.exit_reason == "EXIT_TIME")

    print("VWAP Strategy Summary")
    print(f"  Trades:        {len(trades)}  ({trades_per_day:.1f}/day over {trading_days} days)")
    print(f"  Win rate:      {len(wins)/len(trades)*100:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Total PnL:     ${total_pnl:+.2f}")
    print(f"  Profit factor: {pf:.3f}")
    print(f"  Avg hold:      {avg_hold:.0f} min")
    print(f"  Exits:         {targets} target / {stops} stop / {time_stops} time")
    if trades:
        best = max(trades, key=lambda t: t.pnl)
        worst = min(trades, key=lambda t: t.pnl)
        print(f"  Best:          ${best.pnl:+.4f}  Worst: ${worst.pnl:+.4f}")
