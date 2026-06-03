"""
VWAP momentum signal engine.

Strategy: trade WITH VWAP direction, not against it.
  Entry (long): close crosses above VWAP from below + volume confirmation
  Exit:         close crosses back below VWAP, or time stop at 15:45

Research basis: Concretum SSRN study on QQQ 2018-2023 showed 671% return
(Sharpe 2.1) vs 126% buy-and-hold using VWAP crossover direction.

Previous mean-reversion approach (close < VWAP - band) had 42% win, PF~1.0
across all 48 parameter combos — no edge on SPY/QQQ/IWM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

VOLUME_CONFIRM_MULT: float = 1.2


VWAP_SIGNALS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "vwap_cross_up": lambda df: (df["close"] > df["vwap"]) & (df["close"].shift(1) <= df["vwap"].shift(1)),
    "vol_confirm":   lambda df: df["volume"] > VOLUME_CONFIRM_MULT * df["volume_ma"],
}


@dataclass(frozen=True)
class VWAPSnapshot:
    details: dict[str, bool]
    vwap: float
    above_vwap: bool

    @property
    def entry_ready(self) -> bool:
        return all(self.details.values())

    def __str__(self) -> str:
        flags = "  ".join(f"{'✓' if v else '✗'} {k}" for k, v in self.details.items())
        return f"vwap={self.vwap:.3f}  above={self.above_vwap}  {flags}"


def score_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Add sig_vwap_* columns and vwap_entry (bool) to an indicators-enriched DataFrame."""
    df = df.copy()
    for name, fn in VWAP_SIGNALS.items():
        df[f"sig_{name}"] = fn(df).fillna(False)
    df["vwap_entry"] = df[[f"sig_{n}" for n in VWAP_SIGNALS]].all(axis=1)
    return df


def snapshot_vwap(row: pd.Series) -> VWAPSnapshot:
    """Evaluate VWAP signals for a single bar — used by the live paper runner."""
    vwap_val = float(row.get("vwap", 0))
    above = float(row["close"]) > vwap_val
    details = {
        "vwap_cross_up": bool(row.get("sig_vwap_cross_up", False)),
        "vol_confirm":   bool(row["volume"] > VOLUME_CONFIRM_MULT * row.get("volume_ma", 0)),
    }
    return VWAPSnapshot(details=details, vwap=vwap_val, above_vwap=above)
