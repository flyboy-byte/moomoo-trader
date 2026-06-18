"""
Backtester: runs the strategy over a saved candle CSV and reports results.
"""
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import config as _config
from .strategy import run_signals, Signal, Trade
from .logger import get_logger

log = get_logger("backtest")


def load_candles(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time_key"] = pd.to_datetime(df["time_key"])
    return df.sort_values("time_key").reset_index(drop=True)


def run_backtest(df: pd.DataFrame) -> tuple[list[Trade], pd.DataFrame]:
    """Return completed trades and the signal-annotated DataFrame."""
    cfg = _config.cfg  # re-fetched at call time — see mm/strategy.py for why
    df = run_signals(df)

    trades: list[Trade] = []
    open_entry: dict | None = None

    for _, row in df.iterrows():
        sig = row["signal"]

        if open_entry is None:
            if sig == Signal.ENTRY:
                open_entry = {
                    "entry_time": row["time_key"],
                    "entry_price": row["close"],
                    "risk": cfg.atr_stop_mult * float(row["atr"]),
                }
        else:
            if sig in (Signal.EXIT_TARGET, Signal.EXIT_DEATH_CROSS, Signal.EXIT_STOP_LOSS):
                trade = Trade(
                    entry_time=open_entry["entry_time"],
                    entry_price=open_entry["entry_price"],
                    exit_time=row["time_key"],
                    exit_price=row["close"],
                    exit_reason=sig.name,
                    risk=open_entry.get("risk", 0.0),
                )
                trades.append(trade)
                open_entry = None

    return trades, df


def profit_factor(trades) -> float:
    """Canonical PF calc — gross win / gross loss, inf if no losses.

    Bug fix 2026-06-18: this metric used to be independently reimplemented in
    at least 5 places across the codebase (mm/research.py, backtest_orb.py,
    backtest_vwap_pb.py, backtest_ema_momentum.py, sweep_vwap.py) with two
    inconsistent conventions that had silently drifted apart: a pnl==0 trade
    counted as a loss in some places (`pnl <= 0`) and as neither win nor loss
    in others (`pnl < 0`); the no-losses sentinel was `999.0` in some and
    `float("inf")` in others, which are NOT interchangeable in any sum/average
    across runs (inf poisons it, 999.0 doesn't). Standardized here on `<= 0`
    (matches this module's own pre-existing print_summary) and `inf` (the
    mathematically correct sentinel). Accepts any list of objects with a
    `.pnl` attribute — works with Trade, GapFadeTrade, or any other trade
    dataclass in this project.
    """
    if not trades:
        return float("inf")
    gross_win = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    return gross_win / gross_loss if gross_loss > 0 else float("inf")


def print_summary(trades: list[Trade]) -> None:
    if not trades:
        log.info("No completed trades.")
        return

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    avg_pnl = total_pnl / len(trades)
    win_rate = len(wins) / len(trades) * 100

    log.info("--- Backtest Summary ---")
    log.info("Total trades:  %d", len(trades))
    log.info("Win rate:      %.1f%%  (%d W / %d L)", win_rate, len(wins), len(losses))
    log.info("Total PnL:     %.4f", total_pnl)
    log.info("Avg PnL/trade: %.4f", avg_pnl)
    r_vals = [t.r_mult for t in trades if t.r_mult is not None]
    if r_vals:
        log.info("Avg R:         %+.3f  (PnL / initial ATR risk, size-independent)", sum(r_vals) / len(r_vals))
    avg_bps = sum(t.bps for t in trades) / len(trades)
    log.info("Avg bps/trade: %+.1f  (round-trip spread+slip hurdle ≈ 1-3 bps)", avg_bps)
    log.info("Best trade:    %.4f", max(t.pnl for t in trades))
    log.info("Worst trade:   %.4f", min(t.pnl for t in trades))

    for t in trades:
        log.info(
            "  %s → %s  entry=%.4f exit=%.4f pnl=%+.4f  [%s]",
            t.entry_time,
            t.exit_time,
            t.entry_price,
            t.exit_price,
            t.pnl,
            t.exit_reason,
        )


def backtest_file(path: str | Path) -> list[Trade]:
    df = load_candles(path)
    log.info("Loaded %d candles from %s", len(df), path)
    trades, _ = run_backtest(df)
    print_summary(trades)
    return trades


@dataclass
class WindowResult:
    label: str
    start: pd.Timestamp
    end: pd.Timestamp
    candles: int
    trades: int
    wins: int
    losses: int
    total_pnl: float
    avg_pnl: float
    win_rate: float


def walk_forward(
    df: pd.DataFrame,
    window_days: int = 30,
) -> list[WindowResult]:
    """Split df into sequential non-overlapping windows and backtest each independently.

    Returns one WindowResult per window that contained enough data to run.
    """
    df = df.copy()
    df["time_key"] = pd.to_datetime(df["time_key"])
    df = df.sort_values("time_key").reset_index(drop=True)

    start_ts = df["time_key"].iloc[0]
    end_ts = df["time_key"].iloc[-1]
    results: list[WindowResult] = []

    window_start = start_ts
    while window_start < end_ts:
        window_end = window_start + pd.Timedelta(days=window_days)
        mask = (df["time_key"] >= window_start) & (df["time_key"] < window_end)
        chunk = df[mask].reset_index(drop=True)

        label = f"{window_start.strftime('%Y-%m-%d')} → {min(window_end, end_ts).strftime('%Y-%m-%d')}"

        if len(chunk) < 20:
            log.debug("Window %s: only %d candles, skipping", label, len(chunk))
            window_start = window_end
            continue

        trades, _ = run_backtest(chunk)

        if trades:
            wins = [t for t in trades if t.pnl > 0]
            total_pnl = sum(t.pnl for t in trades)
            win_rate = len(wins) / len(trades) * 100
            avg_pnl = total_pnl / len(trades)
        else:
            wins = []
            total_pnl = avg_pnl = win_rate = 0.0

        result = WindowResult(
            label=label,
            start=window_start,
            end=window_end,
            candles=len(chunk),
            trades=len(trades),
            wins=len(wins),
            losses=len(trades) - len(wins),
            total_pnl=total_pnl,
            avg_pnl=avg_pnl,
            win_rate=win_rate,
        )
        results.append(result)
        window_start = window_end

    return results


def print_walk_forward(results: list[WindowResult]) -> None:
    if not results:
        log.info("No walk-forward windows produced results.")
        return

    log.info("--- Walk-Forward Results (%d windows) ---", len(results))
    log.info("%-40s  %5s  %5s  %6s  %8s  %8s", "Window", "Trades", "Win%", "W/L", "TotalPnL", "AvgPnL")
    for r in results:
        log.info(
            "%-40s  %5d  %5.1f  %d/%d  %+8.4f  %+8.4f",
            r.label, r.trades, r.win_rate, r.wins, r.losses, r.total_pnl, r.avg_pnl,
        )

    all_trades = [r for r in results if r.trades > 0]
    if all_trades:
        overall_trades = sum(r.trades for r in all_trades)
        overall_pnl = sum(r.total_pnl for r in all_trades)
        overall_wins = sum(r.wins for r in all_trades)
        log.info("%-40s  %5d  %5.1f  %d/%d  %+8.4f  %+8.4f",
                 "TOTAL",
                 overall_trades,
                 overall_wins / overall_trades * 100,
                 overall_wins,
                 overall_trades - overall_wins,
                 overall_pnl,
                 overall_pnl / overall_trades,
                 )


def walk_forward_file(path: str | Path, window_days: int = 30) -> list[WindowResult]:
    df = load_candles(path)
    log.info("Loaded %d candles from %s", len(df), path)
    results = walk_forward(df, window_days=window_days)
    print_walk_forward(results)
    return results
