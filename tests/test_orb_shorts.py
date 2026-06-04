"""Tests for ORB short-side logic in PaperPosition and _eval_orb exit math.

These tests do not call _eval_orb() directly (it requires live OpenD). Instead
they verify the core invariants that shorts must satisfy:
- Short stop fires on close >= stop_price (not <=)
- Short target fires on close <= target_price (not >=)
- Short PnL = entry_price - exit_price (not exit - entry)
- Long behavior unchanged
- direction field survives position file round-trip
"""

import json
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest

from mm.paper import PaperPosition


# ---------------------------------------------------------------------------
# PaperPosition direction field
# ---------------------------------------------------------------------------

def test_default_direction_is_long():
    pos = PaperPosition(
        symbol="US.SPY", strategy="orb",
        entry_time=datetime(2026, 6, 4, 10, 0),
        entry_price=500.0, stop_price=495.0, qty=1,
    )
    assert pos.direction == "long"


def test_short_direction_stored():
    pos = PaperPosition(
        symbol="US.SPY", strategy="orb",
        entry_time=datetime(2026, 6, 4, 10, 0),
        entry_price=500.0, stop_price=505.0, qty=1,
        direction="short",
    )
    assert pos.direction == "short"


def test_position_round_trip_preserves_direction():
    """direction field survives JSON serialisation (used by _save_position/_load_position)."""
    pos = PaperPosition(
        symbol="US.SPY", strategy="orb",
        entry_time=datetime(2026, 6, 4, 10, 0),
        entry_price=500.0, stop_price=505.0, qty=1,
        direction="short",
    )
    d = asdict(pos)
    d["entry_time"] = str(pos.entry_time)
    payload = json.dumps(d)
    restored = json.loads(payload)
    assert restored["direction"] == "short"


def test_load_position_restores_direction():
    """_load_position must restore direction — otherwise a restarted runner flips short exit logic."""
    import tempfile
    from unittest.mock import patch
    from mm.paper import _load_position

    pos = PaperPosition(
        symbol="US.SPY", strategy="orb",
        entry_time=datetime(2026, 6, 4, 10, 0),
        entry_price=500.0, stop_price=505.0, qty=1,
        direction="short", target_price=490.0,
    )
    d = asdict(pos)
    d["entry_time"] = str(pos.entry_time)

    with tempfile.TemporaryDirectory() as tmpdir:
        pos_file = Path(tmpdir) / "paper_US_SPY_orb_position.json"
        pos_file.write_text(json.dumps(d))
        with patch("mm.paper._position_file", return_value=pos_file):
            loaded = _load_position("US.SPY", "orb")

    assert loaded is not None
    assert loaded.direction == "short"


# ---------------------------------------------------------------------------
# Exit condition logic (direction-aware) — mirrors _eval_orb exit block
# ---------------------------------------------------------------------------

def _check_exit(position: PaperPosition, close: float) -> tuple[str | None, float]:
    """Replicate the direction-aware exit logic from _eval_orb."""
    is_short = position.direction == "short"
    exit_reason: str | None = None

    if position.target_price > 0 and (
        close <= position.target_price if is_short else close >= position.target_price
    ):
        exit_reason = "TARGET"
    elif close >= position.stop_price if is_short else close <= position.stop_price:
        exit_reason = "STOP"

    pnl = 0.0
    if exit_reason:
        pnl = (position.entry_price - close) if is_short else (close - position.entry_price)

    return exit_reason, pnl


# Long exit tests

def test_long_target_fires_above():
    pos = PaperPosition("US.SPY", "orb", datetime.now(), 500.0, 495.0, 1,
                        target_price=510.0, direction="long")
    reason, pnl = _check_exit(pos, 510.0)
    assert reason == "TARGET"
    assert pnl == pytest.approx(10.0)


def test_long_stop_fires_below():
    pos = PaperPosition("US.SPY", "orb", datetime.now(), 500.0, 495.0, 1,
                        target_price=510.0, direction="long")
    reason, pnl = _check_exit(pos, 495.0)
    assert reason == "STOP"
    assert pnl == pytest.approx(-5.0)


def test_long_no_exit_between():
    pos = PaperPosition("US.SPY", "orb", datetime.now(), 500.0, 495.0, 1,
                        target_price=510.0, direction="long")
    reason, _ = _check_exit(pos, 502.0)
    assert reason is None


def test_long_stop_does_not_fire_above():
    pos = PaperPosition("US.SPY", "orb", datetime.now(), 500.0, 495.0, 1,
                        target_price=510.0, direction="long")
    reason, _ = _check_exit(pos, 506.0)
    assert reason is None


# Short exit tests

def test_short_target_fires_below():
    pos = PaperPosition("US.SPY", "orb", datetime.now(), 500.0, 505.0, 1,
                        target_price=490.0, direction="short")
    reason, pnl = _check_exit(pos, 490.0)
    assert reason == "TARGET"
    assert pnl == pytest.approx(10.0)


def test_short_stop_fires_above():
    pos = PaperPosition("US.SPY", "orb", datetime.now(), 500.0, 505.0, 1,
                        target_price=490.0, direction="short")
    reason, pnl = _check_exit(pos, 505.0)
    assert reason == "STOP"
    assert pnl == pytest.approx(-5.0)


def test_short_no_exit_between():
    pos = PaperPosition("US.SPY", "orb", datetime.now(), 500.0, 505.0, 1,
                        target_price=490.0, direction="short")
    reason, _ = _check_exit(pos, 497.0)
    assert reason is None


def test_short_stop_does_not_fire_below():
    pos = PaperPosition("US.SPY", "orb", datetime.now(), 500.0, 505.0, 1,
                        target_price=490.0, direction="short")
    reason, _ = _check_exit(pos, 494.0)
    assert reason is None


def test_short_target_does_not_fire_above():
    pos = PaperPosition("US.SPY", "orb", datetime.now(), 500.0, 505.0, 1,
                        target_price=490.0, direction="short")
    reason, _ = _check_exit(pos, 501.0)
    assert reason is None


# PnL sign correctness

def test_short_profit_positive_when_price_falls():
    pos = PaperPosition("US.SPY", "orb", datetime.now(), 500.0, 505.0, 1,
                        target_price=490.0, direction="short")
    reason, pnl = _check_exit(pos, 490.0)
    assert pnl > 0


def test_short_loss_negative_when_stopped():
    pos = PaperPosition("US.SPY", "orb", datetime.now(), 500.0, 505.0, 1,
                        target_price=490.0, direction="short")
    reason, pnl = _check_exit(pos, 505.0)
    assert pnl < 0


def test_long_profit_positive_when_price_rises():
    pos = PaperPosition("US.SPY", "orb", datetime.now(), 500.0, 495.0, 1,
                        target_price=510.0, direction="long")
    reason, pnl = _check_exit(pos, 510.0)
    assert pnl > 0
