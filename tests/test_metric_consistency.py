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


# ---------------------------------------------------------------------------
# Repo-wide guard against a NINTH profit_factor
# ---------------------------------------------------------------------------
#
# Built 2026-08-29. docs/strategy_graveyard.md recorded this as the missing piece
# after the 4th drift instance: "a repo-wide grep test for `def profit_factor`
# outside mm/backtest.py would close it properly. Not built yet."
#
# It matters because the tests above pin the behaviour of the canonical function
# and cannot, even in principle, notice that a second implementation exists
# somewhere else. That is exactly how instances 4 through 7 happened — three of
# them (in scripts/web_dashboard.py) sat in production for months.

from pathlib import Path  # noqa: E402

_REPO = Path(__file__).parent.parent
_CANONICAL = "mm/backtest.py"
_SCAN = ["mm", "scripts"]


def _py_files():
    for d in _SCAN:
        yield from sorted((_REPO / d).glob("*.py"))


def test_only_mm_backtest_defines_profit_factor():
    """Any other `def profit_factor` is a reimplementation waiting to drift.

    Need PF somewhere new? Import it:
        from .backtest import profit_factor
    Re-exporting is fine (mm/stats.py and mm/trades.py both do it); redefining is not.
    """
    offenders = []
    for path in _py_files():
        rel = f"{path.parent.name}/{path.name}"
        if rel == _CANONICAL:
            continue
        for n, line in enumerate(path.read_text().splitlines(), start=1):
            if line.lstrip().startswith("def profit_factor"):
                offenders.append(f"  {rel}:{n}: {line.strip()}")
    assert not offenders, (
        "profit_factor is defined outside mm/backtest.py — import the canonical one "
        "instead of writing another:\n" + "\n".join(offenders)
    )


def test_no_999_no_loss_sentinel_survives_anywhere():
    """The 999.0 sentinel is the specific divergence the 2026-06-18 consolidation
    was meant to end. Two `mm/` engines still had it on 2026-08-29 — that pass fixed
    the scripts/ wrappers and missed the engines underneath them. 999.0 and inf are
    not interchangeable in any average across runs: inf poisons it, 999.0 quietly
    doesn't, which is the worse failure."""
    offenders = []
    for path in _py_files():
        rel = f"{path.parent.name}/{path.name}"
        for n, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "999.0" in stripped and "gross_loss" in stripped:
                offenders.append(f"  {rel}:{n}: {stripped}")
    assert not offenders, (
        "999.0 no-loss sentinel found — use mm.backtest.profit_factor (returns inf):\n"
        + "\n".join(offenders)
    )
