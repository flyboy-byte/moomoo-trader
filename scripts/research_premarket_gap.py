#!/usr/bin/env python3
"""
Pre-market feature research for Gap Fade.

Fetches recent extended-hours candles (extended_time=True), derives pre-market
fill % and pre-market volume ratio per gap day, and joins them onto the
existing Gap Fade trades from the RTH-only combined CSVs. Prints a breakdown
table testing the noise-gap filter hypothesis from docs/deep/ research:
low pre-market volume + gap still mostly intact at 9:30 = fade; high volume +
already-faded = stand aside.

This is research-only: it does not change mm/gap_fade.py's live entry logic.

Usage:
    python scripts/research_premarket_gap.py --symbol US.IWM
    python scripts/research_premarket_gap.py --symbol US.IWM --start 2026-01-01
    python scripts/research_premarket_gap.py --symbol US.IWM --details
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.data import fetch_candles                       # noqa: E402
from mm.backtest import load_candles, profit_factor      # noqa: E402
from mm.gap_fade import _build_day_map, run_gap_fade      # noqa: E402
from mm.premarket import (                                # noqa: E402
    premarket_session, premarket_fill_pct, premarket_volume_ratio,
    build_premarket_volume_history, attach_atr, gap_atr_mult,
)

LOGS = Path(__file__).parent.parent / "logs"
_COMBINED = {
    "US.SPY": "US_SPY_K_5M_combined.csv",
    "US.QQQ": "US_QQQ_K_5M_combined.csv",
    "US.IWM": "US_IWM_K_5M_combined.csv",
}


def _bucket(value: float | None, edges: list[float], labels: list[str]) -> str:
    if value is None:
        return "n/a"
    for edge, label in zip(edges, labels):
        if value < edge:
            return label
    return labels[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-market gap-fade feature research")
    parser.add_argument("--symbol", default="US.IWM")
    parser.add_argument("--start", default=None, help="YYYY-MM-DD (default: as far back as Moomoo returns)")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD")
    parser.add_argument("--details", action="store_true", help="Dump per-day feature table")
    args = parser.parse_args()

    rth_path = LOGS / _COMBINED.get(args.symbol, "")
    if not rth_path.exists():
        print(f"No combined RTH CSV found for {args.symbol} at {rth_path}")
        sys.exit(1)

    print(f"Fetching extended-hours candles for {args.symbol} "
          f"(start={args.start or 'default 30d'}, end={args.end or 'today'})...")
    df_ext = fetch_candles(symbol=args.symbol, ktype="K_5M", start=args.start, end=args.end,
                            extended_time=True)
    if df_ext.empty:
        print("No extended-hours data returned. Check OpenD connection / symbol entitlement.")
        sys.exit(1)
    print(f"Fetched {len(df_ext)} extended-hours bars.")

    sessions = premarket_session(df_ext)
    if not sessions:
        print("No bars fell inside the 4:00-9:30 ET premarket window. "
              "This may mean Moomoo's extended_time data doesn't cover that range for this "
              "symbol/period — flagged as a live-test unknown in the research.")
        sys.exit(1)
    print(f"Found premarket sessions for {len(sessions)} days.")

    pm_vol_history = build_premarket_volume_history(sessions)
    pm_vol_avg20 = pm_vol_history.rolling(20).mean().shift(1)

    df_rth = load_candles(rth_path)
    df_rth = attach_atr(df_rth)
    day_map = _build_day_map(df_rth)

    # Map date -> last RTH ATR value of the prior trading day, for gap_atr_mult.
    df_rth["_date"] = df_rth["time_key"].dt.date
    last_atr_by_date = df_rth.groupby("_date")["atr"].last().to_dict()
    sorted_dates = sorted(last_atr_by_date.keys())

    trades = run_gap_fade(df_rth.copy())
    trades_by_date = {t.entry_time.date(): t for t in trades}

    rows = []
    for date, info in day_map.items():
        if date not in sessions:
            continue
        prev_close, today_open = info["prev_close"], info["open"]
        gap_pct = (today_open - prev_close) / prev_close
        pm_bars = sessions[date]

        fill_pct = premarket_fill_pct(prev_close, today_open, pm_bars)
        today_vol = float(pm_bars["volume"].sum())
        avg20 = pm_vol_avg20.get(pd.Timestamp(date))
        vol_ratio = premarket_volume_ratio(today_vol, avg20) if avg20 and avg20 > 0 else None

        idx = sorted_dates.index(date) if date in sorted_dates else None
        prior_atr = last_atr_by_date[sorted_dates[idx - 1]] if idx else None
        atr_mult = gap_atr_mult(gap_pct, today_open, prior_atr)

        trade = trades_by_date.get(date)
        rows.append({
            "date": date, "gap_pct": gap_pct, "fill_pct": fill_pct, "vol_ratio": vol_ratio,
            "atr_mult": atr_mult, "traded": trade is not None,
            "pnl": trade.pnl if trade else None,
            "reason": trade.exit_reason if trade else None,
        })

    traded_rows = [r for r in rows if r["traded"]]
    print(f"\n{len(rows)} gap days with premarket coverage; "
          f"{len(traded_rows)} of those produced a Gap Fade trade.\n")

    if args.details:
        print(f"  {'Date':<12} {'Gap%':>7} {'Fill%':>7} {'VolRatio':>9} {'ATRx':>6} "
              f"{'Traded':>7} {'PnL':>8} {'Reason':<10}")
        for r in sorted(rows, key=lambda r: r["date"]):
            fp = f"{r['fill_pct']*100:.0f}%" if r["fill_pct"] is not None else "n/a"
            vr = f"{r['vol_ratio']:.2f}" if r["vol_ratio"] is not None else "n/a"
            am = f"{r['atr_mult']:.2f}" if r["atr_mult"] is not None else "n/a"
            pnl = f"{r['pnl']:+.3f}" if r["pnl"] is not None else "-"
            reason = r["reason"] or "-"
            print(f"  {str(r['date']):<12} {r['gap_pct']*100:>+6.2f}% {fp:>7} {vr:>9} "
                  f"{am:>6} {'YES' if r['traded'] else 'no':>7} {pnl:>8} {reason:<10}")
        print()

    # Breakdown: win rate / PF by premarket volume tier, among traded days only.
    def _pf_winrate(group: list[dict]) -> tuple[str, str, int]:
        pnls = [r["pnl"] for r in group if r["pnl"] is not None]
        if not pnls:
            return "n/a", "n/a", 0
        wins = sum(1 for p in pnls if p > 0)
        pf = profit_factor(pnls)
        pf_str = "inf" if pf == float("inf") else f"{pf:.3f}"
        return f"{100*wins/len(pnls):.0f}%", pf_str, len(pnls)

    print("=" * 60)
    print("  Volume-ratio tier breakdown (traded days only)")
    print("=" * 60)
    vol_edges, vol_labels = [1.0, 1.5], ["<1.0x (low)", "1.0-1.5x (med)", ">=1.5x (high)"]
    for label in vol_labels:
        group = [r for r in traded_rows if r["vol_ratio"] is not None
                  and _bucket(r["vol_ratio"], vol_edges, vol_labels) == label]
        wr, pf, n = _pf_winrate(group)
        print(f"  {label:<16} n={n:<4} win%={wr:<6} PF={pf}")

    print()
    print("=" * 60)
    print("  Pre-market fill% tier breakdown (traded days only)")
    print("=" * 60)
    fill_edges, fill_labels = [0.3, 0.7], ["<30% intact", "30-70% partial", ">=70% mostly filled"]
    for label in fill_labels:
        group = [r for r in traded_rows if r["fill_pct"] is not None
                  and _bucket(r["fill_pct"], fill_edges, fill_labels) == label]
        wr, pf, n = _pf_winrate(group)
        print(f"  {label:<20} n={n:<4} win%={wr:<6} PF={pf}")

    print()
    print("Note: this is a research breakdown only. mm/gap_fade.py's live entry logic is "
          "unchanged. See GAP_PREMARKET_FILTER_ENABLED in mm/config.py (dark by default) for "
          "the scaffolding to enable a validated filter later.")


if __name__ == "__main__":
    main()
