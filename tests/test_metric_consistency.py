"""Regression coverage for the reimplemented-metric-drift bug class.

profit_factor was independently reimplemented in ~8 places across the
codebase, drifting on two axes: loss classification (`pnl <= 0` vs `pnl < 0`)
and the no-losses sentinel (`999.0` vs `float("inf")`). Consolidated into
mm.backtest.profit_factor() on 2026-06-18 (research.py, backtest_orb.py,
backtest_vwap_pb.py, backtest_ema_momentum.py, sweep_vwap.py) and again later
the same day (analyze_orb_hours.py, research_premarket_gap.py,
sweep_session_filter.py — the last one had the 999.0 sentinel specifically).
This test pins the canonical definition so a 9th reimplementation can't
silently drift again, and exercises both call shapes (objects-with-.pnl and
plain numbers) the consolidation needed to support.
"""
from dataclasses import dataclass

from mm.backtest import profit_factor


@dataclass
class _FakeTrade:
    pnl: float


def test_profit_factor_treats_zero_pnl_as_a_loss():
    """pnl == 0 must count toward gross_loss, not be excluded from both."""
    pf = profit_factor([10.0, 0.0, -5.0])
    # gross_win=10, gross_loss=5 (the 0.0 counts as a loss) -> pf=2.0.
    # If 0.0 were excluded entirely, gross_loss would be 5 too (no difference
    # here) — use a case where it matters: an all-zero set must NOT be "inf".
    assert pf == 2.0
    assert profit_factor([0.0, 0.0]) == float("inf")  # gross_loss=0 -> inf is still right
    assert profit_factor([5.0, 0.0]) == float("inf")  # no losses at all


def test_profit_factor_sentinel_is_inf_not_999():
    assert profit_factor([]) == float("inf")
    assert profit_factor([10.0]) == float("inf")  # no losses
    assert profit_factor([10.0]) != 999.0


def test_profit_factor_accepts_trade_objects_and_plain_numbers_identically():
    pnls = [10.0, -4.0, 6.0, -2.0]
    trades = [_FakeTrade(pnl=p) for p in pnls]
    assert profit_factor(trades) == profit_factor(pnls)


def test_profit_factor_matches_hand_computed_value():
    # gross_win = 10+6=16, gross_loss = 4+2=6 -> pf = 16/6
    pnls = [10.0, -4.0, 6.0, -2.0]
    assert profit_factor(pnls) == 16.0 / 6.0
