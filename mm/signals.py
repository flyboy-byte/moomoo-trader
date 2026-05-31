"""
Signal scoring engine.

Each signal is an independent evidence source that votes yes/no on a bar.
A trade fires when enough signals agree (score >= MIN_SIGNAL_SCORE).

Signals:
  bb_touch      — price at or below Bollinger lower band (entry zone)
  kdj_cross     — KDJ golden cross (momentum turning up)
  rsi_oversold  — RSI < threshold (independent oversold confirmation)
  ranging       — ADX < threshold (mean-reversion only in ranging markets)
  volume_spike  — volume > N× 20-bar average (unusual activity)

Adding a signal: one line in SIGNALS dict. All downstream code adapts automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

RSI_OVERSOLD: float = 35.0
ADX_RANGING: float = 25.0
VOLUME_SPIKE_MULT: float = 1.5

SIGNALS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "bb_touch":     lambda df: df["close"] <= df["bb_lower"],
    "kdj_cross":    lambda df: df["kdj_golden_cross"].astype(bool),
    "rsi_oversold": lambda df: df["rsi"] < RSI_OVERSOLD,
    "ranging":      lambda df: df["adx"] < ADX_RANGING,
    "volume_spike": lambda df: df["volume"] > VOLUME_SPIKE_MULT * df["volume_ma"],
}


@dataclass(frozen=True)
class SignalSnapshot:
    """Per-bar signal state — used in the live paper runner for logging."""
    score: int
    max_score: int
    details: dict[str, bool]

    @property
    def pct(self) -> float:
        return self.score / self.max_score if self.max_score else 0.0

    def __str__(self) -> str:
        flags = "  ".join(f"{'✓' if v else '✗'} {k}" for k, v in self.details.items())
        return f"[{self.score}/{self.max_score}]  {flags}"


def score_df(df: pd.DataFrame) -> pd.DataFrame:
    """Add sig_* columns and signal_score column to an indicators-enriched DataFrame.

    Expects df to already have bb_lower, kdj_golden_cross, rsi, adx, volume, volume_ma columns.
    """
    df = df.copy()
    for name, fn in SIGNALS.items():
        df[f"sig_{name}"] = fn(df).fillna(False)
    sig_cols = [f"sig_{n}" for n in SIGNALS]
    df["signal_score"] = df[sig_cols].sum(axis=1).astype(int)
    return df


def snapshot(row: pd.Series) -> SignalSnapshot:
    """Evaluate all signals for a single bar — used by the live paper runner."""
    details = {
        "bb_touch":     bool(row["close"] <= row["bb_lower"]),
        "kdj_cross":    bool(row["kdj_golden_cross"]),
        "rsi_oversold": bool(row["rsi"] < RSI_OVERSOLD),
        "ranging":      bool(row["adx"] < ADX_RANGING),
        "volume_spike": bool(row["volume"] > VOLUME_SPIKE_MULT * row.get("volume_ma", 0)),
    }
    return SignalSnapshot(
        score=sum(details.values()),
        max_score=len(details),
        details=details,
    )
