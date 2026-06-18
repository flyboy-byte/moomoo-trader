#!/usr/bin/env python3
"""Parameter sweep for the VWAP mean-reversion scalp strategy.

Sweeps VWAP_BAND_MULT × VWAP_STOP_MULT × RSI threshold across all K_5M CSVs.
Reports trades/day, win rate, profit factor, total PnL sorted by profit factor.

Usage:
    python scripts/sweep_vwap.py
    python scripts/sweep_vwap.py --latest   # one file per symbol (most recent)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from mm.backtest import load_candles, profit_factor
from mm.vwap_strategy import run_vwap_signals

BAND_MULTS = [0.25, 0.5, 0.75, 1.0]
STOP_MULTS = [0.5, 0.75, 1.0]
RSI_THRESHOLDS = [35, 40, 45, 50]


def _run_combo(dfs: list[pd.DataFrame], band: float, stop: float, rsi: float) -> dict:
    import mm.vwap_signals as vs
    vs.VWAP_BAND_MULT = band
    vs.RSI_DIP_THRESHOLD = rsi

    all_trades = []
    total_days = 0
    for df in dfs:
        trades, annotated = run_vwap_signals(df, stop_mult=stop)
        all_trades.extend(trades)
        total_days += len(pd.to_datetime(annotated["time_key"]).dt.date.unique())

    if not all_trades:
        return {"band": band, "stop": stop, "rsi": rsi, "trades": 0,
                "trades_day": 0, "win_pct": 0, "pnl": 0, "pf": 0, "avg_hold": 0}

    wins = [t for t in all_trades if t.pnl > 0]
    total_pnl = sum(t.pnl for t in all_trades)
    pf = profit_factor(all_trades)
    avg_hold = sum(
        (t.exit_time - t.entry_time).total_seconds() / 60 for t in all_trades
    ) / len(all_trades)

    return {
        "band": band, "stop": stop, "rsi": rsi,
        "trades": len(all_trades),
        "trades_day": len(all_trades) / total_days if total_days else 0,
        "win_pct": len(wins) / len(all_trades) * 100,
        "pnl": total_pnl,
        "pf": pf,
        "avg_hold": avg_hold,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="VWAP parameter sweep")
    parser.add_argument("--latest", action="store_true", default=True,
                        help="Use most recent K_5M CSV per symbol (default)")
    parser.add_argument("--all", action="store_true", help="All K_5M CSVs")
    args = parser.parse_args()

    logs = Path(__file__).parent.parent / "logs"

    if args.all:
        paths = sorted(logs.glob("US_*_K_5M_*.csv"))
    else:
        seen: dict[str, Path] = {}
        for p in sorted(logs.glob("US_*_K_5M_*.csv")):
            sym = p.name.split("_K_5M_")[0]
            seen[sym] = p
        paths = sorted(seen.values())

    if not paths:
        print("No K_5M CSV files found in logs/")
        sys.exit(1)

    print(f"Loading {len(paths)} file(s)...")
    dfs = [load_candles(p) for p in paths]
    for p, df in zip(paths, dfs):
        print(f"  {p.name}: {len(df):,} candles")

    print(f"\nSweeping {len(BAND_MULTS)}×{len(STOP_MULTS)}×{len(RSI_THRESHOLDS)} = "
          f"{len(BAND_MULTS)*len(STOP_MULTS)*len(RSI_THRESHOLDS)} combinations...\n")

    rows = []
    for band in BAND_MULTS:
        for stop in STOP_MULTS:
            for rsi in RSI_THRESHOLDS:
                rows.append(_run_combo(dfs, band, stop, rsi))

    results = pd.DataFrame(rows).sort_values("pf", ascending=False)

    print(f"{'band':>6} {'stop':>6} {'rsi':>5} {'trades':>7} {'t/day':>6} "
          f"{'win%':>6} {'pnl':>8} {'pf':>7} {'hold':>6}")
    print("-" * 70)
    for _, r in results.iterrows():
        print(f"{r['band']:>6.2f} {r['stop']:>6.2f} {r['rsi']:>5.0f} "
              f"{r['trades']:>7.0f} {r['trades_day']:>6.1f} "
              f"{r['win_pct']:>6.1f}% {r['pnl']:>+8.2f} {r['pf']:>7.3f} "
              f"{r['avg_hold']:>5.0f}m")

    print("\n--- Top 5 by profit factor ---")
    for _, r in results.head(5).iterrows():
        print(f"  band={r['band']} stop={r['stop']} rsi={r['rsi']:.0f}  →  "
              f"{r['trades']:.0f} trades ({r['trades_day']:.1f}/day), "
              f"{r['win_pct']:.1f}% win, PF={r['pf']:.3f}, PnL={r['pnl']:+.2f}")


if __name__ == "__main__":
    main()
