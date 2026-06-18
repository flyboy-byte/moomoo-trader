"""Direct unit tests for mm/execution.py — previously only covered indirectly
via test_paper.py/test_replay.py despite being the highest real-bug-density
module in the project (partial fills, fill-confirmation, reconcile races).

Covers:
- _confirm_fill: partial fill then timeout; partial then complete on a later poll
- _reconcile_positions: offsetting-positions (other_filled) regression test for
  the "netting deletion" scenario in docs/MASTER_AUDIT_JUNE.md (verified already
  fixed in code — this is the missing regression test for that fix)
- _reconcile_positions: pending-order grace-period keep vs cancel-and-clear
"""
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from mm import config as _config
from mm import execution
from mm.events import PaperPosition


@pytest.fixture(autouse=True)
def _isolate_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
    yield


def _fake_elog():
    return MagicMock()


# ---------------------------------------------------------------------------
# _confirm_fill
# ---------------------------------------------------------------------------

class _FakeTctx:
    """order_list_query returns successive canned responses, one per call."""
    def __init__(self, responses: list[tuple[int, pd.DataFrame]]):
        self._responses = list(responses)
        self.calls = 0

    def order_list_query(self, order_id, trd_env, acc_id):
        self.calls += 1
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def _order_row(status: str, dealt_qty: float = 0.0, dealt_avg_price: float = 0.0) -> pd.DataFrame:
    return pd.DataFrame([{
        "order_status": status, "dealt_qty": dealt_qty, "dealt_avg_price": dealt_avg_price,
    }])


def test_confirm_fill_partial_then_timeout(monkeypatch):
    """Order sits FILLED_PART forever (never reaches a terminal status) — must
    return the partial fill once the timeout elapses, not block forever."""
    tctx = _FakeTctx([(0, _order_row("FILLED_PART", dealt_qty=3.0, dealt_avg_price=10.0))])
    clock_time = [0.0]
    monkeypatch.setattr(execution.clock, "monotonic", lambda: clock_time[0])

    def fake_sleep(s):
        clock_time[0] += s
    monkeypatch.setattr(execution.clock, "sleep", fake_sleep)

    status, dealt, price = execution._confirm_fill(tctx, acc_id=1, order_id="X", timeout_s=5)
    assert status == "FILLED_PART"
    assert dealt == 3.0
    assert price == 10.0


def test_confirm_fill_partial_then_complete_on_second_poll(monkeypatch):
    """First poll sees a partial fill (not terminal), second poll sees FILLED_ALL
    — must return the FILLED_ALL state, not the stale partial snapshot."""
    tctx = _FakeTctx([
        (0, _order_row("FILLED_PART", dealt_qty=3.0, dealt_avg_price=10.0)),
        (0, _order_row("FILLED_ALL", dealt_qty=5.0, dealt_avg_price=10.05)),
    ])
    clock_time = [0.0]
    monkeypatch.setattr(execution.clock, "monotonic", lambda: clock_time[0])
    monkeypatch.setattr(execution.clock, "sleep", lambda s: clock_time.__setitem__(0, clock_time[0] + s))

    status, dealt, price = execution._confirm_fill(tctx, acc_id=1, order_id="X", timeout_s=30)
    assert status == "FILLED_ALL"
    assert dealt == 5.0
    assert price == 10.05


def test_confirm_fill_query_exception_does_not_crash(monkeypatch):
    """A flaky order_list_query call must be tolerated, not raise."""
    class _ExplodingTctx:
        def order_list_query(self, order_id, trd_env, acc_id):
            raise RuntimeError("network blip")

    clock_time = [0.0]
    monkeypatch.setattr(execution.clock, "monotonic", lambda: clock_time[0])
    monkeypatch.setattr(execution.clock, "sleep", lambda s: clock_time.__setitem__(0, clock_time[0] + s))

    status, dealt, price = execution._confirm_fill(_ExplodingTctx(), acc_id=1, order_id="X", timeout_s=3)
    assert status is None
    assert dealt == 0.0
    assert price is None


# ---------------------------------------------------------------------------
# _reconcile_positions
# ---------------------------------------------------------------------------

class _FakeReconcileTctx:
    def __init__(self, broker_df: pd.DataFrame, order_statuses: dict[str, str]):
        self._broker_df = broker_df
        self._order_statuses = order_statuses

    def position_list_query(self, trd_env, acc_id):
        return 0, self._broker_df

    def order_list_query(self, order_id, trd_env, acc_id):
        status = self._order_statuses.get(str(order_id))
        if status is None:
            return 0, pd.DataFrame()
        return 0, pd.DataFrame([{"order_status": status}])

    def modify_order(self, *a, **k):
        return 0, None


def _pos(symbol, strategy, order_id, entry_time, direction="long") -> PaperPosition:
    return PaperPosition(symbol=symbol, strategy=strategy, entry_time=entry_time,
                         entry_price=100.0, stop_price=95.0, qty=1.0,
                         order_id=order_id, direction=direction)


def test_reconcile_keeps_offsetting_positions_netting_to_zero(monkeypatch):
    """Regression test for docs/MASTER_AUDIT_JUNE.md's 'Netting Deletion' scenario:
    bb_kdj long SPY + ORB short SPY net to 0 shares at the broker. The long leg's
    OWN order status is unknown (simulating a lagging/unreliable status lookup)
    and its entry is past the reconcile grace period — without the other_filled
    check it would be misclassified as a genuine ghost and cleared. Because the
    short leg on the same symbol has a FILLED order, it must be recognized as a
    valid offsetting position and kept instead."""
    now = datetime(2026, 6, 18, 11, 0, 0)
    monkeypatch.setattr(execution.clock, "now_et", lambda: now)
    monkeypatch.setattr(execution, "notify", lambda *a, **k: None)

    broker_df = pd.DataFrame(columns=["code", "qty"])  # broker shows 0 net SPY
    # long_order's status is deliberately NOT in the statuses dict → _order_status
    # returns None (unknown), forcing the code to rely on other_filled, not its
    # own per-order FILLED_STATUSES shortcut.
    statuses = {"short_order": "FILLED_ALL"}
    tctx = _FakeReconcileTctx(broker_df, statuses)

    old_entry = datetime(2026, 6, 18, 10, 0, 0)  # 60 min old, past 30-min grace
    long_pos = _pos("US.SPY", "bb_kdj", "long_order", old_entry, direction="long")
    short_pos = _pos("US.SPY", "orb", "short_order", now, direction="short")
    positions = {("US.SPY", "bb_kdj"): long_pos, ("US.SPY", "orb"): short_pos}
    elogs = {"US.SPY": MagicMock()}

    execution._reconcile_positions(tctx, acc_id=1, positions=positions, elogs=elogs)

    assert positions[("US.SPY", "bb_kdj")] is long_pos
    assert positions[("US.SPY", "orb")] is short_pos
    elogs["US.SPY"].error.assert_not_called()


def test_reconcile_keeps_pending_order_within_grace_period(monkeypatch):
    now = datetime(2026, 6, 18, 10, 5, 0)
    monkeypatch.setattr(execution.clock, "now_et", lambda: now)

    broker_df = pd.DataFrame(columns=["code", "qty"])
    tctx = _FakeReconcileTctx(broker_df, {"pending_order": "SUBMITTED"})

    entry_time = datetime(2026, 6, 18, 9, 55, 0)  # 10 min old, within 30-min grace
    pos = _pos("US.QQQ", "vwap_pb", "pending_order", entry_time)
    positions = {("US.QQQ", "vwap_pb"): pos}
    elogs = {"US.QQQ": MagicMock()}

    execution._reconcile_positions(tctx, acc_id=1, positions=positions, elogs=elogs)

    assert positions[("US.QQQ", "vwap_pb")] is pos  # kept, not cleared
    elogs["US.QQQ"].error.assert_not_called()


def test_reconcile_cancels_and_clears_pending_order_past_grace(monkeypatch, tmp_path):
    now = datetime(2026, 6, 18, 11, 0, 0)
    monkeypatch.setattr(execution.clock, "now_et", lambda: now)
    monkeypatch.setattr(execution, "notify", lambda *a, **k: None)

    broker_df = pd.DataFrame(columns=["code", "qty"])
    tctx = _FakeReconcileTctx(broker_df, {"pending_order": "SUBMITTED"})

    entry_time = datetime(2026, 6, 18, 10, 0, 0)  # 60 min old, past 30-min grace
    pos = _pos("US.IWM", "bb_kdj", "pending_order", entry_time)
    positions = {("US.IWM", "bb_kdj"): pos}
    elogs = {"US.IWM": MagicMock()}

    execution._reconcile_positions(tctx, acc_id=1, positions=positions, elogs=elogs)

    assert positions[("US.IWM", "bb_kdj")] is None  # cleared — genuinely stale entry
    elogs["US.IWM"].error.assert_called_once()


def test_reconcile_keeps_position_broker_confirms(monkeypatch):
    """Sanity check the non-mismatch path: broker shows the symbol, nothing happens."""
    now = datetime(2026, 6, 18, 10, 0, 0)
    monkeypatch.setattr(execution.clock, "now_et", lambda: now)

    broker_df = pd.DataFrame([{"code": "US.SPY", "qty": 10.0}])
    tctx = _FakeReconcileTctx(broker_df, {})

    pos = _pos("US.SPY", "bb_kdj", "order1", now)
    positions = {("US.SPY", "bb_kdj"): pos}
    elogs = {"US.SPY": MagicMock()}

    execution._reconcile_positions(tctx, acc_id=1, positions=positions, elogs=elogs)

    assert positions[("US.SPY", "bb_kdj")] is pos
    elogs["US.SPY"].error.assert_not_called()
