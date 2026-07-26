#!/usr/bin/env python3
"""Backtest the Opening Range Breakout strategy against historical candle CSVs.

Usage:
    python scripts/backtest_orb.py --latest
    python scripts/backtest_orb.py logs/US_IWM_K_5M_2026-05-31.csv
    python scripts/backtest_orb.py --all
    python scripts/backtest_orb.py --sweep-vol          # sweep vol_mult (0.0/0.8/1.0/1.2/1.5/2.0)
    python scripts/backtest_orb.py --sweep-minutes      # sweep orb_minutes (15/30/45/60)
    python scripts/backtest_orb.py --sweep-target       # sweep target_mult (0.5/1.0/1.5/2.0/2.5)
    python scripts/backtest_orb.py --sweep-vix          # sweep VIX max threshold (none/15/18/20/22/25)
    python scripts/backtest_orb.py --sweep-vol --all    # vol sweep across SPY+QQQ+IWM combined CSVs
    python scripts/backtest_orb.py --all --start 2024-01-01  # OOS slice
    python scripts/backtest_orb.py --all --analyze-exits     # TIME_STOP post-exit hit analysis
    python scripts/backtest_orb.py --all --entry-timing      # entry-timing PF breakdown by bucket
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.backtest import load_candles, profit_factor
from mm.indicators import add_all
from mm.orb_strategy import run_orb_signals, print_orb_summary, ORB_VOL_MULT, ORB_TARGET_MULT, ORB_MINUTES


def _load_vix_map(logs_dir: Path) -> dict[str, float]:
    """Return {date_str: vix_prev_close} from vix_daily.jsonl."""
    vix_file = logs_dir / "vix_daily.jsonl"
    if not vix_file.exists():
        return {}
    result: dict[str, float] = {}
    with open(vix_file) as f:
        for line in f:
            try:
                rec = json.loads(line)
                result[rec["date"]] = float(rec["vix_prev_close"])
            except (KeyError, ValueError, json.JSONDecodeError):
                continue
    return result


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


def sweep_vix(df, sym: str, vix_map: dict) -> None:
    print(f"\n=== {sym} — VIX max threshold sweep ===")
    dates_in_df = set(pd.to_datetime(df["time_key"]).dt.strftime("%Y-%m-%d"))
    coverage = len(dates_in_df & set(vix_map)) if vix_map else 0
    total_days = len(dates_in_df)
    print(f"  VIX coverage: {coverage}/{total_days} trading days in this dataset")
    _header()
    # baseline — no filter
    base_trades, _ = run_orb_signals(df.copy())
    print(_row(base_trades, "no filter"))
    for threshold in [15, 17, 18, 20, 22, 25]:
        if not vix_map:
            print(f"  vix_max={threshold:<4}   [no vix_daily.jsonl found]")
            continue
        trades, _ = run_orb_signals(df.copy(), vix_map=vix_map, vix_max=threshold)
        blocked = len(base_trades) - len(trades)
        label = f"vix_max={threshold}"
        row = _row(trades, label)
        print(f"{row}  (blocked {blocked} trades)")


def analyze_exits(trades: list, annotated: pd.DataFrame, target_mult: float = ORB_TARGET_MULT) -> None:
    """For each TIME_STOP trade, scan remaining bars to see if price would have hit target."""
    time_stops = [t for t in trades if t.exit_reason == "TIME_STOP"]
    if not time_stops:
        print("\n  No TIME_STOP trades to analyze.")
        return

    annotated = annotated.copy()
    annotated["_ts"] = pd.to_datetime(annotated["time_key"])
    annotated["_date"] = annotated["_ts"].dt.date

    hit, would_have_hit, continued_against = 0, 0, 0
    favorable_moves: list[float] = []

    for t in time_stops:
        or_range = t.or_high - t.or_low
        if t.direction == "long":
            target = t.entry_price + target_mult * or_range
        else:
            target = t.entry_price - target_mult * or_range

        exit_date = t.exit_time.date() if hasattr(t.exit_time, "date") else pd.Timestamp(t.exit_time).date()
        exit_ts = pd.Timestamp(t.exit_time)
        remaining = annotated[(annotated["_date"] == exit_date) & (annotated["_ts"] > exit_ts)]

        if remaining.empty:
            continue

        closes = remaining["close"].values
        if t.direction == "long":
            hit_target = any(c >= target for c in closes)
            best_close = max(closes)
            fav_move = (best_close - t.entry_price) / t.entry_price * 100
            against = any(c < t.entry_price for c in closes)
        else:
            hit_target = any(c <= target for c in closes)
            best_close = min(closes)
            fav_move = (t.entry_price - best_close) / t.entry_price * 100
            against = any(c > t.entry_price for c in closes)

        if hit_target:
            would_have_hit += 1
        if against:
            continued_against += 1
        favorable_moves.append(fav_move)

    n = len(time_stops)
    analyzed = len(favorable_moves)
    avg_fav = sum(favorable_moves) / analyzed if analyzed else 0.0
    print(f"\n  TIME_STOP exit analysis  (N={n}, analyzed={analyzed})")
    print(f"  {'Would have hit target:':<28} {would_have_hit}/{analyzed}  "
          f"({100*would_have_hit/analyzed:.0f}%)" if analyzed else "  Would have hit target: n/a")
    print(f"  {'Continued against entry:':<28} {continued_against}/{analyzed}  "
          f"({100*continued_against/analyzed:.0f}%)" if analyzed else "  Continued against: n/a")
    print(f"  Avg max favorable move after exit: {avg_fav:+.2f}%")
    if analyzed:
        hit_pct = 100 * would_have_hit / analyzed
        if hit_pct >= 40:
            print("  → Exits too early — investigate later TIME_STOP or trailing stop")
        elif hit_pct <= 20:
            print("  → Price keeps going wrong — entry timing or direction problem")
        else:
            print("  → Mixed result — ambiguous signal")


def analyze_entry_timing(trades: list, orb_minutes: int = ORB_MINUTES) -> None:
    """Break down PF and TIME_STOP% by how many minutes after OR formation the trade entered."""
    if not trades:
        print("\n  No trades to analyze.")
        return

    or_close_min = 9 * 60 + 30 + orb_minutes  # minutes since midnight when OR closes

    buckets: dict[str, list] = {"<15min": [], "15-30min": [], "30-45min": [], ">45min": []}

    for t in trades:
        ts = pd.Timestamp(t.entry_time)
        entry_min = ts.hour * 60 + ts.minute
        lag = entry_min - or_close_min
        if lag < 15:
            buckets["<15min"].append(t)
        elif lag < 30:
            buckets["15-30min"].append(t)
        elif lag < 45:
            buckets["30-45min"].append(t)
        else:
            buckets[">45min"].append(t)

    print(f"\n  Entry timing breakdown  (OR window={orb_minutes}min, closes at "
          f"{or_close_min//60}:{or_close_min%60:02d} ET)")
    print(f"  {'Bucket':<12}  {'N':>5}  {'Win%':>6}  {'TIME_STOP%':>11}  {'PnL':>9}  {'PF':>7}")
    print("  " + "-" * 58)
    for label, bucket in buckets.items():
        if not bucket:
            print(f"  {label:<12}  {'0':>5}")
            continue
        wins = sum(1 for t in bucket if t.pnl > 0)
        ts_count = sum(1 for t in bucket if t.exit_reason == "TIME_STOP")
        pnl = sum(t.pnl for t in bucket)
        pf = profit_factor(bucket)
        print(f"  {label:<12}  {len(bucket):>5}  "
              f"{100*wins/len(bucket):>5.1f}%  "
              f"{100*ts_count/len(bucket):>10.1f}%  "
              f"{pnl:>+9.2f}  {pf:>7.3f}")


def _run_file(path: Path, args: argparse.Namespace, vix_map: dict | None = None) -> None:
    sym = path.stem.split("_K_")[0].replace("_", ".", 1)
    df = load_candles(path)
    if args.start:
        df = df[df["time_key"] >= args.start].reset_index(drop=True)
    df = add_all(df)

    do_sweep = args.sweep_vol or args.sweep_minutes or args.sweep_target or args.sweep_vix
    if not do_sweep:
        print(f"\n{'='*60}")
        print(f"File: {path.name}")
        print(f"  Candles: {len(df):,}  ({df['time_key'].iloc[0]} → {df['time_key'].iloc[-1]})")
        trades, annotated = run_orb_signals(df.copy())
        print_orb_summary(trades, annotated)
        if args.analyze_exits:
            analyze_exits(trades, annotated)
        if args.entry_timing:
            analyze_entry_timing(trades)
        return

    if args.sweep_vol:
        sweep_vol(df, sym)
    if args.sweep_minutes:
        sweep_minutes(df, sym)
    if args.sweep_target:
        sweep_target(df, sym)
    if args.sweep_vix:
        sweep_vix(df, sym, vix_map or {})


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
    parser.add_argument("--sweep-vix", action="store_true",
                        help="Sweep VIX max threshold: no filter / 15 / 17 / 18 / 20 / 22 / 25")
    parser.add_argument("--start", metavar="YYYY-MM-DD",
                        help="Only include candles on or after this date (OOS slice)")
    parser.add_argument("--analyze-exits", action="store_true",
                        help="For TIME_STOP trades: would price have hit target after exit?")
    parser.add_argument("--entry-timing", action="store_true",
                        help="Break down PF/win-pct/TIME_STOP-pct by entry lag after OR formation")
    args = parser.parse_args()

    logs = Path(__file__).parent.parent / "logs"
    vix_map = _load_vix_map(logs) if args.sweep_vix else {}

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
        _run_file(path, args, vix_map=vix_map)


if __name__ == "__main__":
    main()
