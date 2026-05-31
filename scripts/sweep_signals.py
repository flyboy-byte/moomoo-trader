#!/usr/bin/env python3
"""Compare alternative regime/ranging filters as the third bonus signal.

Tests ADX ranging (current default), BB width percentile variants, and no-filter
across one or more candle CSVs at multiple min_bonus thresholds.

Usage:
    python scripts/sweep_signals.py --latest
    python scripts/sweep_signals.py logs/US_SPY_K_5M_2026-05-30.csv
    python scripts/sweep_signals.py logs/US_SPY_K_5M_2026-05-30.csv \\
        logs/US_QQQ_K_5M_2026-05-31.csv logs/US_IWM_K_5M_2026-05-31.csv
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from mm.backtest import load_candles
from mm.config import cfg
from mm.research import sweep_signal_filter
from mm.logger import get_logger

log = get_logger("sweep_signals")


def _latest_csvs() -> list[Path]:
    """Find the most recent K_5M CSV for each symbol found in logs/."""
    by_sym: dict[str, Path] = {}
    for p in cfg.logs_dir.glob("US_*_K_5M_*.csv"):
        parts = p.stem.split("_")
        if len(parts) >= 2:
            sym = f"{parts[0]}_{parts[1]}"
            if sym not in by_sym or p.stem > by_sym[sym].stem:
                by_sym[sym] = p
    return sorted(by_sym.values())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sweep regime/ranging signal filter alternatives"
    )
    parser.add_argument("csvs", nargs="*", help="Candle CSV files to analyse")
    parser.add_argument("--latest", action="store_true",
                        help="Auto-discover latest K_5M CSVs in logs/")
    args = parser.parse_args()

    if args.latest:
        csvs = _latest_csvs()
        if not csvs:
            print("No K_5M CSVs found in logs/")
            sys.exit(1)
    elif args.csvs:
        csvs = [Path(p) for p in args.csvs]
    else:
        parser.print_help()
        sys.exit(1)

    for p in csvs:
        if not p.exists():
            print(f"Not found: {p}")
            sys.exit(1)

    # Run per-file — indicators must not cross symbol boundaries
    per_file_results = []
    for p in csvs:
        df = load_candles(p)
        log.info("Loaded %d candles from %s", len(df), p.name)
        r = sweep_signal_filter(df)
        r["file"] = p.stem
        per_file_results.append(r)

    if len(per_file_results) == 1:
        result = per_file_results[0].drop(columns=["file"])
    else:
        # Aggregate across files: sum counts, weighted-average rates.
        # Profit factor cannot be reliably computed from file-level totals — omitted.
        combined_frames = pd.concat(per_file_results, ignore_index=True)
        agg = (
            combined_frames
            .groupby(["regime_filter", "min_bonus"], as_index=False)
            .agg(
                trades=("trades", "sum"),
                total_pnl=("total_pnl", "sum"),
                stops=("stops", "sum"),
                targets=("targets", "sum"),
            )
        )
        win_agg = (
            combined_frames
            .assign(weighted_win=lambda x: x["win_pct"] * x["trades"])
            .groupby(["regime_filter", "min_bonus"], as_index=False)
            .agg(weighted_win=("weighted_win", "sum"), trades_sum=("trades", "sum"))
        )
        win_agg["win_pct"] = (win_agg["weighted_win"] / win_agg["trades_sum"]).round(1)
        agg = agg.merge(win_agg[["regime_filter", "min_bonus", "win_pct"]],
                        on=["regime_filter", "min_bonus"])
        agg["avg_pnl"] = (agg["total_pnl"] / agg["trades"]).round(4)
        agg["total_pnl"] = agg["total_pnl"].round(4)
        result = agg.sort_values("total_pnl", ascending=False)

    print("\n=== Signal Filter Sweep Results ===")
    print(result.to_string(index=False))
    if not result.empty:
        top = result.iloc[0]
        pf_str = f"PF={top['profit_factor']}  " if "profit_factor" in result.columns else ""
        print(f"\nTop result: {top['regime_filter']}  "
              f"min_bonus={top['min_bonus']}  "
              f"{pf_str}"
              f"trades={top['trades']}  "
              f"win%={top['win_pct']}")


if __name__ == "__main__":
    main()
