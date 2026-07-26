#!/usr/bin/env python3
"""Phase 4: Cross-asset BB divergence filter.

Hypothesis: a BB touch on one symbol while peers are ABOVE BB middle (isolated weakness)
is a stronger mean-reversion signal than when all symbols touch BB lower together
(confirmed weakness = trend day, mean reversion fails).

IS=2022-2023, OOS=2024+. Deploy only if OOS PF >= 1.2 with >= 50 signals.

Usage:
    python scripts/mine_cross_asset.py                    # IS + OOS report
    python scripts/mine_cross_asset.py --oos-only         # skip IS, print OOS only
    python scripts/mine_cross_asset.py --quiet            # suppress per-trade log noise
    python scripts/mine_cross_asset.py --details          # show per-symbol breakdown
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.backtest import load_candles, profit_factor
from mm.indicators import add_all
from mm.logger import set_quiet_mode
from mm.strategy import Trade, run_signals

LOGS = Path(__file__).parent.parent / "logs"
SYMBOLS = ["US.SPY", "US.QQQ", "US.IWM"]
IS_END = "2023-12-31"
OOS_START = "2024-01-01"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _csv_path(symbol: str) -> Path:
    key = symbol.replace(".", "_")
    return LOGS / f"{key}_K_5M_combined.csv"


def _load_and_annotate(symbol: str) -> pd.DataFrame:
    """Load candles, compute all indicators + signals, return annotated df."""
    path = _csv_path(symbol)
    df = load_candles(path)
    df = add_all(df)
    df = run_signals(df)
    df["symbol"] = symbol
    df["time_key"] = pd.to_datetime(df["time_key"])
    return df


def _simulate_trade(entry_row: pd.Series, future_df: pd.DataFrame) -> Trade | None:
    """Simulate a bb_kdj trade from entry_row through future_df bars.

    Entry at close of entry_row. Target = bb_middle. Stop = ATR-based (1× ATR).
    Returns a Trade or None if no exit found (open at end of data).
    """
    entry_price = float(entry_row["close"])
    stop_price = entry_price - float(entry_row["atr"])
    target_price = float(entry_row["bb_middle"])

    if target_price <= entry_price:
        return None  # malformed signal (target below entry)

    for _, row in future_df.iterrows():
        close = float(row["close"])
        if close >= target_price:
            return Trade(
                entry_time=str(entry_row["time_key"]),
                entry_price=entry_price,
                exit_time=str(row["time_key"]),
                exit_price=close,
                exit_reason="EXIT_TARGET",
                risk=entry_price - stop_price,
            )
        if close <= stop_price:
            return Trade(
                entry_time=str(entry_row["time_key"]),
                entry_price=entry_price,
                exit_time=str(row["time_key"]),
                exit_price=close,
                exit_reason="EXIT_STOP_LOSS",
                risk=entry_price - stop_price,
            )
    return None


def _categorize(row: pd.Series, peer_dfs: dict[str, pd.DataFrame]) -> str:
    """Classify a bb_touch bar as isolated / confirmed / neutral.

    Isolated:  0 peers at bb_lower, >= 1 peer close >= bb_middle
    Confirmed: >= 1 peer also at bb_lower
    Neutral:   everything else (peers between bands)
    """
    ts = row["time_key"]
    peers_at_lower = 0
    peers_above_middle = 0

    for sym, pdf in peer_dfs.items():
        peer_row = pdf[pdf["time_key"] == ts]
        if peer_row.empty:
            continue
        peer_row = peer_row.iloc[0]
        if bool(peer_row.get("sig_bb_touch", False)):
            peers_at_lower += 1
        elif float(peer_row["close"]) >= float(peer_row["bb_middle"]):
            peers_above_middle += 1

    if peers_at_lower >= 1:
        return "confirmed"
    if peers_above_middle >= 1:
        return "isolated"
    return "neutral"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _run_analysis(
    dfs: dict[str, pd.DataFrame],
    start: str,
    end: str,
    label: str,
    details: bool,
) -> dict:
    """Run cross-asset divergence analysis over a date slice.

    Returns summary dict with per-category results.
    """
    results: dict[str, list[Trade]] = {"isolated": [], "confirmed": [], "neutral": []}
    per_symbol: dict[str, dict[str, list[Trade]]] = {s: {"isolated": [], "confirmed": [], "neutral": []} for s in SYMBOLS}

    for symbol in SYMBOLS:
        df = dfs[symbol]
        peers = {s: dfs[s] for s in SYMBOLS if s != symbol}

        slice_df = df[(df["time_key"] >= start) & (df["time_key"] <= end)].reset_index(drop=True)
        touch_rows = slice_df[slice_df["sig_bb_touch"] == True]

        for idx, row in touch_rows.iterrows():
            category = _categorize(row, peers)

            # Simulate trade: use bars after entry within same symbol
            future = slice_df.iloc[idx + 1 :].reset_index(drop=True)
            trade = _simulate_trade(row, future)
            if trade is None:
                continue

            results[category].append(trade)
            per_symbol[symbol][category].append(trade)

    # Print summary
    print(f"\n{'='*60}")
    print(f"Cross-Asset Divergence — {label}")
    print(f"  Date range: {start} → {end}")
    print(f"{'='*60}")
    print(f"  {'Category':<12}  {'Signals':>8}  {'Win%':>6}  {'PF':>6}  {'Deployable?':>12}")
    print(f"  {'-'*52}")

    summary = {}
    for cat in ("isolated", "confirmed", "neutral"):
        trades = results[cat]
        if not trades:
            print(f"  {cat:<12}  {'0':>8}  {'—':>6}  {'—':>6}  {'—':>12}")
            summary[cat] = {"n": 0, "pf": None, "win_pct": None}
            continue
        wins = [t for t in trades if t.pnl > 0]
        win_pct = 100 * len(wins) / len(trades)
        pf = profit_factor(trades)
        pf_str = f"{pf:.3f}" if pf != float("inf") else "inf"
        deployable = "YES" if (pf >= 1.2 and len(trades) >= 50) else ("maybe" if pf >= 1.1 else "NO")
        print(f"  {cat:<12}  {len(trades):>8}  {win_pct:>5.1f}%  {pf_str:>6}  {deployable:>12}")
        summary[cat] = {"n": len(trades), "pf": pf, "win_pct": win_pct}

    if details:
        print(f"\n  Per-symbol breakdown:")
        for symbol in SYMBOLS:
            print(f"    {symbol}:")
            for cat in ("isolated", "confirmed", "neutral"):
                trades = per_symbol[symbol][cat]
                if not trades:
                    print(f"      {cat:<12}  n=0")
                    continue
                pf = profit_factor(trades)
                wins = [t for t in trades if t.pnl > 0]
                print(f"      {cat:<12}  n={len(trades):>4}  win%={100*len(wins)/len(trades):>5.1f}  PF={pf:.3f}")

    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-asset BB divergence filter (Phase 4)")
    parser.add_argument("--oos-only", action="store_true",
                        help="Skip IS period, print OOS only")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress per-trade log noise (file logs unaffected)")
    parser.add_argument("--details", action="store_true",
                        help="Show per-symbol breakdown within each category")
    args = parser.parse_args()

    if args.quiet:
        set_quiet_mode()

    # Verify CSVs exist
    missing = [s for s in SYMBOLS if not _csv_path(s).exists()]
    if missing:
        print(f"Missing combined CSVs for: {missing}. Run from project root.")
        sys.exit(1)

    print("Loading and annotating candles for all 3 symbols...")
    dfs = {s: _load_and_annotate(s) for s in SYMBOLS}
    total_bars = sum(len(df) for df in dfs.values())
    print(f"  Loaded {total_bars:,} total bars across {len(SYMBOLS)} symbols")

    is_summary = None
    if not args.oos_only:
        is_summary = _run_analysis(dfs, "2022-01-01", IS_END, "IS 2022-2023", args.details)

    oos_summary = _run_analysis(dfs, OOS_START, "2099-12-31", "OOS 2024+", args.details)

    # Deployment verdict
    print(f"\n{'='*60}")
    print("Deployment verdict (OOS 2024+):")
    iso = oos_summary.get("isolated", {})
    conf = oos_summary.get("confirmed", {})
    if iso.get("pf") and iso["pf"] >= 1.2 and iso["n"] >= 50:
        print(f"  ISOLATED edge confirmed: PF={iso['pf']:.3f}, N={iso['n']}")
        print(f"  → Add peer_divergence gate to mm/evals._eval_bb_kdj()")
        print(f"    Block entry when >= 1 peer is also at bb_lower (confirmed category)")
    elif iso.get("pf"):
        print(f"  Isolated PF={iso['pf']:.3f} N={iso['n']} — insufficient for deployment")
        if iso["n"] < 50:
            print(f"  (need >= 50 OOS signals, have {iso['n']})")
        else:
            print(f"  (need PF >= 1.2)")
    else:
        print("  No isolated signals found in OOS period")

    if conf.get("pf"):
        print(f"  Confirmed (all-at-lower): PF={conf['pf']:.3f} N={conf['n']} — "
              f"{'weaker as expected' if conf['pf'] < (iso.get('pf') or 999) else 'unexpectedly strong'}")

    if is_summary and iso.get("pf"):
        is_iso = is_summary.get("isolated", {})
        if is_iso.get("pf"):
            print(f"\n  IS→OOS consistency: isolated PF {is_iso['pf']:.3f} → {iso['pf']:.3f} "
                  f"({'consistent' if abs(is_iso['pf'] - iso['pf']) < 0.2 else 'degraded'})")


if __name__ == "__main__":
    main()
