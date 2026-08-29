"""Tests for mm.stats — bootstrap uncertainty (docs/research-reset.md Goal A4).

The behaviour that matters here is that small samples produce HONESTLY WIDE intervals.
A CI implementation that quietly looks confident at n=10 would defeat the entire purpose,
so several tests assert width/coverage rather than point values.
"""
import math

import pytest

from mm import stats


def test_stats_reexports_the_canonical_profit_factor_not_a_copy():
    """Guard against reintroducing the ~8-way PF divergence that mm/backtest.py's
    docstring and tests/test_metric_consistency.py exist to prevent. A second
    implementation here with a `< 0` loss convention was written and removed on
    2026-08-29 — this pins the re-export so it cannot come back silently."""
    # Provenance, not identity — mm.backtest gets reloaded by other tests, which
    # would break an `is` check without anything being wrong. See the same note in
    # tests/test_trades_module.py.
    assert stats.profit_factor.__module__ == "mm.backtest"
    assert stats.profit_factor.__qualname__ == "profit_factor"
    assert stats.profit_factor([10.0, 0.0, -5.0]) == pytest.approx(2.0)   # 0 counts as loss
    assert stats.profit_factor([]) == float("inf")                        # not nan


def test_bootstrap_ci_uses_the_same_loss_convention_as_the_point_estimate():
    """A CI computed with a different zero-PnL convention than the PF it brackets
    would not reliably contain it."""
    pnls = [3.0, 0.0, -1.0, 2.0, 0.0, -2.0, 1.5, -0.5]
    pf = stats.profit_factor(pnls)
    lo, hi = stats.bootstrap_pf_ci(pnls, n_boot=4000)
    assert lo <= pf <= hi


def test_ci_is_deterministic_across_calls():
    """Two runs of the same report must not disagree — fixed seed."""
    pnls = [1.0, -0.5, 2.0, -1.5, 0.3, -0.2, 1.1, -0.9]
    assert stats.bootstrap_pf_ci(pnls) == stats.bootstrap_pf_ci(pnls)


def test_tiny_sample_returns_nan_rather_than_a_fake_interval():
    assert all(math.isnan(x) for x in stats.bootstrap_pf_ci([1.0]))
    assert all(math.isnan(x) for x in stats.bootstrap_mean_ci([1.0]))
    assert math.isnan(stats.prob_positive([1.0]))


def test_small_noisy_sample_ci_straddles_pf_of_one():
    """The audit's core claim: a marginally-positive PF on a small sample is
    consistent with zero edge. The interval must SHOW that."""
    pnls = [1.0, -0.9, 1.1, -1.0, 0.8, -0.7, 1.2, -1.1, 0.5, -0.4]
    lo, hi = stats.bootstrap_pf_ci(pnls, n_boot=2000)
    assert lo < 1.0 < hi


def test_large_clear_edge_ci_excludes_one():
    """Conversely, a real edge on a real sample must produce an interval that
    excludes 1.0 — otherwise the method can never detect anything."""
    pnls = [2.0, -0.5] * 200
    lo, _ = stats.bootstrap_pf_ci(pnls, n_boot=2000)
    assert lo > 1.0


def test_more_data_narrows_the_interval():
    pattern = [1.0, -0.9, 1.1, -1.0, 0.8, -0.7]
    narrow = stats.bootstrap_mean_ci(pattern * 50, n_boot=2000)
    wide = stats.bootstrap_mean_ci(pattern, n_boot=2000)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_prob_positive_is_near_half_for_coinflip_pnl():
    pnls = [1.0, -1.0] * 50
    assert 0.3 < stats.prob_positive(pnls, n_boot=2000) < 0.7


def test_prob_positive_is_high_for_a_real_edge():
    assert stats.prob_positive([2.0, -0.5] * 100, n_boot=2000) > 0.95


def test_summarize_returns_the_full_picture():
    s = stats.summarize([1.0, -0.5, 2.0, -1.5, 0.3], n_boot=1000)
    assert s["n"] == 5
    assert s["total"] == pytest.approx(1.3)
    assert s["mean"] == pytest.approx(0.26)
    assert s["pf"] == pytest.approx(3.3 / 2.0)
    assert s["pf_ci"][0] <= s["pf"] <= s["pf_ci"][1]
    assert 0.0 <= s["prob_positive"] <= 1.0


def test_pf_ci_upper_bound_is_inf_not_nan_when_resamples_have_no_losses():
    """Regression: linear interpolation between two inf order statistics yields nan,
    which silently destroyed the whole interval. A mostly-winning small sample must
    report an unbounded upper end, not a missing one."""
    lo, hi = stats.bootstrap_pf_ci([5.0, 4.0, 3.0, -0.1], n_boot=2000)
    assert not math.isnan(hi)
    assert hi == float("inf")
    assert math.isfinite(lo)
