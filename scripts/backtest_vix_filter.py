"""Backtest VIX daily regime filter on BB+KDJ strategy.

Downloads CBOE VIX daily data via yfinance, joins to combined candle CSVs,
and tests whether blocking (or relaxing) entries on high/low VIX days improves
out-of-sample performance.

Usage:
    python scripts/backtest_vix_filter.py [--all] [--symbols US.SPY,US.QQQ,US.IWM]
    python scripts/backtest_vix_filter.py --all  # default: SPY + QQQ + IWM

Outputs a comparison table. Thresholds tested:
  Baseline     — no VIX filter
  Block >= 20  — skip entries on days where VIX >= 20
  Block >= 25  — skip entries on days where VIX >= 25 (plan default)
  Block >= 30  — skip entries on days where VIX >= 30
  Relax > 30   — use min_bonus=1 instead of 2 when VIX > 30 (crisis MR mode)

OOS split: train=2022-2023, test=2024-present.
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from mm.config import cfg
from mm.indicators import add_all
from mm.signals import score_df
from mm.strategy import Signal, Trade


# ---------------------------------------------------------------------------
# VIX data
# ---------------------------------------------------------------------------

def fetch_vix(start: str = "2022-01-01") -> dict[date, float]:
    """Download VIX daily closes from Yahoo Finance. Returns {date: vix_close}."""
    try:
        import yfinance as yf
    except ImportError:
        print("ERROR: yfinance not installed. Run: pip install yfinance")
        sys.exit(1)

    end = datetime.now().strftime("%Y-%m-%d")
    print(f"Fetching VIX daily data {start} → {end} via yfinance...")
    df = yf.download("^VIX", start=start, end=end, auto_adjust=False, progress=False)
    if df.empty:
        print("ERROR: VIX download returned empty DataFrame.")
        sys.exit(1)

    # yfinance may return MultiIndex columns — flatten
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    closes = df["Close"].dropna()
    result = {pd.Timestamp(ts).date(): float(v) for ts, v in closes.items()}
    print(f"  Got {len(result)} VIX daily observations")
    return result


# ---------------------------------------------------------------------------
# VIX-aware backtest engine
# ---------------------------------------------------------------------------

def _run_vix_backtest(
    df: pd.DataFrame,
    vix: dict[date, float],
    block_threshold: float | None = None,   # skip entry if VIX >= this
    relax_threshold: float | None = None,   # use min_bonus=1 if VIX > this
    min_bonus: int = 2,
    kdj_window: int = 3,
    atr_stop_mult: float = 1.0,
) -> list[Trade]:
    """Run BB+KDJ backtest with optional VIX entry gate."""
    df = add_all(df.copy())
    df = score_df(df)
    df["time_key"] = pd.to_datetime(df["time_key"])

    # KDJ window — rolling max of sig_kdj_cross over last N bars
    if kdj_window > 0:
        kdj_in_window = (
            df["sig_kdj_cross"]
            .rolling(window=kdj_window + 1, min_periods=1)
            .max()
            .fillna(False)
            .astype(bool)
        )
    else:
        kdj_in_window = df["sig_kdj_cross"].astype(bool)

    bonus_cols = ["sig_rsi_oversold", "sig_ranging", "sig_volume_spike"]
    df["bonus_score"] = df[bonus_cols].sum(axis=1).astype(int)

    trades: list[Trade] = []
    position_entry: dict | None = None

    for _, row in df.iterrows():
        bar_date = pd.Timestamp(row["time_key"]).date()
        vix_today = vix.get(bar_date)

        if position_entry is None:
            # VIX block: skip entry entirely
            if block_threshold is not None and vix_today is not None:
                if vix_today >= block_threshold:
                    continue

            # VIX relax: lower the bonus bar on crisis days
            effective_min_bonus = min_bonus
            if relax_threshold is not None and vix_today is not None:
                if vix_today > relax_threshold:
                    effective_min_bonus = 1

            core = bool(row["sig_bb_touch"]) and bool(kdj_in_window.loc[row.name])
            bonus = int(row["bonus_score"])
            if core and bonus >= effective_min_bonus:
                position_entry = {
                    "entry_time": row["time_key"],
                    "entry_price": row["close"],
                    "stop_price": row["close"] - atr_stop_mult * float(row["atr"]),
                    "bb_middle": float(row["bb_middle"]),
                }
        else:
            exit_reason: str | None = None
            if row["close"] >= position_entry["bb_middle"]:
                exit_reason = "TARGET"
            elif row["close"] < position_entry["stop_price"]:
                exit_reason = "STOP"

            if exit_reason:
                trade = Trade(
                    entry_time=position_entry["entry_time"],
                    entry_price=position_entry["entry_price"],
                    exit_time=row["time_key"],
                    exit_price=row["close"],
                    exit_reason=exit_reason,
                )
                trades.append(trade)
                position_entry = None

    return trades


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dataclass
class Stats:
    label: str
    trades: int
    wins: int
    total_pnl: float
    profit_factor: float
    win_rate: float

    def __str__(self) -> str:
        return (
            f"{self.label:<22} {self.trades:>6}  {self.win_rate:>6.1f}%  "
            f"{self.profit_factor:>6.3f}  {self.total_pnl:>+8.2f}"
        )


def _stats(label: str, trades: list[Trade]) -> Stats:
    if not trades:
        return Stats(label, 0, 0, 0.0, 0.0, 0.0)
    wins = [t for t in trades if t.pnl > 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    return Stats(
        label=label,
        trades=len(trades),
        wins=len(wins),
        total_pnl=sum(t.pnl for t in trades),
        profit_factor=pf,
        win_rate=len(wins) / len(trades) * 100,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

VARIANTS: list[tuple[str, dict]] = [
    ("Baseline",    {}),
    ("Block >= 20", {"block_threshold": 20.0}),
    ("Block >= 25", {"block_threshold": 25.0}),
    ("Block >= 30", {"block_threshold": 30.0}),
    ("Relax > 30",  {"relax_threshold": 30.0}),
]


def _run_symbol(path: Path, vix: dict[date, float]) -> None:
    symbol = path.stem.replace("_K_5M_combined", "").replace("_", ".", 1)
    print(f"\n{'='*65}")
    print(f"  {symbol}  —  {path.name}")
    print(f"{'='*65}")

    df_full = pd.read_csv(path)
    df_full["time_key"] = pd.to_datetime(df_full["time_key"])

    oos_split = pd.Timestamp("2024-01-01")
    df_train = df_full[df_full["time_key"] < oos_split].copy()
    df_test  = df_full[df_full["time_key"] >= oos_split].copy()

    print(f"  Full: {len(df_full):,} bars  |  Train (2022-23): {len(df_train):,}  |  OOS (2024+): {len(df_test):,}\n")

    header = f"  {'Variant':<22} {'Trades':>6}  {'Win%':>7}  {'PF':>6}  {'PnL':>8}"
    divider = "  " + "-" * 58

    # In-sample (full)
    print("  IN-SAMPLE (full 2022–present)")
    print(header)
    print(divider)
    for label, kwargs in VARIANTS:
        trades = _run_vix_backtest(df_full, vix, **kwargs)
        print(" ", _stats(label, trades))

    # OOS
    print(f"\n  OOS (test 2024–present, {len(df_test):,} bars)")
    print(header)
    print(divider)
    for label, kwargs in VARIANTS:
        trades = _run_vix_backtest(df_test, vix, **kwargs)
        print(" ", _stats(label, trades))


def _run_combined(paths: list[Path], vix: dict[date, float]) -> None:
    print(f"\n{'='*65}")
    print(f"  COMBINED ({', '.join(p.stem.split('_')[1] for p in paths)})")
    print(f"{'='*65}")

    frames = {p: pd.read_csv(p) for p in paths}
    for df in frames.values():
        df["time_key"] = pd.to_datetime(df["time_key"])

    oos_split = pd.Timestamp("2024-01-01")

    header = f"  {'Variant':<22} {'Trades':>6}  {'Win%':>7}  {'PF':>6}  {'PnL':>8}"
    divider = "  " + "-" * 58

    def _combined_trades(df_slice_fn, **kwargs):
        all_trades = []
        for df in frames.values():
            chunk = df_slice_fn(df).copy()
            if len(chunk) > 20:
                all_trades += _run_vix_backtest(chunk, vix, **kwargs)
        return all_trades

    print("\n  IN-SAMPLE (full 2022–present)")
    print(header)
    print(divider)
    for label, kwargs in VARIANTS:
        trades = _combined_trades(lambda df: df, **kwargs)
        print(" ", _stats(label, trades))

    print(f"\n  OOS (test 2024–present)")
    print(header)
    print(divider)
    for label, kwargs in VARIANTS:
        trades = _combined_trades(lambda df: df[df["time_key"] >= oos_split], **kwargs)
        print(" ", _stats(label, trades))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest VIX daily regime filter on BB+KDJ.")
    parser.add_argument("--all", action="store_true", help="Use all combined CSVs")
    parser.add_argument("--symbols", help="Comma-separated symbols, e.g. US.SPY,US.QQQ")
    args = parser.parse_args()

    logs_dir = ROOT / "logs"

    if args.symbols:
        syms = [s.strip() for s in args.symbols.split(",")]
        paths = [logs_dir / f"{s.replace('.', '_')}_K_5M_combined.csv" for s in syms]
    else:
        paths = sorted(logs_dir.glob("*_K_5M_combined.csv"))

    paths = [p for p in paths if p.exists()]
    if not paths:
        print("No combined CSV files found. Run fetch_candles.py first.")
        sys.exit(1)

    print(f"Found {len(paths)} symbol file(s): {[p.name for p in paths]}")

    vix = fetch_vix()

    for path in paths:
        _run_symbol(path, vix)

    if len(paths) > 1:
        _run_combined(paths, vix)

    print("\nDone. Deploy VIX filter only if OOS PF improves vs Baseline.")


if __name__ == "__main__":
    main()
