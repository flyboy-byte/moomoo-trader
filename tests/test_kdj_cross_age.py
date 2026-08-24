"""Regression test: _kdj_cross_age must not report a cross from a prior day.

Found by external audit 2026-08-25: mm/evals.py::_kdj_cross_age scanned the
last 50 rows with no day-boundary check, so the first bars of a new trading
session could report yesterday's KDJ golden cross as age 1/2/3. This field
feeds the w=0-vs-w>0 subset comparison in evaluation_criteria.md's BB+KDJ
gate, so mislabeled age corrupts the evidence a future strategy decision
depends on — the same bug class mm/strategy.py's entry gate was fixed for
on 2026-06-17 (day-boundary KDJ window leak), missed here because this is
telemetry, not the entry gate.
"""
import pandas as pd

from mm.evals import _kdj_cross_age


def _df(rows: list[tuple[str, bool]]) -> pd.DataFrame:
    return pd.DataFrame({
        "time_key": [r[0] for r in rows],
        "kdj_golden_cross": [r[1] for r in rows],
    })


def test_cross_late_previous_day_does_not_leak_into_next_day():
    df = _df([
        ("2026-06-16 15:50:00", False),
        ("2026-06-16 15:55:00", True),   # cross on day 1, near the close
        ("2026-06-17 09:30:00", False),  # first bar of a new session
        ("2026-06-17 09:35:00", False),
    ])
    # Without the day-boundary fix this would report age=2 (yesterday's cross).
    assert _kdj_cross_age(df) is None


def test_cross_same_day_still_found():
    df = _df([
        ("2026-06-17 09:30:00", False),
        ("2026-06-17 09:35:00", True),
        ("2026-06-17 09:40:00", False),
        ("2026-06-17 09:45:00", False),
    ])
    assert _kdj_cross_age(df) == 2


def test_cross_on_current_bar_is_age_zero():
    df = _df([
        ("2026-06-17 09:30:00", False),
        ("2026-06-17 09:35:00", True),
    ])
    assert _kdj_cross_age(df) == 0

    df2 = _df([("2026-06-17 09:30:00", True)])
    assert _kdj_cross_age(df2) == 0
