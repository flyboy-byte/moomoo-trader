"""
Signal generation for the BB + KDJ mean-reversion strategy.

Entry:  close <= bb_lower  AND  KDJ golden cross on this bar
Exit:   close >= bb_middle  (target)
     OR close < entry_price - 1 * ATR  (stop loss)
     OR KDJ death cross  (only if EXIT_ON_KDJ_DEATH=true in .env)

Research note: backtesting 2022-2025 shows the KDJ death cross exit cuts winning
mean-reversion trades before they reach the BB middle. Disabling it (default) improves
win rate from 27% → 41% and flips total PnL from negative to positive.
"""
from dataclasses import dataclass, field
from enum import Enum, auto

import pandas as pd

from . import config as _config
from .indicators import add_all
from .signals import score_df
from .logger import get_logger

log = get_logger("strategy")


class Signal(Enum):
    NONE = auto()
    ENTRY = auto()
    EXIT_TARGET = auto()
    EXIT_DEATH_CROSS = auto()
    EXIT_STOP_LOSS = auto()


@dataclass
class Position:
    entry_idx: int
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float


@dataclass
class Trade:
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    exit_reason: str
    risk: float = 0.0  # initial risk per share (entry − stop); 0 = unknown
    pnl: float = field(init=False)

    def __post_init__(self) -> None:
        self.pnl = self.exit_price - self.entry_price

    @property
    def r_mult(self) -> float | None:
        """PnL as a multiple of initial risk — size-independent."""
        return self.pnl / self.risk if self.risk > 0 else None

    @property
    def bps(self) -> float:
        """Return on notional in basis points — comparable against slippage cost."""
        return self.pnl / self.entry_price * 10000


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Add indicator + signal columns to a candle DataFrame.

    Input must have: open, high, low, close, volume columns.
    Returns df enriched with all indicator, sig_*, signal_score, and signal columns.
    """
    # Bug fix 2026-06-18: must re-fetch cfg at call time (module ref pattern, see
    # CLAUDE.md) — `from .config import cfg` would bind once at import and go
    # stale after any test/replay reload of mm.config. mm/evals.py already does
    # this correctly; this module didn't, until a new test caught the staleness.
    cfg = _config.cfg
    df = add_all(df)
    df = score_df(df)

    # Core mean-reversion gate: price at BB lower AND KDJ momentum turning.
    # KDJ_WINDOW_BARS: if > 0, accept a KDJ cross from any of the last N bars (not just same-bar).
    # Sweep on IWM+QQQ 2022-2025 showed w=3 gives 10x more signals while improving OOS PF.
    # Grouped by calendar day (bug fix 2026-06-17): a plain .rolling() over a multi-day frame
    # lets the window for the first N bars of a new trading day see KDJ crosses from the tail
    # end of the PREVIOUS day, firing on a stale cross instead of a same-session one. Per-day
    # grouping makes the window reset at every session boundary, matching the documented intent
    # ("KDJ cross within N bars" implicitly means N bars of THIS session).
    if cfg.kdj_window_bars > 0:
        day_key = pd.to_datetime(df["time_key"]).dt.date
        kdj_in_window = (
            df["sig_kdj_cross"]
            .groupby(day_key)
            .transform(lambda s: s.rolling(window=cfg.kdj_window_bars + 1, min_periods=1).max())
            .fillna(False)
            .astype(bool)
        )
    else:
        kdj_in_window = df["sig_kdj_cross"].astype(bool)
    core_gate = df["sig_bb_touch"] & kdj_in_window
    # bonus_score counts additional independent confirmations (RSI, ADX regime, volume).
    # Entry requires core gate AND bonus_score >= min_signal_score.
    # min_signal_score=0 restores original BB+KDJ-only behaviour.
    bonus_cols = ["sig_rsi_oversold", "sig_ranging", "sig_volume_spike"]
    df["bonus_score"] = df[bonus_cols].sum(axis=1).astype(int)
    entry_mask = core_gate & (df["bonus_score"] >= cfg.min_signal_score)

    signals = pd.Series(Signal.NONE, index=df.index, name="signal")
    signals[entry_mask] = Signal.ENTRY
    df["signal"] = signals
    return df


def run_signals(df: pd.DataFrame, blocked_hours: set[int] | None = None) -> pd.DataFrame:
    """Stateful pass: apply entry/exit logic bar-by-bar and record open signals.

    blocked_hours: set of ET hours (0-23) where new entries are suppressed.
    Exits always fire regardless of time — only entries are filtered.
    Returns df with 'signal' column updated to reflect exit reasons as well.
    """
    cfg = _config.cfg  # see compute_signals() for why this is re-fetched at call time
    df = compute_signals(df)
    position: Position | None = None

    for i, row in df.iterrows():
        if position is None:
            hour = pd.Timestamp(row["time_key"]).hour
            if row["signal"] == Signal.ENTRY and (not blocked_hours or hour not in blocked_hours):
                position = Position(
                    entry_idx=i,
                    entry_time=row["time_key"],
                    entry_price=row["close"],
                    stop_price=row["close"] - cfg.atr_stop_mult * row["atr"],
                )
                log.info(
                    "ENTRY  bar=%s price=%.4f stop=%.4f",
                    row["time_key"],
                    position.entry_price,
                    position.stop_price,
                )
        else:
            exit_signal: Signal | None = None

            if row["close"] >= row["bb_middle"]:
                exit_signal = Signal.EXIT_TARGET
            elif cfg.exit_on_kdj_death and row["kdj_death_cross"]:
                exit_signal = Signal.EXIT_DEATH_CROSS
            elif row["close"] < position.stop_price:
                exit_signal = Signal.EXIT_STOP_LOSS

            if exit_signal is not None:
                df.at[i, "signal"] = exit_signal
                log.info(
                    "EXIT   bar=%s price=%.4f reason=%s",
                    row["time_key"],
                    row["close"],
                    exit_signal.name,
                )
                position = None

    return df
