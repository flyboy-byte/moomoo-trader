"""
Opening Range Breakout (ORB) strategy.

Opening range: first ORB_MINUTES of session (default 30 min = 9:30-10:00 ET).
Entry: 5-min close above OR high (long) or below OR low (short).
Stop:  opposite OR boundary.
Target: ORB_TARGET_MULT × range height from entry (default 1.0×).
Time stop: 15:45 ET — no new entries after ORB_CUTOFF_HOUR:ORB_CUTOFF_MIN.

Filters:
  - OR range must be >= ORB_MIN_RANGE_PCT × close (avoids tiny flat opens)
  - OR range must be <= ORB_MAX_RANGE_PCT × close (avoids news-spike gaps)
  - Volume on breakout bar > ORB_VOL_MULT × 20-bar volume MA
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time as dtime

import pandas as pd

from .indicators import add_all
from .logger import get_logger

log = get_logger("orb_strategy")

ORB_MINUTES: int = int(os.getenv("ORB_MINUTES", "30"))        # opening range window
ORB_TARGET_MULT: float = float(os.getenv("ORB_TARGET_MULT", "1.5"))  # target = mult × range
ORB_VOL_MULT: float = float(os.getenv("ORB_VOL_MULT", "1.2"))
ORB_MIN_RANGE_PCT: float = float(os.getenv("ORB_MIN_RANGE_PCT", "0.001"))  # 0.1% min
ORB_MAX_RANGE_PCT: float = float(os.getenv("ORB_MAX_RANGE_PCT", "0.008"))  # 0.8% max
_MARKET_OPEN = dtime(9, 30)
_TIME_STOP = dtime(15, 45)


@dataclass
class ORBTrade:
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    exit_reason: str
    direction: str  # "long" or "short"
    or_high: float
    or_low: float
    pnl: float = field(init=False)

    def __post_init__(self) -> None:
        if self.direction == "long":
            self.pnl = self.exit_price - self.entry_price
        else:
            self.pnl = self.entry_price - self.exit_price


@dataclass
class ORBDay:
    date: object
    or_high: float = 0.0
    or_low: float = float("inf")
    or_close: float = 0.0  # last bar of OR period (for range pct calc)
    or_complete: bool = False
    bars_in_or: int = 0
    entered: bool = False   # one trade per day max


def _build_opening_ranges(df: pd.DataFrame, orb_minutes: int | None = None) -> dict:
    """Compute OR high/low for each trading day from the first orb_minutes of bars.

    orb_minutes defaults to the ORB_MINUTES env var when not supplied. Pass explicitly
    to support per-symbol overrides in the paper runner.
    """
    if orb_minutes is None:
        orb_minutes = ORB_MINUTES
    ranges: dict = {}
    dates = pd.to_datetime(df["time_key"]).dt.date

    for date, group in df.groupby(dates):
        group_times = pd.to_datetime(group["time_key"]).dt.time
        or_mask = group_times < dtime(9, 30 + orb_minutes) if 30 + orb_minutes < 60 else \
                  group_times < dtime(10, (30 + orb_minutes) % 60)
        or_bars = group[or_mask]
        if or_bars.empty:
            continue
        or_high = float(or_bars["high"].max())
        or_low = float(or_bars["low"].min())
        or_close = float(or_bars.iloc[-1]["close"])
        range_pct = (or_high - or_low) / or_close if or_close else 0
        valid = ORB_MIN_RANGE_PCT <= range_pct <= ORB_MAX_RANGE_PCT
        ranges[date] = {"high": or_high, "low": or_low, "close": or_close,
                        "range_pct": range_pct, "valid": valid}
    return ranges


def run_orb_signals(
    df: pd.DataFrame,
    vol_mult: float = ORB_VOL_MULT,
    orb_minutes: int | None = None,
    target_mult: float = ORB_TARGET_MULT,
) -> tuple[list[ORBTrade], pd.DataFrame]:
    """Stateful bar-by-bar ORB evaluation. Returns (trades, annotated_df)."""
    df = add_all(df)
    df = df.copy()
    df["orb_signal"] = "none"

    ranges = _build_opening_ranges(df, orb_minutes=orb_minutes)
    trades: list[ORBTrade] = []
    position: dict | None = None  # {entry, stop, target, direction, or_high, or_low}
    entered_today: set = set()

    dates = pd.to_datetime(df["time_key"]).dt.date

    for i, row in df.iterrows():
        bar_time = pd.Timestamp(row["time_key"])
        bar_date = bar_time.date()
        bar_clock = bar_time.time()
        close = float(row["close"])

        or_info = ranges.get(bar_date)
        if or_info is None or not or_info["valid"]:
            continue

        or_high = or_info["high"]
        or_low = or_info["low"]
        or_range = or_high - or_low

        # Only evaluate bars AFTER the opening range period
        _orb_min = orb_minutes if orb_minutes is not None else ORB_MINUTES
        cutoff = dtime(9, 30 + _orb_min) if 30 + _orb_min < 60 else \
                 dtime(10, (30 + _orb_min) % 60)
        if bar_clock < cutoff:
            continue

        is_time_stop = bar_clock >= _TIME_STOP

        if position is not None:
            # Check exits
            exit_reason: str | None = None
            if is_time_stop:
                exit_reason = "TIME_STOP"
            elif position["direction"] == "long":
                if close >= position["target"]:
                    exit_reason = "TARGET"
                elif close <= position["stop"]:
                    exit_reason = "STOP"
            else:  # short
                if close <= position["target"]:
                    exit_reason = "TARGET"
                elif close >= position["stop"]:
                    exit_reason = "STOP"

            if exit_reason:
                df.at[i, "orb_signal"] = f"exit_{exit_reason.lower()}"
                trade = ORBTrade(
                    entry_time=position["entry_time"],
                    entry_price=position["entry_price"],
                    exit_time=bar_time,
                    exit_price=close,
                    exit_reason=exit_reason,
                    direction=position["direction"],
                    or_high=or_high,
                    or_low=or_low,
                )
                trades.append(trade)
                log.info("ORB EXIT  %s  price=%.4f  pnl=%+.4f  reason=%s",
                         bar_time, close, trade.pnl, exit_reason)
                position = None

        if position is None and not is_time_stop and bar_date not in entered_today:
            vol_ok = float(row["volume"]) > vol_mult * float(row.get("volume_ma", 0))

            if close > or_high and vol_ok:
                target = close + target_mult * or_range
                stop = or_low
                position = {"entry_time": bar_time, "entry_price": close,
                            "target": target, "stop": stop, "direction": "long",
                            "or_high": or_high, "or_low": or_low}
                entered_today.add(bar_date)
                df.at[i, "orb_signal"] = "entry_long"
                log.info("ORB LONG  %s  price=%.4f  stop=%.4f  target=%.4f  OR=[%.4f,%.4f]",
                         bar_time, close, stop, target, or_low, or_high)

            elif close < or_low and vol_ok:
                target = close - target_mult * or_range
                stop = or_high
                position = {"entry_time": bar_time, "entry_price": close,
                            "target": target, "stop": stop, "direction": "short",
                            "or_high": or_high, "or_low": or_low}
                entered_today.add(bar_date)
                df.at[i, "orb_signal"] = "entry_short"
                log.info("ORB SHORT %s  price=%.4f  stop=%.4f  target=%.4f  OR=[%.4f,%.4f]",
                         bar_time, close, stop, target, or_low, or_high)

    return trades, df


def print_orb_summary(trades: list[ORBTrade], df: pd.DataFrame | None = None) -> None:
    if not trades:
        print("  No ORB trades.")
        return

    longs = [t for t in trades if t.direction == "long"]
    shorts = [t for t in trades if t.direction == "short"]
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    pf = gross_win / gross_loss if gross_loss else float("inf")
    avg_hold = sum(
        (t.exit_time - t.entry_time).total_seconds() / 60 for t in trades
    ) / len(trades)

    trading_days = len(df["time_key"].apply(lambda x: pd.Timestamp(x).date()).unique()) \
        if df is not None else 0
    trades_per_day = len(trades) / trading_days if trading_days else 0

    targets = sum(1 for t in trades if t.exit_reason == "TARGET")
    stops = sum(1 for t in trades if t.exit_reason == "STOP")
    time_stops = sum(1 for t in trades if t.exit_reason == "TIME_STOP")

    print(f"  ORB Strategy Summary  (OR={ORB_MINUTES}min  target={ORB_TARGET_MULT}×  vol={ORB_VOL_MULT}×)")
    print(f"  Trades:        {len(trades)}  ({trades_per_day:.1f}/day)  "
          f"[{len(longs)} long / {len(shorts)} short]")
    print(f"  Win rate:      {len(wins)/len(trades)*100:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Total PnL:     ${total_pnl:+.2f}")
    print(f"  Profit factor: {pf:.3f}")
    print(f"  Avg hold:      {avg_hold:.0f} min")
    print(f"  Exits:         {targets} target / {stops} stop / {time_stops} time")
    if trades:
        best = max(trades, key=lambda t: t.pnl)
        worst = min(trades, key=lambda t: t.pnl)
        print(f"  Best:          ${best.pnl:+.4f}  Worst: ${worst.pnl:+.4f}")
