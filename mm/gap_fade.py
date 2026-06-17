"""
Gap Fade strategy.

Overnight gap forms when today's open differs meaningfully from yesterday's close.
Most small gaps fill intraday. This strategy fades the gap when the first 5-min bar
confirms rejection of the gap direction.

Entry:
  - Gap >= MIN_GAP_PCT (default 0.3%) in either direction.
  - First 5-min bar (9:30 bar, labeled at bar START) closes AGAINST the gap:
      gap up  + first bar close < open → short (market rejected the gap).
      gap down + first bar close > open → long  (market rejected the gap).
  - Entry at close of first bar (9:30 start = 9:35 close).

Exit:
  - TARGET: price reaches GAP_TARGET_FILL_PCT × gap distance toward prev_close.
      E.g. 0.5 → target 50% gap fill from open toward prev_close.
  - STOP:   first bar's extreme (high for shorts, low for longs) × (1 ± stop_buffer).
  - TIME_STOP: 11:00 ET — morning-only strategy.

Filters:
  - MAX_GAP_PCT (default 2.0%) caps news-event gaps where fade logic breaks down.
  - gap_shorts_enabled: disable short entries if needed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time as dtime

import pandas as pd

from .indicators import add_all
from .logger import get_logger
from .premarket import premarket_fill_pct as _premarket_fill_pct

log = get_logger("gap_fade")

GAP_MIN_PCT: float = float(os.getenv("GAP_MIN_PCT", "0.003"))       # 0.3% minimum gap
GAP_MAX_PCT: float = float(os.getenv("GAP_MAX_PCT", "0.02"))        # 2.0% max (no news gaps)
GAP_TARGET_FILL_PCT: float = float(os.getenv("GAP_TARGET_FILL_PCT", "0.5"))  # 50% gap fill
GAP_STOP_BUFFER: float = float(os.getenv("GAP_STOP_BUFFER", "0.001"))        # 0.1% beyond extreme
GAP_SHORTS_ENABLED: bool = os.getenv("GAP_SHORTS_ENABLED", "true").lower() in ("true", "1", "yes")
# See mm/config.py's gap_premarket_fill_pct_min comment for why this is a MIN, not a MAX.
GAP_PREMARKET_FILL_PCT_MIN: float = float(os.getenv("GAP_PREMARKET_FILL_PCT_MIN", "0.3"))

# 5-min bars are labeled at their END time. First bar of session closes at 9:35.
_FIRST_BAR_TIME = dtime(9, 35)
_TIME_STOP = dtime(11, 0)


@dataclass
class GapFadeTrade:
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    exit_time: pd.Timestamp
    exit_price: float
    exit_reason: str
    direction: str    # "long" or "short"
    gap_pct: float    # overnight gap (signed: positive = gap up)
    prev_close: float
    premarket_fill_pct: float | None = None  # shadow telemetry, see run_gap_fade()
    would_filter_skip: bool = False          # would this trade be skipped if the filter were live?
    pnl: float = field(init=False)

    def __post_init__(self) -> None:
        self.pnl = (self.exit_price - self.entry_price) if self.direction == "long" \
                   else (self.entry_price - self.exit_price)


def _build_day_map(df: pd.DataFrame) -> dict:
    """Return {date: {prev_close, open, high, low, close, ts}} for each day
    that has a valid 9:30 first bar and a previous day."""
    df = df.copy()
    df["_ts"] = pd.to_datetime(df["time_key"])
    df["_date"] = df["_ts"].dt.date
    df["_time"] = df["_ts"].dt.time

    day_map: dict = {}
    unique_dates = sorted(df["_date"].unique())
    # Build last-close-per-day first
    last_close: dict = {}
    for date, grp in df.groupby("_date"):
        last_close[date] = float(grp.iloc[-1]["close"])

    for i, date in enumerate(unique_dates):
        if i == 0:
            continue  # no previous day
        prev_date = unique_dates[i - 1]
        day_df = df[df["_date"] == date]
        first = day_df[day_df["_time"] == _FIRST_BAR_TIME]
        if first.empty:
            continue
        row = first.iloc[0]
        day_map[date] = {
            "prev_close": last_close[prev_date],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "ts": row["_ts"],
        }
    return day_map


def run_gap_fade(
    df: pd.DataFrame,
    min_gap_pct: float = GAP_MIN_PCT,
    max_gap_pct: float = GAP_MAX_PCT,
    target_fill_pct: float = GAP_TARGET_FILL_PCT,
    stop_buffer: float = GAP_STOP_BUFFER,
    shorts_enabled: bool = GAP_SHORTS_ENABLED,
    premarket_sessions: dict | None = None,
    min_premarket_fill_pct: float = GAP_PREMARKET_FILL_PCT_MIN,
    filter_active: bool = False,
) -> list[GapFadeTrade]:
    """Stateful bar-by-bar gap fade pass. Returns list of completed trades.

    premarket_sessions: optional {date: DataFrame} from mm.premarket.premarket_session(),
    used purely for shadow telemetry (GapFadeTrade.premarket_fill_pct / would_filter_skip)
    unless filter_active=True. Frozen fill definition: mm.premarket.premarket_fill_pct()
    (the ~9:25 ET reference price), matching the validated 9-month/57-trade research finding
    — do not swap in a different fill statistic without re-running that validation.

    filter_active: if True, actually skips entries where premarket_fill_pct < min_premarket_fill_pct
    (None counts as "no premarket data — don't skip"). Defaults to False (shadow mode only) —
    this strategy is not in live STRATEGIES yet, and per evaluation_criteria.md discipline this
    should stay shadow-logged until it survives fresh forward data, not just the retrospective sample.
    """
    if "atr" not in df.columns:
        df = add_all(df)
    df = df.copy()
    df["_ts"] = pd.to_datetime(df["time_key"])
    df["_date"] = df["_ts"].dt.date
    df["_time"] = df["_ts"].dt.time

    day_map = _build_day_map(df)
    trades: list[GapFadeTrade] = []
    position: dict | None = None

    for _, row in df.iterrows():
        date = row["_date"]
        bar_time = row["_time"]
        bar_ts = row["_ts"]
        close = float(row["close"])

        # ------------------------------------------------------------------ exit
        if position is not None:
            exit_reason: str | None = None
            if position["direction"] == "long":
                if close >= position["target"]:
                    exit_reason = "TARGET"
                elif close <= position["stop"]:
                    exit_reason = "STOP"
            else:
                if close <= position["target"]:
                    exit_reason = "TARGET"
                elif close >= position["stop"]:
                    exit_reason = "STOP"
            if exit_reason is None and bar_time >= _TIME_STOP:
                exit_reason = "TIME_STOP"

            if exit_reason:
                trade = GapFadeTrade(
                    entry_time=position["entry_ts"],
                    entry_price=position["entry_price"],
                    stop_price=position["stop"],
                    target_price=position["target"],
                    exit_time=bar_ts,
                    exit_price=close,
                    exit_reason=exit_reason,
                    direction=position["direction"],
                    gap_pct=position["gap_pct"],
                    prev_close=position["prev_close"],
                    premarket_fill_pct=position.get("premarket_fill_pct"),
                    would_filter_skip=position.get("would_filter_skip", False),
                )
                trades.append(trade)
                log.info("GAP_FADE EXIT  %s [%s]  price=%.4f  pnl=%+.4f  reason=%s",
                         bar_ts, position["direction"], close, trade.pnl, exit_reason)
                position = None
            continue

        # ------------------------------------------------------------------ entry (first bar only)
        if bar_time != _FIRST_BAR_TIME or date not in day_map:
            continue

        info = day_map[date]
        prev_close = info["prev_close"]
        today_open = info["open"]
        first_close = info["close"]
        first_high = info["high"]
        first_low = info["low"]

        gap_pct = (today_open - prev_close) / prev_close

        if abs(gap_pct) < min_gap_pct or abs(gap_pct) > max_gap_pct:
            log.debug("GAP_FADE SKIP  %s  gap=%.3f%%  outside [%.1f%%,%.1f%%]",
                      bar_ts, gap_pct * 100, min_gap_pct * 100, max_gap_pct * 100)
            continue

        # Pre-market fill% — shadow telemetry (and live gate if filter_active). Computed here,
        # after the gap-size check and before long/short branch construction, per the design
        # this filter was reviewed against: a structural eligibility check, not mixed into the
        # bar-confirmation or execution logic.
        fill_pct: float | None = None
        would_skip = False
        if premarket_sessions is not None and date in premarket_sessions:
            fill_pct = _premarket_fill_pct(prev_close, today_open, premarket_sessions[date])
            if fill_pct is not None and fill_pct < min_premarket_fill_pct:
                would_skip = True
        if filter_active and would_skip:
            log.debug("GAP_FADE SKIP  %s  premarket_fill_pct=%.2f < min=%.2f",
                      bar_ts, fill_pct, min_premarket_fill_pct)
            continue

        # Gap up → short if first bar rejected (closed below open)
        if gap_pct > 0 and first_close < today_open and shorts_enabled:
            stop = round(first_high * (1 + stop_buffer), 4)
            target = round(today_open - target_fill_pct * (today_open - prev_close), 4)
            position = {
                "entry_ts": bar_ts, "entry_price": first_close, "direction": "short",
                "stop": stop, "target": target, "gap_pct": gap_pct, "prev_close": prev_close,
                "premarket_fill_pct": fill_pct, "would_filter_skip": would_skip,
            }
            log.info("GAP_FADE SHORT %s  gap=%+.3f%%  entry=%.4f  stop=%.4f  target=%.4f",
                     bar_ts, gap_pct * 100, first_close, stop, target)

        # Gap down → long if first bar rejected (closed above open)
        elif gap_pct < 0 and first_close > today_open:
            stop = round(first_low * (1 - stop_buffer), 4)
            target = round(today_open + target_fill_pct * (prev_close - today_open), 4)
            position = {
                "entry_ts": bar_ts, "entry_price": first_close, "direction": "long",
                "stop": stop, "target": target, "gap_pct": gap_pct, "prev_close": prev_close,
                "premarket_fill_pct": fill_pct, "would_filter_skip": would_skip,
            }
            log.info("GAP_FADE LONG  %s  gap=%+.3f%%  entry=%.4f  stop=%.4f  target=%.4f",
                     bar_ts, gap_pct * 100, first_close, stop, target)

    return trades


def print_gap_fade_summary(
    trades: list[GapFadeTrade],
    symbol: str = "",
    days: int = 0,
) -> None:
    if not trades:
        print(f"Gap Fade {symbol}: No trades")
        return

    longs = [t for t in trades if t.direction == "long"]
    shorts = [t for t in trades if t.direction == "short"]
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    pf = gross_win / gross_loss if gross_loss else float("inf")

    from collections import Counter
    reasons = Counter(t.exit_reason for t in trades)
    avg_gap = sum(abs(t.gap_pct) * 100 for t in trades) / len(trades)
    avg_hold = sum(
        (t.exit_time - t.entry_time).total_seconds() / 60 for t in trades
    ) / len(trades)

    freq = f"  ({len(trades)/days:.2f}/day)" if days else ""
    pf_str = f"{pf:.3f}" if pf != float("inf") else "∞"
    print(f"Gap Fade {symbol}")
    print(f"  Trades:        {len(trades)}{freq}  [{len(longs)} long / {len(shorts)} short]")
    print(f"  Win rate:      {100*len(wins)/len(trades):.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  Total PnL:     ${total_pnl:+.2f}")
    print(f"  Profit factor: {pf_str}")
    print(f"  Avg hold:      {avg_hold:.0f} min")
    print(f"  Avg gap size:  {avg_gap:.2f}%")
    print(f"  Exits:         {dict(reasons)}")
    if trades:
        best = max(trades, key=lambda t: t.pnl)
        worst = min(trades, key=lambda t: t.pnl)
        print(f"  Best:          ${best.pnl:+.4f}  Worst: ${worst.pnl:+.4f}")
