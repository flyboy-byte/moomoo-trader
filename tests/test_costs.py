"""Tests for mm.costs — the transaction cost model (docs/research-reset.md Goal A1).

The point of these tests is not that the arithmetic works; it is that the model stays
PESSIMISTIC and stays APPLIED. The failure mode this whole module exists to prevent is a
cost assumption quietly drifting toward zero until results look good, so the invariants
below are deliberately about direction and defaults, not just values.
"""
import pytest

from mm import costs


def test_known_etfs_use_their_own_bps_not_the_default():
    assert costs.round_trip_bps("US.SPY") == 1.5
    assert costs.round_trip_bps("US.IWM") == 2.5
    assert costs.round_trip_bps("US.SPY") < costs.DEFAULT_ROUND_TRIP_BPS


def test_unknown_symbol_is_charged_the_pessimistic_default():
    """Load-bearing for Goal B: an unlisted single name must NOT silently inherit
    SPY-like costs, or the wide scan will look profitable for the wrong reason."""
    assert costs.round_trip_bps("US.SOMETHING_NEW") == costs.DEFAULT_ROUND_TRIP_BPS
    assert costs.DEFAULT_ROUND_TRIP_BPS > max(costs.SYMBOL_ROUND_TRIP_BPS.values())


def test_cost_is_charged_on_notional():
    # 1.5 bps on 10 shares x $700 = $7000 notional = $1.05
    assert costs.trade_cost("US.SPY", 700.0, 10) == pytest.approx(1.05)


def test_cost_reduces_pnl_for_winners_and_losers_alike():
    """Costs are not directional. A loser must get MORE negative, never less."""
    win = costs.net_pnl(5.0, "US.SPY", 700.0, 10)
    loss = costs.net_pnl(-5.0, "US.SPY", 700.0, 10)
    assert win == pytest.approx(5.0 - 1.05)
    assert loss == pytest.approx(-5.0 - 1.05)
    assert loss < -5.0


def test_bps_override_does_not_mutate_module_state():
    """The reporting layer sweeps COST_SCENARIOS; that must not leak between calls."""
    before = costs.round_trip_bps("US.SPY")
    costs.net_pnl(1.0, "US.SPY", 700.0, 10, bps_override=99.0)
    assert costs.round_trip_bps("US.SPY") == before


def test_zero_override_reproduces_frictionless_numbers():
    """Continuity with every historical report in the repo."""
    assert costs.net_pnl(3.21, "US.SPY", 700.0, 10, bps_override=0.0) == pytest.approx(3.21)


def test_zero_scenario_is_available_for_continuity():
    assert 0.0 in costs.COST_SCENARIOS
    assert costs.COST_SCENARIOS == tuple(sorted(costs.COST_SCENARIOS))


def test_degenerate_notional_costs_nothing_rather_than_crashing():
    """Old/partial log records can carry qty=0 or entry=0; reporting must not die."""
    assert costs.trade_cost("US.SPY", 0.0, 10) == 0.0
    assert costs.trade_cost("US.SPY", 700.0, 0) == 0.0
    assert costs.net_bps(1.0, "US.SPY", 0.0, 10) is None


def test_net_bps_is_gross_bps_minus_the_hurdle():
    """A trade returning exactly its own cost must net to 0.0 bps — this is the
    comparison the audit was missing."""
    entry, qty = 700.0, 10
    gross = costs.trade_cost("US.SPY", entry, qty)   # earns exactly its cost
    assert costs.net_bps(gross, "US.SPY", entry, qty) == pytest.approx(0.0)


def test_the_live_portfolio_average_does_not_clear_spy_costs():
    """Regression guard on the audit's headline finding: +1.31 bps gross on a
    SPY-like symbol is NEGATIVE after this model's costs. If a future edit to the
    defaults makes this pass as profitable, that edit needs justifying."""
    entry, qty = 766.0, 1
    gross_pnl = 1.31 / 10_000 * entry * qty
    assert costs.net_bps(gross_pnl, "US.SPY", entry, qty) < 0
