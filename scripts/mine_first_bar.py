#!/usr/bin/env python3
"""
H1 — Does the 9:30-9:35 first bar predict 10:00-11:00 returns?

OOS discipline:
  IN-SAMPLE  : 2022-01-01 → 2023-12-31  (hypothesis development)
  OUT-OF-SAMPLE: 2024-01-01 → present   (validation)

Decision rule: deploy only if OOS p < 0.05 AND Cohen's d > 0.2 AND n > 100.
Null result → document in docs/strategy_graveyard.md.

Usage:
    python scripts/mine_first_bar.py --all
    python scripts/mine_first_bar.py logs/US_SPY_K_5M_combined.csv
    python scripts/mine_first_bar.py --all --oos-only
"""
from __future__ import annotations

import argparse
import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.backtest import load_candles

DERIVE_END = "2023-12-31"
OOS_START  = "2024-01-01"

_FIRST_BAR  = dtime(9, 35)
_FWD_START  = dtime(10, 0)
_FWD_END    = dtime(11, 0)


def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    """For each trading day, extract first-bar features and 10am-11am forward return."""
    df = df.copy()
    df["ts"]   = pd.to_datetime(df["time_key"])
    df["date"] = df["ts"].dt.date
    df["t"]    = df["ts"].dt.time

    rows = []
    for date, g in df.groupby("date"):
        first = g[g["t"] == _FIRST_BAR]
        fwd   = g[(g["t"] >= _FWD_START) & (g["t"] <= _FWD_END)]
        if first.empty or len(fwd) < 3:
            continue
        f = first.iloc[0]
        body      = float(f["close"]) - float(f["open"])
        rng       = float(f["high"]) - float(f["low"])
        o         = float(f["open"])
        fwd_open  = float(fwd.iloc[0]["open"])
        fwd_close = float(fwd.iloc[-1]["close"])
        fwd_ret   = (fwd_close - fwd_open) / fwd_open * 100 if fwd_open else 0.0
        rows.append({
            "date":              str(date),
            "first_bar_dir":     1 if body > 0 else -1,
            "first_bar_body_pct": body / o * 100 if o else 0.0,
            "first_bar_range_pct": rng / o * 100 if o else 0.0,
            "fwd_ret_pct":       fwd_ret,
        })
    return pd.DataFrame(rows)


def report(feat: pd.DataFrame, label: str) -> bool:
    """Print stats and return True if the OOS null hypothesis is rejected."""
    from scipy import stats as sp

    if feat.empty or len(feat) < 20:
        print(f"{label}: insufficient data (n={len(feat)})")
        return False

    up   = feat[feat["first_bar_dir"] ==  1]["fwd_ret_pct"]
    down = feat[feat["first_bar_dir"] == -1]["fwd_ret_pct"]

    if len(up) < 5 or len(down) < 5:
        print(f"{label}: too few samples in one direction (up={len(up)}, down={len(down)})")
        return False

    corr, p_corr = sp.pearsonr(feat["first_bar_body_pct"], feat["fwd_ret_pct"])
    _, p_mw      = sp.mannwhitneyu(up, down, alternative="two-sided")
    pooled_std   = feat["fwd_ret_pct"].std()
    cohens_d     = (up.mean() - down.mean()) / pooled_std if pooled_std else 0.0

    print(f"\n{label}  (n={len(feat)} days)")
    print(f"  Up-bar   fwd ret:  mean={up.mean():+.3f}%  median={up.median():+.3f}%  n={len(up)}")
    print(f"  Down-bar fwd ret:  mean={down.mean():+.3f}%  median={down.median():+.3f}%  n={len(down)}")
    print(f"  Pearson  r={corr:+.3f}   p={p_corr:.4f}")
    print(f"  Mann-Whitney       p={p_mw:.4f}   Cohen's d={cohens_d:+.3f}")

    signal = p_mw < 0.05 and abs(cohens_d) > 0.2 and len(feat) >= 100
    verdict = "SIGNAL — worth investigating further" if signal else "NULL — no meaningful edge"
    print(f"  → {verdict}")
    return signal


def run_file(path: Path, oos_only: bool = False) -> None:
    sym = path.stem.split("_K_")[0].replace("_", ".", 1)
    print(f"\n{'='*60}")
    print(f"{sym}  ({path.name})")

    df   = load_candles(path)
    feat = extract_features(df)

    if feat.empty:
        print("  No features extracted — check candle data.")
        return

    print(f"  Total days with data: {len(feat)}  "
          f"({feat['date'].min()} → {feat['date'].max()})")

    if not oos_only:
        derive = feat[feat["date"] <= DERIVE_END]
        report(derive, f"  IN-SAMPLE  (≤ {DERIVE_END})")

    oos = feat[feat["date"] >= OOS_START]
    signal = report(oos, f"  OOS        (≥ {OOS_START})")

    if signal:
        print(f"\n  *** DEPLOY CANDIDATE — verify with walk_forward before wiring into evals.py ***")
    else:
        print(f"\n  Document null result in docs/strategy_graveyard.md if not already there.")


def main() -> None:
    try:
        from scipy import stats  # noqa: F401
    except ImportError:
        print("ERROR: scipy not installed. Run: pip install scipy")
        sys.exit(1)

    ap = argparse.ArgumentParser(description="H1: first-bar predictive analysis")
    ap.add_argument("csvs", nargs="*", help="Candle CSV paths")
    ap.add_argument("--all", action="store_true",
                    help="Run on all US_*_K_5M_combined.csv files in logs/")
    ap.add_argument("--oos-only", action="store_true",
                    help="Skip in-sample section, show OOS only")
    args = ap.parse_args()

    logs = Path("logs")
    paths: list[Path] = []
    if args.csvs:
        paths = [Path(p) for p in args.csvs]
    elif args.all:
        paths = sorted(logs.glob("US_*_K_5M_combined.csv"))
    else:
        ap.print_help()
        sys.exit(1)

    if not paths:
        print("No CSVs found.")
        sys.exit(1)

    for p in paths:
        run_file(p, oos_only=args.oos_only)


if __name__ == "__main__":
    main()
