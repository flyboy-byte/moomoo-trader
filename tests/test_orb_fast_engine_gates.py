"""The fast ORB engine can mirror the live ORB_LATEST_ENTRY and short-allowlist gates.

PLAN.md Step 5 compares mm/orb_strategy.py against the real runner, and the live
runner applies both gates (mm/evals.py::_eval_orb). Defaults must keep the old
research behaviour; a blocked bar must not use up the day's single entry.
"""
from datetime import time as dtime

import pandas as pd

from mm.orb_strategy import run_orb_signals


def _day(events: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """One RTH session of 5-min bars at 100 with a 99.8-100.2 opening range.

    Breakouts go after ~11:10, once the 20-bar volume average exists.

    events maps "HH:MM" -> (close, volume) for bars that should break out.
    """
    rows = []
    for ts in pd.date_range("2026-03-02 09:30", "2026-03-02 15:55", freq="5min"):
        hhmm = ts.strftime("%H:%M")
        if ts.time() < dtime(9, 45):
            o, h, l, c, v = 100.0, 100.2, 99.8, 100.0, 1000.0
        elif hhmm in events:
            c, v = events[hhmm]
            o, h, l = 100.0, max(c, 100.0) + 0.01, min(c, 100.0) - 0.01
        else:
            o, h, l, c, v = 100.0, 100.05, 99.95, 100.0, 1000.0
        rows.append({"time_key": ts.strftime("%Y-%m-%d %H:%M:%S"),
                     "open": o, "high": h, "low": l, "close": c, "volume": v})
    return pd.DataFrame(rows)


def _run(df, **kw):
    trades, _ = run_orb_signals(df, vol_mult=1.5, orb_minutes=15, target_mult=1.5, **kw)
    return trades


def test_late_breakout_taken_by_default():
    trades = _run(_day({"12:35": (100.5, 10_000.0)}))
    assert len(trades) == 1 and trades[0].direction == "long"


def test_latest_entry_blocks_late_breakout():
    trades = _run(_day({"12:35": (100.5, 10_000.0)}), latest_entry=dtime(12, 30))
    assert trades == []


def test_latest_entry_allows_earlier_breakout():
    trades = _run(_day({"11:30": (100.5, 10_000.0)}), latest_entry=dtime(12, 30))
    assert len(trades) == 1


def test_short_taken_by_default():
    trades = _run(_day({"11:30": (99.5, 10_000.0)}))
    assert len(trades) == 1 and trades[0].direction == "short"


def test_disallowed_short_does_not_consume_the_day():
    df = _day({"11:30": (99.5, 10_000.0), "12:00": (100.5, 10_000.0)})
    trades = _run(df, shorts_allowed=False)
    assert [t.direction for t in trades] == ["long"]
