"""Portfolio-level correlation and exposure analysis across all deployed strategies.

Replays the historical trade lists of bb_kdj + orb + vwap_pb on the combined CSVs
as if they had traded together, then answers:

  1. How correlated are the strategies' daily PnL streams?
  2. How often are positions held concurrently (and how many at once)?
  3. What does the worst combined day look like vs MAX_DAILY_LOSS?
  4. Portfolio max drawdown on the combined equity curve.

All PnL is per-share (1 share per trade) — same convention as the backtests.
Run:  python scripts/analyze_portfolio.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.backtest import load_candles, run_backtest          # noqa: E402
from mm.orb_strategy import run_orb_signals                 # noqa: E402
from mm.vwap_pullback import run_vwap_pullback              # noqa: E402
from mm.config import cfg                                   # noqa: E402

LOGS = Path(__file__).parent.parent / "logs"
SYMBOLS = ["US.SPY", "US.QQQ", "US.IWM"]
VWAP_PB_SYMBOLS = {"US.SPY", "US.QQQ"}  # IWM fails OOS — matches deployment


def section(title: str) -> None:
    print(f"\n{'=' * 64}\n  {title}\n{'=' * 64}")


def _collect_trades() -> list[dict]:
    """Run all three strategy engines on all symbols; return normalized trade dicts."""
    trades: list[dict] = []
    for sym in SYMBOLS:
        path = LOGS / f"{sym.replace('.', '_')}_K_5M_combined.csv"
        if not path.exists():
            print(f"  WARNING: {path.name} missing — skipping {sym}")
            continue
        df = load_candles(path)

        bb, _ = run_backtest(df)
        for t in bb:
            trades.append({"strategy": "bb_kdj", "symbol": sym, "entry_time": t.entry_time,
                           "exit_time": t.exit_time, "pnl": t.pnl})

        orb_minutes = cfg.orb_minutes_overrides.get(sym, cfg.orb_minutes)
        orb, _ = run_orb_signals(df, orb_minutes=orb_minutes)
        for t in orb:
            trades.append({"strategy": "orb", "symbol": sym, "entry_time": t.entry_time,
                           "exit_time": t.exit_time, "pnl": t.pnl})

        if sym in VWAP_PB_SYMBOLS:
            for t in run_vwap_pullback(df):
                trades.append({"strategy": "vwap_pb", "symbol": sym, "entry_time": t.entry_time,
                               "exit_time": t.exit_time, "pnl": t.pnl})

        print(f"  {sym}: bb_kdj={len(bb)}  orb={len(orb)}  "
              f"vwap_pb={'excluded' if sym not in VWAP_PB_SYMBOLS else sum(1 for x in trades if x['strategy'] == 'vwap_pb' and x['symbol'] == sym)}")
    return trades


def _daily_pnl(trades: list[dict], key: str) -> pd.DataFrame:
    """Daily PnL pivot: index=date, columns=key (strategy or symbol)."""
    rows = [{"date": t["exit_time"].date(), "k": t[key], "pnl": t["pnl"]} for t in trades]
    df = pd.DataFrame(rows)
    return df.pivot_table(index="date", columns="k", values="pnl", aggfunc="sum").fillna(0.0)


def _correlation(trades: list[dict]) -> None:
    section("1. DAILY PnL CORRELATION BETWEEN STRATEGIES")
    pivot = _daily_pnl(trades, "strategy")
    # Only days where at least one strategy traded are present; correlation on those.
    corr = pivot.corr()
    print(f"  Active days in sample: {len(pivot)}\n")
    print(corr.round(3).to_string())
    print("\n  (Computed on days with ≥1 trade. Low values = diversification is real;")
    print("   high values = the strategies lose together and MAX_DAILY_LOSS does the work.)")


def _concurrency(trades: list[dict]) -> None:
    section("2. CONCURRENT POSITION EXPOSURE")
    events = []
    for t in trades:
        events.append((t["entry_time"], 1, t))
        events.append((t["exit_time"], -1, t))
    events.sort(key=lambda e: (e[0], -e[1]))  # entries before exits at same ts = conservative

    open_now = 0
    peak = 0
    peak_at = None
    concurrent_bars = 0
    total_open_events = 0
    overlap_pairs: dict[tuple, int] = defaultdict(int)
    open_set: list[dict] = []

    for ts, delta, t in events:
        if delta == 1:
            for o in open_set:
                pair = tuple(sorted([o["strategy"], t["strategy"]]))
                overlap_pairs[pair] += 1
            open_set.append(t)
            open_now += 1
            total_open_events += 1
            if open_now > peak:
                peak, peak_at = open_now, ts
            if open_now > 1:
                concurrent_bars += 1
        else:
            open_now -= 1
            if t in open_set:
                open_set.remove(t)

    print(f"  Total positions opened:      {total_open_events}")
    print(f"  Peak simultaneous positions: {peak}  (at {peak_at})")
    print(f"  Entries while ≥1 already open: {concurrent_bars} "
          f"({100 * concurrent_bars / total_open_events:.1f}% of entries)")
    print("\n  Overlap counts by strategy pair (entry while other was open):")
    for pair, n in sorted(overlap_pairs.items(), key=lambda x: -x[1]):
        print(f"    {pair[0]} + {pair[1]}: {n}")


def _worst_days(trades: list[dict]) -> None:
    section("3. WORST COMBINED DAYS  (vs MAX_DAILY_LOSS)")
    pivot = _daily_pnl(trades, "strategy")
    daily = pivot.sum(axis=1).sort_values()
    print(f"  MAX_DAILY_LOSS currently: ${cfg.max_daily_loss:.0f} "
          f"(per-share PnL below is NOT directly comparable at size —")
    print("   multiply by your typical qty to sanity-check headroom)\n")
    print(f"  {'Date':<12} {'Total':>8}   breakdown")
    for date, total in daily.head(10).items():
        parts = ", ".join(f"{k}={v:+.2f}" for k, v in pivot.loc[date].items() if v != 0)
        print(f"  {str(date):<12} {total:>+8.2f}   {parts}")
    n_loss = (daily < 0).sum()
    print(f"\n  Losing days: {n_loss}/{len(daily)} ({100 * n_loss / len(daily):.0f}%)  "
          f"Avg day: {daily.mean():+.2f}  Worst: {daily.min():+.2f}")


def _drawdown(trades: list[dict]) -> None:
    section("4. COMBINED EQUITY CURVE / MAX DRAWDOWN")
    pivot = _daily_pnl(trades, "strategy")
    equity = pivot.sum(axis=1).cumsum()
    peak = equity.cummax()
    dd = equity - peak
    max_dd = dd.min()
    max_dd_date = dd.idxmin()
    print(f"  Final equity (per-share): {equity.iloc[-1]:+.2f}")
    print(f"  Max drawdown:             {max_dd:+.2f}  (trough {max_dd_date})")
    print(f"  Longest underwater:       {(dd < 0).astype(int).groupby((dd >= 0).cumsum()).sum().max()} active days")


def main() -> None:
    print("Running all three strategy engines on combined CSVs (uses current .env config)...")
    print(f"  KDJ_WINDOW_BARS={cfg.kdj_window_bars}  MIN_SIGNAL_SCORE={cfg.min_signal_score}  "
          f"ORB_MINUTES={cfg.orb_minutes}  overrides={cfg.orb_minutes_overrides}")
    trades = _collect_trades()
    if not trades:
        print("No trades produced — check that combined CSVs exist in logs/.")
        sys.exit(1)
    print(f"\n  Total trades across portfolio: {len(trades)}")
    _correlation(trades)
    _concurrency(trades)
    _worst_days(trades)
    _drawdown(trades)
    print()


if __name__ == "__main__":
    main()
