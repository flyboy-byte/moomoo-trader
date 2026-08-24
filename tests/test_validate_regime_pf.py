"""Regression test for the regime-validator PF aggregation bug.

Found by external audit 2026-08-25, verified against scripts/validate_regime.py:
the old code computed PF independently per day, dropped infinite-PF (zero-loss)
days, then averaged the remaining daily PF ratios. Averaging ratios is not
profit factor. Two days — one gross_win=10/gross_loss=1 (PF=10), one
gross_win=1/gross_loss=10 (PF=0.1) — averaged to 5.05, while the correct pooled
PF across both days is (10+1)/(1+10)=1.00 (breakeven). The fix pools every
trade belonging to a label and calls profit_factor() once on the pooled list.

This test doesn't invoke validate_regime.py's main() (argv-parsing, live API
calls, candle files) — it pins down the arithmetic the fix depends on: that
mm.backtest.profit_factor(), the canonical PF calc used everywhere else in the
project, gives the pooled answer and not the averaged-ratio answer.
"""
from types import SimpleNamespace

from mm.backtest import profit_factor


def _trades(*pnls):
    return [SimpleNamespace(pnl=p) for p in pnls]


def test_pooled_pf_not_average_of_daily_pf():
    day_a = _trades(10.0, -1.0)   # gross_win=10, gross_loss=1 -> PF=10
    day_b = _trades(1.0, -10.0)   # gross_win=1, gross_loss=10 -> PF=0.1

    pf_a = profit_factor(day_a)
    pf_b = profit_factor(day_b)
    assert pf_a == 10.0
    assert round(pf_b, 3) == 0.1

    naive_average = (pf_a + pf_b) / 2
    assert round(naive_average, 3) == 5.05  # the bug's answer — wrong

    pooled_pf = profit_factor(day_a + day_b)
    assert pooled_pf == 1.0  # the correct answer — breakeven, not "great"


def test_pooled_pf_ignores_zero_loss_day_correctly():
    """A zero-loss day has infinite PF alone but must not be silently dropped
    from a pooled calculation — its gross wins still belong in the numerator."""
    zero_loss_day = _trades(5.0, 3.0)      # PF = inf alone
    normal_day = _trades(2.0, -4.0)        # PF = 0.5 alone

    pooled_pf = profit_factor(zero_loss_day + normal_day)
    # gross_win = 5+3+2 = 10, gross_loss = 4 -> PF = 2.5
    assert pooled_pf == 2.5
