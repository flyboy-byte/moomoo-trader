#!/usr/bin/env python3
"""Replay historical candles through the paper-trading signal and risk logic.

Produces a JSONL event log identical in format to the live paper runner,
allowing compare_paper_vs_backtest.py to validate the full pipeline
without needing a live market session.

Usage:
    python scripts/simulate_paper.py logs/US_SPY_K_5M_2026-05-30.csv
    python scripts/simulate_paper.py logs/US_SPY_K_5M_2026-05-30.csv \\
        --start 2025-01-01 --end 2025-05-30 --compare
    python scripts/simulate_paper.py logs/US_SPY_K_5M_2026-05-30.csv \\
        --symbol US.SPY --start 2024-01-01 --end 2024-12-31 --compare
"""
import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from mm.backtest import load_candles
from mm.config import cfg
from mm.paper import PaperEventLog, PaperPosition
from mm.risk import DailyTracker, calc_qty
from mm.signals import snapshot as signal_snapshot
from mm.strategy import compute_signals


class SimPaperEventLog(PaperEventLog):
    """PaperEventLog with an explicit output path (bypasses date-based auto-naming)."""

    def __init__(self, symbol: str, path: Path) -> None:
        cfg.logs_dir.mkdir(exist_ok=True)
        self._sym = symbol
        self._path = path
        path.write_text("")  # clear any previous run at this path


def _infer_symbol(csv_path: Path) -> str:
    """Extract symbol from CSV filename: US_SPY_K_5M_2026-05-30.csv → US.SPY"""
    parts = csv_path.stem.split("_")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return "UNKNOWN"


def simulate(
    csv_path: Path,
    symbol: str | None = None,
    start: date | None = None,
    end: date | None = None,
    compare: bool = False,
) -> Path:
    """Replay candles and write JSONL. Returns the output path."""
    symbol = symbol or _infer_symbol(csv_path)
    sym_safe = symbol.replace(".", "_")
    start_str = start.strftime("%Y-%m-%d") if start else "all"
    end_str = end.strftime("%Y-%m-%d") if end else "all"
    out_path = cfg.logs_dir / f"paper_{sym_safe}_{start_str}_{end_str}_sim.jsonl"

    print(f"Simulating {symbol}  {start_str} → {end_str}")
    print(f"Loading: {csv_path}")
    df = load_candles(csv_path)
    print(f"  {len(df)} candles")

    print("Running compute_signals (indicators + bonus_score)...")
    df = compute_signals(df)

    elog = SimPaperEventLog(symbol, out_path)
    elog.info(f"runner_start symbol={symbol} start={start_str} end={end_str} mode=simulation "
              f"min_signal_score={cfg.min_signal_score} atr_stop_mult={cfg.atr_stop_mult}")

    position: PaperPosition | None = None
    # virtual_position mirrors what the backtester would hold — maintained even when
    # risk management blocks actual execution, so we skip in-position re-entries and
    # our signal count matches the backtester's.
    virtual_stop: float | None = None
    virtual_entry: float | None = None
    daily = DailyTracker()
    current_sim_day: date | None = None
    entry_count = 0
    exit_count = 0

    for _, row in df.iterrows():
        ts = row["time_key"]
        ts_date = ts.date()

        if start and ts_date < start:
            continue
        if end and ts_date > end:
            continue

        # Reset daily limits when simulated calendar day advances
        if current_sim_day is None or ts_date != current_sim_day:
            if current_sim_day is not None:
                daily = DailyTracker()
            current_sim_day = ts_date

        # Skip indicator warm-up rows where core indicators are not yet valid
        if pd.isna(row["bb_lower"]) or pd.isna(row["atr"]) or pd.isna(row["rsi"]):
            continue

        close = float(row["close"])
        sig = signal_snapshot(row)
        bonus = int(row["bonus_score"])
        eval_ts = ts.to_pydatetime()

        elog.bar_eval(
            candle_ts=ts, eval_ts=eval_ts, accepted=True,
            close=close, score=sig.score, bonus=bonus,
            signals=sig.details,
        )

        # --- Virtual position exit (mirrors backtester exit logic) ---
        if virtual_stop is not None:
            v_exit = None
            if close >= float(row["bb_middle"]):
                v_exit = "TARGET_BB_MIDDLE"
            elif cfg.exit_on_kdj_death and bool(row["kdj_death_cross"]):
                v_exit = "KDJ_DEATH_CROSS"
            elif close < virtual_stop:
                v_exit = "STOP_LOSS"
            if v_exit:
                if position is not None:
                    # Real position exits normally
                    pnl_per_share = close - position.entry_price
                    pnl_total = pnl_per_share * position.qty
                    elog.order_attempt("SELL", position.qty, close)
                    elog.order_result("SELL", success=True,
                                      order_id=f"SIM_EXIT_{exit_count:06d}")
                    daily.record_trade(pnl_total)
                    elog.position_close(close, v_exit, pnl_total)
                    exit_count += 1
                    position = None
                virtual_stop = None
                virtual_entry = None
            continue  # don't evaluate new entries while in a virtual position

        # --- Entry evaluation ---
        core_met = bool(row["sig_bb_touch"]) and bool(row["sig_kdj_cross"])
        bonus_met = bonus >= cfg.min_signal_score

        if core_met and bonus_met:
            if not daily.can_open():
                elog.risk_block("daily_limit_reached",
                                trades=daily.trades, pnl=daily.pnl)
            else:
                qty = calc_qty(close)
                stop = close - cfg.atr_stop_mult * float(row["atr"])
                if qty == 0:
                    elog.risk_block("price_exceeds_max_position",
                                    price=close,
                                    max_dollars=cfg.max_position_dollars)
                else:
                    order_id = f"SIM_{entry_count:06d}"
                    elog.order_attempt("BUY", qty, close)
                    elog.order_result("BUY", success=True, order_id=order_id)
                    position = PaperPosition(
                        symbol=symbol,
                        entry_time=ts.to_pydatetime(),
                        entry_price=close,
                        stop_price=stop,
                        qty=qty,
                        order_id=order_id,
                    )
                    elog.position_open(close, stop, qty)
                    entry_count += 1
                # Open virtual position regardless of real execution
                virtual_stop = stop
                virtual_entry = close
        elif core_met:
            elog.signal_skip("bonus_below_threshold",
                             score=sig.score, bonus=bonus,
                             min_score=cfg.min_signal_score)

    if position is not None:
        elog.info(f"runner_stop open_position=true entry={position.entry_price}")
    else:
        elog.info(f"runner_stop entries={entry_count} exits={exit_count}")

    print(f"\nDone: {entry_count} entries, {exit_count} exits → {out_path}")

    if compare:
        print("\nRunning compare_paper_vs_backtest...")
        from scripts.compare_paper_vs_backtest import compare as run_compare  # noqa: PLC0415
        run_compare(out_path, csv_path)

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay historical candles through paper-trading logic, produce JSONL"
    )
    parser.add_argument("csv", help="Historical candle CSV (e.g. logs/US_SPY_K_5M_2026-05-30.csv)")
    parser.add_argument("--symbol", default=None, help="Override symbol (e.g. US.SPY)")
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD (default: all)")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD (default: all)")
    parser.add_argument("--compare", action="store_true",
                        help="Auto-run compare_paper_vs_backtest on the output")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        sys.exit(1)

    start_date = date.fromisoformat(args.start) if args.start else None
    end_date = date.fromisoformat(args.end) if args.end else None

    simulate(csv_path, symbol=args.symbol, start=start_date, end=end_date, compare=args.compare)


if __name__ == "__main__":
    main()
