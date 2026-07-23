#!/usr/bin/env python3
"""
H3 — Lag-1 autocorrelation of 5-min returns by hour-of-day bucket.

Is the market momentum or mean-reverting at different times of day?
  Positive autocorr → momentum (up bar predicts up bar)
  Negative autocorr → mean-reversion (up bar predicts down bar)

OOS discipline:
  IN-SAMPLE  : 2022-01-01 → 2023-12-31
  OUT-OF-SAMPLE: 2024-01-01 → present

Decision rule: deploy only if OOS |r| > 0.05 AND p < 0.01 AND n > 200 bars in that bucket.
(Lower r threshold than H1 — autocorr of 0.05 is meaningful at high sample counts.)

Usage:
    python scripts/mine_autocorrelation.py --all
    python scripts/mine_autocorrelation.py logs/US_SPY_K_5M_combined.csv
    python scripts/mine_autocorrelation.py --all --oos-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.backtest import load_candles

DERIVE_END = "2023-12-31"
OOS_START  = "2024-01-01"

_HOUR_BUCKETS = [
    ("09:30–10:00", 9, 30, 10,  0),
    ("10:00–11:00", 10,  0, 11,  0),
    ("11:00–12:00", 11,  0, 12,  0),
    ("12:00–13:00", 12,  0, 13,  0),
    ("13:00–14:00", 13,  0, 14,  0),
    ("14:00–15:00", 14,  0, 15,  0),
    ("15:00–16:00", 15,  0, 16,  1),
]


def _bucket_label(h: int, m: int) -> str:
    for label, sh, sm, eh, em in _HOUR_BUCKETS:
        bar_mins = h * 60 + m
        if sh * 60 + sm <= bar_mins < eh * 60 + em:
            return label
    return "other"


def build_returns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ts"]     = pd.to_datetime(df["time_key"])
    df["date"]   = df["ts"].dt.date
    df["h"]      = df["ts"].dt.hour
    df["m"]      = df["ts"].dt.minute
    df["ret"]    = df["close"].pct_change()
    df["bucket"] = df.apply(lambda r: _bucket_label(r["h"], r["m"]), axis=1)
    df["lag1"]   = df["ret"].shift(1)
    # don't let lag cross day boundary
    df.loc[df["date"] != df["date"].shift(1), "lag1"] = float("nan")
    return df.dropna(subset=["ret", "lag1"])


def report_bucket(sub: pd.DataFrame, label: str, bucket: str) -> bool:
    from scipy import stats as sp

    rows = sub[sub["bucket"] == bucket].dropna(subset=["ret", "lag1"])
    n = len(rows)
    if n < 50:
        print(f"    {bucket:<18}  n={n:<5}  (too few bars)")
        return False

    r, p = sp.pearsonr(rows["lag1"], rows["ret"])
    signal = abs(r) > 0.05 and p < 0.01 and n >= 200
    flag = " ***" if signal else ""
    print(f"    {bucket:<18}  n={n:<5}  r={r:+.4f}  p={p:.4f}{flag}")
    return signal


def run_file(path: Path, oos_only: bool = False) -> None:
    sym = path.stem.split("_K_")[0].replace("_", ".", 1)
    print(f"\n{'='*60}")
    print(f"{sym}  ({path.name})")

    df = load_candles(path)
    rets = build_returns(df)

    print(f"  Total bars with data: {len(rets)}  "
          f"({str(rets['date'].min())} → {str(rets['date'].max())})")

    any_signal = False

    if not oos_only:
        is_data = rets[rets["date"].astype(str) <= DERIVE_END]
        print(f"\n  IN-SAMPLE (≤ {DERIVE_END})  n_bars={len(is_data)}")
        for label, *_ in _HOUR_BUCKETS:
            report_bucket(is_data, "IS", label)

    oos_data = rets[rets["date"].astype(str) >= OOS_START]
    print(f"\n  OOS (≥ {OOS_START})  n_bars={len(oos_data)}")
    for label, *_ in _HOUR_BUCKETS:
        sig = report_bucket(oos_data, "OOS", label)
        any_signal = any_signal or sig

    if any_signal:
        print(f"\n  *** SIGNAL — bucket(s) marked ***. Verify with walk-forward before deploying.")
    else:
        print(f"\n  NULL — no meaningful autocorrelation in any time bucket.")
        print(f"  Document in docs/strategy_graveyard.md.")


def main() -> None:
    try:
        from scipy import stats  # noqa: F401
    except ImportError:
        print("ERROR: scipy not installed. Run: pip install scipy")
        sys.exit(1)

    ap = argparse.ArgumentParser(description="H3: lag-1 autocorrelation by hour bucket")
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
