#!/usr/bin/env python3
"""Backtest the Opening Range Breakout strategy against historical candle CSVs.

Usage:
    python scripts/backtest_orb.py --latest
    python scripts/backtest_orb.py logs/US_IWM_K_5M_2026-05-31.csv
    python scripts/backtest_orb.py --all
    python scripts/backtest_orb.py --sweep-vol          # sweep vol_mult (0.0/0.8/1.0/1.2/1.5/2.0)
    python scripts/backtest_orb.py --sweep-minutes      # sweep orb_minutes (15/30/45/60)
    python scripts/backtest_orb.py --sweep-target       # sweep target_mult (0.5/1.0/1.5/2.0/2.5)
    python scripts/backtest_orb.py --sweep-vol --all    # vol sweep across SPY+QQQ+IWM combined CSVs
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.backtest import load_candles, profit_factor
from mm.indicators import add_all
from mm.orb_strategy import run_orb_signals, print_orb_summary, ORB_VOL_MULT, ORB_TARGET_MULT


def _row(trades: list, label: str) -> str:
    if not trades:
        return f"{label:<18}  {'0':>7}  {'—':>6}  {'—':>9}  {'—':>7}"
    wins = sum(1 for t in trades if t.pnl > 0)
    pnl = sum(t.pnl for t in trades)
    pf = profit_factor(trades)
    return (f"{label:<18}  {len(trades):>7}  "
            f"{100*wins/len(trades):>5.1f}%  {pnl:>+9.2f}  {pf:>7.3f}")


def _header() -> None:
    print(f"\n{'param':>18}  {'trades':>7}  {'win%':>6}  {'pnl':>9}  {'pf':>7}")
    print("-" * 56)


def sweep_vol(df, sym: str) -> None:
    print(f"\n=== {sym} — vol_mult sweep ===")
    _header()
    for vm in [0.0, 0.8, 1.0, 1.2, 1.5, 2.0]:
        trades, _ = run_orb_signals(df.copy(), vol_mult=vm)
        print(_row(trades, f"vol={vm:.1f}"))


def sweep_minutes(df, sym: str) -> None:
    print(f"\n=== {sym} — orb_minutes sweep ===")
    _header()
    for mins in [15, 30, 45, 60]:
        trades, _ = run_orb_signals(df.copy(), orb_minutes=mins)
        print(_row(trades, f"minutes={mins}"))


def sweep_target(df, sym: str) -> None:
    print(f"\n=== {sym} — target_mult sweep ===")
    _header()
    for tm in [0.5, 1.0, 1.5, 2.0, 2.5]:
        trades, _ = run_orb_signals(df.copy(), target_mult=tm)
        print(_row(trades, f"target={tm:.1f}x"))


def _run_file(path: Path, args: argparse.Namespace) -> None:
    sym = path.stem.split("_K_")[0].replace("_", ".", 1)
    df = load_candles(path)
    df = add_all(df)

    do_sweep = args.sweep_vol or args.sweep_minutes or args.sweep_target
    if not do_sweep:
        print(f"\n{'='*60}")
        print(f"File: {path.name}")
        print(f"  Candles: {len(df):,}  ({df['time_key'].iloc[0]} → {df['time_key'].iloc[-1]})")
        trades, annotated = run_orb_signals(df.copy())
        print_orb_summary(trades, annotated)
        return

    if args.sweep_vol:
        sweep_vol(df, sym)
    if args.sweep_minutes:
        sweep_minutes(df, sym)
    if args.sweep_target:
        sweep_target(df, sym)


def main() -> None:
    parser = argparse.ArgumentParser(description="ORB strategy backtest")
    parser.add_argument("csvs", nargs="*")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--sweep-vol", action="store_true",
                        help="Sweep vol_mult: 0.0 (disabled), 0.8, 1.0, 1.2, 1.5, 2.0")
    parser.add_argument("--sweep-minutes", action="store_true",
                        help="Sweep orb_minutes opening range window: 15, 30, 45, 60")
    parser.add_argument("--sweep-target", action="store_true",
                        help="Sweep target_mult: 0.5, 1.0, 1.5, 2.0, 2.5")
    args = parser.parse_args()

    logs = Path(__file__).parent.parent / "logs"
    paths: list[Path] = []
    if args.csvs:
        paths = [Path(p) for p in args.csvs]
    elif args.all:
        combined = sorted(logs.glob("US_*_K_5M_combined.csv"))
        paths = combined if combined else sorted(logs.glob("US_*_K_5M_*.csv"))
    elif args.latest:
        seen: dict[str, Path] = {}
        for p in sorted(logs.glob("US_*_K_5M_*.csv")):
            sym = p.name.split("_K_5M_")[0]
            seen[sym] = p
        paths = sorted(seen.values())
    else:
        parser.print_help()
        sys.exit(1)

    for path in paths:
        _run_file(path, args)


if __name__ == "__main__":
    main()
