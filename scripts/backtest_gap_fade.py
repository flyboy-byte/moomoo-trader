"""
Gap Fade strategy backtest.

Usage:
    python scripts/backtest_gap_fade.py --all                      # all combined CSVs
    python scripts/backtest_gap_fade.py --latest                   # most recent CSV per symbol
    python scripts/backtest_gap_fade.py logs/US_SPY_K_5M_combined.csv
    python scripts/backtest_gap_fade.py --all --sweep              # sweep gap size + target fill
    python scripts/backtest_gap_fade.py --all --sweep-fill         # sweep target_fill_pct only
    python scripts/backtest_gap_fade.py --all --sweep-vix          # gap × VIX band breakdown
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.backtest import load_candles   # noqa: E402
from mm.gap_fade import (              # noqa: E402
    run_gap_fade, print_gap_fade_summary,
    GAP_MIN_PCT, GAP_MAX_PCT, GAP_TARGET_FILL_PCT, GAP_STOP_BUFFER,
)

LOGS = Path(__file__).parent.parent / "logs"

COMBINED_CSVS = [
    "US_SPY_K_5M_combined.csv",
    "US_QQQ_K_5M_combined.csv",
    "US_IWM_K_5M_combined.csv",
]


LOGS = Path(__file__).parent.parent / "logs"

_VIX_BANDS = [
    ("VIX<15",    0,  15),
    ("VIX 15-20", 15, 20),
    ("VIX 20-25", 20, 25),
    ("VIX>25",    25, 999),
]

_GAP_BANDS = [
    ("gap 0.3-0.5%", 0.003, 0.005),
    ("gap 0.5-1.0%", 0.005, 0.010),
    ("gap>1.0%",     0.010, 0.020),
]


def _load_vix_map() -> dict[str, float]:
    vix_file = LOGS / "vix_daily.jsonl"
    out: dict[str, float] = {}
    if not vix_file.exists():
        return out
    with open(vix_file) as f:
        for line in f:
            try:
                rec = json.loads(line)
                out[rec["date"]] = float(rec["vix_prev_close"])
            except (KeyError, ValueError, json.JSONDecodeError):
                continue
    return out


def sweep_vix(df: pd.DataFrame, sym: str, vix_map: dict[str, float]) -> None:
    """Print PF / win% / trade count broken down by VIX band × gap size band."""
    all_trades = run_gap_fade(df.copy())
    if not all_trades:
        print(f"  {sym}: no trades")
        return

    print(f"\n{'='*70}")
    print(f"  {sym} — Gap × VIX breakdown  (n={len(all_trades)} total trades)")
    print(f"{'='*70}")

    dates = pd.to_datetime(df["time_key"]).dt.strftime("%Y-%m-%d")
    df = df.copy()
    df["_date_str"] = dates.values

    header = f"  {'Segment':<22} {'n':>5} {'win%':>6} {'PF':>7} {'PnL':>9}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    def _stats(trades: list) -> tuple:
        if not trades:
            return 0, 0.0, 0.0, 0.0
        wins = sum(1 for t in trades if t.pnl > 0)
        pnl  = sum(t.pnl for t in trades)
        gw   = sum(t.pnl for t in trades if t.pnl > 0)
        gl   = abs(sum(t.pnl for t in trades if t.pnl < 0))
        pf   = gw / gl if gl else float("inf")
        return len(trades), wins / len(trades) * 100, pf, pnl

    for vix_label, vlo, vhi in _VIX_BANDS:
        vix_trades = [
            t for t in all_trades
            if vix_map.get(str(t.entry_time.date())) is not None
            and vlo <= vix_map[str(t.entry_time.date())] < vhi
        ]
        n, wp, pf, pnl = _stats(vix_trades)
        pf_s = f"{pf:.3f}" if pf != float("inf") else "   ∞"
        print(f"  {vix_label:<22} {n:>5} {wp:>5.0f}% {pf_s:>7} {pnl:>+9.2f}")

        for gap_label, glo, ghi in _GAP_BANDS:
            sub = [t for t in vix_trades if glo <= abs(t.gap_pct) < ghi]
            n2, wp2, pf2, pnl2 = _stats(sub)
            if n2 == 0:
                continue
            pf2_s = f"{pf2:.3f}" if pf2 != float("inf") else "   ∞"
            print(f"    ↳ {gap_label:<20} {n2:>5} {wp2:>5.0f}% {pf2_s:>7} {pnl2:>+9.2f}")

    # overall sanity check
    no_vix = [t for t in all_trades if str(t.entry_time.date()) not in vix_map]
    if no_vix:
        print(f"\n  ({len(no_vix)} trades had no VIX data — excluded from breakdown)")


def _symbol(path: Path) -> str:
    name = path.stem  # e.g. US_SPY_K_5M_combined
    parts = name.split("_")
    return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else name


def _resolve_csvs(args: argparse.Namespace) -> list[Path]:
    if args.csvs:
        return [Path(p) for p in args.csvs]
    if args.all:
        return [LOGS / f for f in COMBINED_CSVS if (LOGS / f).exists()]
    if args.latest:
        paths = []
        for prefix in ("US_SPY", "US_QQQ", "US_IWM"):
            candidates = sorted(LOGS.glob(f"{prefix}_K_5M*.csv"), reverse=True)
            if candidates:
                paths.append(candidates[0])
        return paths
    return []


def run_single(path: Path, args: argparse.Namespace,
               vix_map: dict[str, float] | None = None) -> None:
    sym = _symbol(path)
    df = load_candles(path)
    days = df["time_key"].dt.date.nunique()

    if args.sweep_vix:
        sweep_vix(df, sym, vix_map or {})
        return

    if args.sweep:
        print(f"\n{'='*70}\n  {sym} — SWEEP  (stop_buffer={GAP_STOP_BUFFER:.3f})\n{'='*70}")
        header = f"  {'min_gap%':>8} {'target_fill':>12} {'trades':>7} {'win%':>6} {'pnl':>9} {'pf':>7}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for min_gap in (0.002, 0.003, 0.005, 0.008, 0.01):
            for fill in (0.3, 0.5, 0.75, 1.0):
                trades = run_gap_fade(df.copy(), min_gap_pct=min_gap, target_fill_pct=fill)
                if not trades:
                    continue
                wins = sum(1 for t in trades if t.pnl > 0)
                pnl = sum(t.pnl for t in trades)
                gw = sum(t.pnl for t in trades if t.pnl > 0)
                gl = abs(sum(t.pnl for t in trades if t.pnl < 0))
                pf = gw / gl if gl else float("inf")
                pf_s = f"{pf:.3f}" if pf != float("inf") else "   ∞"
                print(f"  {min_gap*100:>7.1f}% {fill:>12.0%} {len(trades):>7} "
                      f"{100*wins/len(trades):>5.0f}% {pnl:>+9.2f} {pf_s:>7}")
        return

    if args.sweep_fill:
        print(f"\n{'='*70}\n  {sym} — target_fill sweep  "
              f"(min_gap={GAP_MIN_PCT:.1%}  stop={GAP_STOP_BUFFER:.3f})\n{'='*70}")
        print(f"  {'fill%':>8} {'trades':>7} {'win%':>6} {'pnl':>9} {'pf':>7}  exits")
        for fill in (0.25, 0.33, 0.5, 0.67, 0.75, 1.0):
            trades = run_gap_fade(df.copy(), target_fill_pct=fill)
            if not trades:
                continue
            from collections import Counter
            wins = sum(1 for t in trades if t.pnl > 0)
            pnl = sum(t.pnl for t in trades)
            gw = sum(t.pnl for t in trades if t.pnl > 0)
            gl = abs(sum(t.pnl for t in trades if t.pnl < 0))
            pf = gw / gl if gl else float("inf")
            pf_s = f"{pf:.3f}" if pf != float("inf") else "∞"
            reasons = dict(Counter(t.exit_reason for t in trades))
            print(f"  {fill:>7.0%} {len(trades):>7} {100*wins/len(trades):>5.0f}% "
                  f"{pnl:>+9.2f} {pf_s:>7}  {reasons}")
        return

    trades = run_gap_fade(df.copy())
    print()
    print_gap_fade_summary(trades, symbol=sym, days=days)

    if args.details and trades:
        print(f"\n  {'Date':<12} {'Dir':>5} {'Gap%':>6} {'Entry':>8} {'Exit':>8} "
              f"{'PnL':>8} {'Reason':<14}")
        print("  " + "-" * 70)
        for t in sorted(trades, key=lambda x: x.entry_time):
            print(f"  {str(t.entry_time.date()):<12} {t.direction:>5} "
                  f"{t.gap_pct*100:>+5.2f}% {t.entry_price:>8.3f} {t.exit_price:>8.3f} "
                  f"{t.pnl:>+8.3f} {t.exit_reason:<14}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gap Fade strategy backtest")
    parser.add_argument("csvs", nargs="*", help="CSV file(s) to backtest")
    parser.add_argument("--all", action="store_true", help="All combined CSVs")
    parser.add_argument("--latest", action="store_true", help="Most recent CSV per symbol")
    parser.add_argument("--sweep", action="store_true", help="Sweep min_gap × target_fill")
    parser.add_argument("--sweep-fill", action="store_true", help="Sweep target_fill_pct only")
    parser.add_argument("--sweep-vix", action="store_true", help="Gap × VIX band breakdown")
    parser.add_argument("--details", action="store_true", help="Print individual trades")
    args = parser.parse_args()

    if not args.csvs and not args.all and not args.latest:
        args.all = True  # default to all

    paths = _resolve_csvs(args)
    if not paths:
        print("No CSV files found. Run with --all or pass CSV paths explicitly.")
        sys.exit(1)

    vix_map: dict[str, float] | None = None
    if args.sweep_vix:
        vix_map = _load_vix_map()
        if not vix_map:
            print("WARNING: no VIX data found in logs/vix_daily.jsonl — run fetch_vix_morning.py first")
        print(f"Gap × VIX Sweep  —  min_gap={GAP_MIN_PCT:.1%}  max_gap={GAP_MAX_PCT:.1%}  "
              f"fill={GAP_TARGET_FILL_PCT:.0%}  vix_records={len(vix_map)}")
    else:
        print(f"Gap Fade Backtest  —  min_gap={GAP_MIN_PCT:.1%}  max_gap={GAP_MAX_PCT:.1%}  "
              f"fill={GAP_TARGET_FILL_PCT:.0%}  stop_buf={GAP_STOP_BUFFER:.3f}")

    all_trades = []
    for path in paths:
        run_single(path, args, vix_map=vix_map)
        if not args.sweep and not args.sweep_fill and not args.sweep_vix:
            df = load_candles(path)
            all_trades.extend(run_gap_fade(df.copy()))

    if len(paths) > 1 and not args.sweep and not args.sweep_fill and not args.sweep_vix:
        print()
        print_gap_fade_summary(all_trades, symbol="COMBINED", days=0)


if __name__ == "__main__":
    main()
