"""The real research archives contain only real bars.

2026-08-24 found test fixtures (prices 100 / 999 / 101, blank `code`) inside
logs/US_IWM_K_5M_combined.csv. The graveyard recorded them as removed; they were
still there on 2026-09-17. This test makes that state checkable instead of claimed.
Skipped where the archives are absent (fresh clone).
"""
from pathlib import Path

import pandas as pd
import pytest

ARCHIVES = sorted(Path("logs").glob("US_*_K_5M*_combined.csv"))


@pytest.mark.skipif(not ARCHIVES, reason="no candle archives on disk")
@pytest.mark.parametrize("path", ARCHIVES, ids=lambda p: p.name)
def test_archive_has_only_real_bars(path):
    df = pd.read_csv(path, usecols=["code", "time_key", "close"])
    assert df["code"].notna().all(), f"{path.name}: rows without a symbol code (test fixtures?)"
    assert df["code"].nunique() == 1, f"{path.name}: more than one symbol"
    df["day"] = df["time_key"].str[:10]
    jumps = df.groupby("day")["close"].apply(lambda s: (s.pct_change().abs() > 0.15).any())
    assert not jumps.any(), f"{path.name}: >15% bar-to-bar jump on {list(jumps[jumps].index)}"
