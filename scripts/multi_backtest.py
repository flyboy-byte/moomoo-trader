#!/usr/bin/env python3
"""Multi-symbol backtest: run BB+KDJ strategy across several candle CSVs and compare.

Usage:
    python scripts/multi_backtest.py                          # all CSVs in logs/
    python scripts/multi_backtest.py logs/US_SPY_K_5M_*.csv  # explicit files
    python scripts/multi_backtest.py --sweep                  # also run ATR sweep on combined data
    python scripts/multi_backtest.py --ktype K_5M             # filter by ktype
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from mm.backtest import run_backtest, load_candles
from mm.research import _run_parametric, _profit_factor, _summarise as _res_summarise
from mm.indicators import add_all
from mm.strategy import Trade
from mm.config import cfg
from mm.logger import get_logger

log = get_logger("multi_backtest")


def _symbol_from_path(path: Path) -> str:
    """Extract 'US.SPY' from 'US_SPY_K_5M_2026-05-30.csv'."""
    parts = path.stem.split("_")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return path.stem


def _ktype_from_path(path: Path) -> str:
    """Extract 'K_5M' from 'US_SPY_K_5M_2026-05-30.csv'."""
    parts = path.stem.split("_")
    if len(parts) >= 4:
        return f"{parts[2]}_{parts[3]}"
    return ""


def _summarise(trades: list[Trade]) -> dict:
    if not trades:
        return dict(trades=0, wins=0, losses=0, win_rate=0.0,
                    total_pnl=0.0, avg_pnl=0.0, best=0.0, worst=0.0)
    wins = [t for t in trades if t.pnl > 0]
    pnls = [t.pnl for t in trades]
    total = sum(pnls)
    return dict(
        trades=len(trades),
        wins=len(wins),
        losses=len(trades) - len(wins),
        win_rate=len(wins) / len(trades) * 100,
        total_pnl=total,
        avg_pnl=total / len(trades),
        best=max(pnls),
        worst=min(pnls),
    )


def _print_table(rows: list[dict]) -> None:
    hdr = f"{'Symbol':<12}  {'Trades':>6}  {'Win%':>6}  {'W/L':>7}  {'TotalPnL':>10}  {'AvgPnL':>8}  {'Best':>8}  {'Worst':>8}"
    sep = "-" * len(hdr)
    print(sep)
    print(hdr)
    print(sep)
    for r in rows:
        wl = f"{r['wins']}/{r['losses']}"
        print(
            f"{r['symbol']:<12}  {r['trades']:>6}  {r['win_rate']:>6.1f}  {wl:>7}"
            f"  {r['total_pnl']:>+10.4f}  {r['avg_pnl']:>+8.4f}"
            f"  {r['best']:>+8.4f}  {r['worst']:>+8.4f}"
        )
    print(sep)


def _combined_row(all_trades: list[Trade], label: str = "COMBINED") -> dict:
    s = _summarise(all_trades)
    s["symbol"] = label
    return s


def discover_csvs(ktype: str | None = None) -> list[Path]:
    pattern = f"*_{ktype}_*.csv" if ktype else "*.csv"
    paths = sorted(cfg.logs_dir.glob(pattern))
    # deduplicate symbols: keep newest file per symbol+ktype
    seen: dict[str, Path] = {}
    for p in paths:
        key = "_".join(p.stem.split("_")[:4])  # US_SPY_K_5M
        seen[key] = p
    return sorted(seen.values())


ATR_MULTS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5]


def _sweep_multi(dfs: list[pd.DataFrame], paths: list[Path], window_days: int = 90) -> None:
    """ATR sweep aggregated across multiple symbol DataFrames.

    Runs _run_parametric on each symbol per ATR multiplier, combines trade lists,
    then scores consistency via non-overlapping windows.
    """
    # Pre-compute per-symbol: indicators + strict entry mask
    prepped: list[tuple[pd.DataFrame, pd.Series]] = []
    for df in dfs:
        df2 = add_all(df.copy())
        mask = (df2["close"] <= df2["bb_lower"]) & df2["kdj_golden_cross"]
        prepped.append((df2, mask))

    total_candles = sum(len(df) for df, _ in prepped)
    print(f"\n=== ATR sweep (aggregated, {total_candles:,} candles, {len(dfs)} symbols) ===\n")

    hdr = f"{'atr_mult':>8}  {'trades':>6}  {'win%':>6}  {'total_pnl':>10}  {'avg_pnl':>8}  {'pf':>6}  consistency"
    print(hdr)
    print("-" * len(hdr))

    for atr_m in ATR_MULTS:
        all_trades: list[Trade] = []
        win_windows = 0
        total_windows = 0

        for df, mask in prepped:
            # Walk-forward per symbol
            start_ts = df["time_key"].iloc[0]
            end_ts = df["time_key"].iloc[-1]
            ws = start_ts
            while ws < end_ts:
                we = ws + pd.Timedelta(days=window_days)
                chunk_mask = (df["time_key"] >= ws) & (df["time_key"] < we)
                chunk = df[chunk_mask].reset_index(drop=True)
                if len(chunk) >= 20:
                    cm = mask[chunk_mask].reset_index(drop=True)
                    trades = _run_parametric(chunk, cm, atr_mult=atr_m)
                    all_trades.extend(trades)
                    if trades:
                        total_windows += 1
                        if sum(t.pnl for t in trades) > 0:
                            win_windows += 1
                ws = we

        if not all_trades:
            continue
        wins = [t for t in all_trades if t.pnl > 0]
        pf = _profit_factor(all_trades)
        total_pnl = sum(t.pnl for t in all_trades)
        consistency = f"{win_windows}/{total_windows} = {win_windows/total_windows*100:.0f}%" if total_windows else "n/a"
        marker = " <--" if atr_m == 1.0 else ""
        print(
            f"{atr_m:>8}  {len(all_trades):>6}  {len(wins)/len(all_trades)*100:>6.1f}"
            f"  {total_pnl:>+10.4f}  {total_pnl/len(all_trades):>+8.4f}  {pf:>6.3f}  {consistency}{marker}"
        )


def _save_trades(all_trades: list[Trade], paths: list[Path]) -> Path:
    """Write trade log to logs/trades_<ktype>_<date>.csv."""
    from datetime import date
    ktype = _ktype_from_path(paths[0]) if paths else "unknown"
    out_path = cfg.logs_dir / f"trades_{ktype}_{date.today()}.csv"
    rows = []
    for t in all_trades:
        rows.append({
            "entry_time":  t.entry_time,
            "entry_price": round(t.entry_price, 4),
            "exit_time":   t.exit_time,
            "exit_price":  round(t.exit_price, 4),
            "exit_reason": t.exit_reason,
            "pnl":         round(t.pnl, 4),
        })
    pd.DataFrame(rows).to_csv(out_path, index=False)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-symbol backtest comparison")
    parser.add_argument("csvs", nargs="*", help="Candle CSV paths (default: all in logs/)")
    parser.add_argument("--sweep", action="store_true", help="Also run ATR sweep on combined data")
    parser.add_argument("--ktype", default=None, help="Filter CSVs by ktype (e.g. K_5M)")
    parser.add_argument("--window", type=int, default=90, help="Walk-forward window days for sweep")
    parser.add_argument("--save-trades", action="store_true",
                        help="Save trade log to logs/trades_<ktype>_<date>.csv")
    args = parser.parse_args()

    if args.csvs:
        paths = [Path(p) for p in args.csvs]
    else:
        ktype = args.ktype or "K_5M"
        paths = discover_csvs(ktype)

    if not paths:
        print("No CSVs found. Run fetch_candles.py first.")
        sys.exit(1)

    rows: list[dict] = []
    all_trades: list[Trade] = []
    combined_df_parts: list[pd.DataFrame] = []

    for path in paths:
        if not path.exists():
            print(f"Skipping (not found): {path}")
            continue

        symbol = _symbol_from_path(path)
        ktype = _ktype_from_path(path)
        df = load_candles(path)
        log.info("%-12s  %d candles  (%s to %s)",
                 symbol, len(df),
                 df["time_key"].iloc[0].strftime("%Y-%m-%d"),
                 df["time_key"].iloc[-1].strftime("%Y-%m-%d"))

        trades, _ = run_backtest(df)
        all_trades.extend(trades)
        combined_df_parts.append(df)

        s = _summarise(trades)
        s["symbol"] = f"{symbol} {ktype}"
        rows.append(s)

    if not rows:
        print("No data loaded.")
        sys.exit(1)

    print(f"\n=== Multi-symbol backtest ({len(paths)} symbols) ===\n")
    _print_table(rows)

    if len(rows) > 1 and all_trades:
        combined = _combined_row(all_trades)
        print()
        _print_table([combined])

    # exit breakdown per symbol
    if all_trades:
        print()
        reasons: dict[str, int] = {}
        for t in all_trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
        total = len(all_trades)
        print("Exit breakdown (all symbols combined):")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason:<24} {count:>3}  ({count/total*100:.0f}%)")

    if args.save_trades and all_trades:
        out = _save_trades(all_trades, paths)
        print(f"\nTrade log saved: {out}  ({len(all_trades)} trades)")

    if args.sweep and combined_df_parts:
        _sweep_multi(combined_df_parts, paths, window_days=args.window)


if __name__ == "__main__":
    main()
