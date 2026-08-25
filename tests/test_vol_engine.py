"""Tests for mm.vol_engine's deterministic classification (no AI, pure math).

fetch_vol_levels() hits the network (yfinance) and isn't unit-tested here —
it's exercised via scripts/fetch_vol_state.py --dry-run in practice. These
tests cover compute_vol_state(), which is pure and deterministic, using the
real percentile thresholds calibrated from 5-year yfinance history 2026-08-25
(see mm/vol_engine.py's _LEVEL_THRESHOLDS).
"""
from mm.vol_engine import compute_vol_state


def _levels(**overrides) -> dict:
    base = {"vix": None, "vix1d": None, "vix9d": None, "vix3m": None,
            "vix6m": None, "vvix": None, "vxn": None, "cor1m": None, "cor3m": None}
    base.update(overrides)
    return base


def test_vix_level_buckets():
    assert compute_vol_state(_levels(vix=10.0))["buckets"]["spy_level"] == "low"        # < p25=15.41
    assert compute_vol_state(_levels(vix=18.0))["buckets"]["spy_level"] == "normal"     # p25..p75
    assert compute_vol_state(_levels(vix=24.0))["buckets"]["spy_level"] == "elevated"   # p75..p90
    assert compute_vol_state(_levels(vix=30.0))["buckets"]["spy_level"] == "extreme"    # > p90=26.94


def test_vxn_drives_qqq_level_independently_of_vix():
    # QQQ's bucket must come from VXN, not VIX -- this is the whole point of
    # per-symbol vol assignment (SPY->VIX, QQQ->VXN).
    state = compute_vol_state(_levels(vix=10.0, vxn=35.0))  # calm SPY, hot QQQ
    assert state["buckets"]["spy_level"] == "low"
    assert state["buckets"]["qqq_level"] == "extreme"


def test_iwm_shares_vix_bucket_no_rvx_equivalent():
    """Documents the known gap: IWM has no free small-cap vol index, so its
    bucket is literally the same as SPY's, not an independent signal."""
    state = compute_vol_state(_levels(vix=24.0))
    assert state["buckets"]["iwm_level"] == state["buckets"]["spy_level"] == "elevated"


def test_missing_level_returns_none_bucket_not_a_crash():
    state = compute_vol_state(_levels())  # everything None (fetch failure)
    assert state["buckets"]["spy_level"] is None
    assert state["buckets"]["qqq_level"] is None
    assert state["buckets"]["vol_of_vol"] is None
    assert state["ratios"]["vix1d_over_vix"] is None


def test_term_structure_ratios_are_raw_not_bucketed():
    """No _LEVEL_THRESHOLDS entry exists for vix1d/vix9d/vix3m -- confirms
    the module deliberately does NOT invent thresholds it can't calibrate."""
    state = compute_vol_state(_levels(vix=17.0, vix1d=24.0, vix9d=19.0, vix3m=18.0))
    assert state["ratios"]["vix1d_over_vix"] == round(24.0 / 17.0, 3)
    assert state["ratios"]["vix_over_vix3m"] == round(17.0 / 18.0, 3)
    assert "short_term" not in state["buckets"]
    assert "curve" not in state["buckets"]


def test_ratio_handles_zero_denominator_without_crashing():
    state = compute_vol_state(_levels(vix=0.0, vix1d=5.0))
    assert state["ratios"]["vix1d_over_vix"] is None


def test_vol_of_vol_bucket_from_vvix():
    assert compute_vol_state(_levels(vvix=80.0))["buckets"]["vol_of_vol"] == "low"       # < p25=87.53
    assert compute_vol_state(_levels(vvix=95.0))["buckets"]["vol_of_vol"] == "normal"    # p25..p75
    assert compute_vol_state(_levels(vvix=170.0))["buckets"]["vol_of_vol"] == "extreme"  # > p90=118.59


def test_levels_passthrough_unchanged():
    raw = _levels(vix=17.4, vvix=95.0)
    state = compute_vol_state(raw)
    assert state["levels"] == raw
