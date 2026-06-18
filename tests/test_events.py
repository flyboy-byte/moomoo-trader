"""Direct unit tests for mm/events.py — position persistence and the event
log's filename/ts correctness, previously untested directly. Regression
coverage for the 2026-06-18 fix (clock.now()/server-local time → clock.now_et()
/clock.today() for the JSONL filename and ts field).
"""
import json
from datetime import date, datetime

from mm import clock
from mm import config as _config
from mm.events import (
    PaperEventLog,
    PaperPosition,
    _clear_position,
    _load_orb_traded,
    _load_position,
    _orb_traded_file,
    _position_file,
    _save_orb_traded,
    _save_position,
)


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)


def test_position_round_trip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    pos = PaperPosition(symbol="US.SPY", strategy="bb_kdj",
                        entry_time=datetime(2026, 6, 18, 10, 0, 0),
                        entry_price=500.0, stop_price=495.0, qty=2.0,
                        order_id="abc123", direction="long")
    _save_position(pos)
    loaded = _load_position("US.SPY", "bb_kdj")
    assert loaded is not None
    assert loaded.symbol == pos.symbol
    assert loaded.entry_price == pos.entry_price
    assert loaded.stop_price == pos.stop_price
    assert loaded.qty == pos.qty
    assert loaded.order_id == pos.order_id
    assert loaded.direction == pos.direction
    assert loaded.entry_time == pos.entry_time


def test_position_clear_removes_file(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    pos = PaperPosition(symbol="US.QQQ", strategy="orb",
                        entry_time=datetime(2026, 6, 18, 10, 0, 0),
                        entry_price=400.0, stop_price=395.0, qty=1.0)
    _save_position(pos)
    assert _position_file("US.QQQ", "orb").exists()
    _clear_position("US.QQQ", "orb")
    assert not _position_file("US.QQQ", "orb").exists()
    assert _load_position("US.QQQ", "orb") is None


def test_load_position_missing_file_returns_none(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert _load_position("US.IWM", "vwap_pb") is None


def test_load_position_corrupt_file_returns_none_not_raises(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    path = _position_file("US.IWM", "bb_kdj")
    path.write_text("not valid json{{{")
    assert _load_position("US.IWM", "bb_kdj") is None


def test_orb_traded_round_trip_uses_real_date(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _save_orb_traded("US.SPY", date(2026, 6, 18))
    result = _load_orb_traded(["US.SPY"])
    assert result == {"US.SPY": date(2026, 6, 18)}


def test_orb_traded_missing_symbol_omitted(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    result = _load_orb_traded(["US.SPY", "US.QQQ"])
    assert result == {}


def test_orb_traded_corrupt_file_skipped_not_raises(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _orb_traded_file("US.SPY").write_text("garbage")
    result = _load_orb_traded(["US.SPY"])
    assert result == {}


# ---------------------------------------------------------------------------
# PaperEventLog filename/ts correctness (regression coverage for 2026-06-18 fix)
# ---------------------------------------------------------------------------

def test_event_log_filename_uses_et_trading_day(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    fake_today = date(2026, 6, 19)
    monkeypatch.setattr(clock, "today", lambda: fake_today)
    monkeypatch.setattr(clock, "now_et", lambda: datetime(2026, 6, 19, 10, 0, 0))

    elog = PaperEventLog("US.SPY")
    elog.signal_skip("test_reason", score=1, bonus=0, min_score=2, strategy="bb_kdj")

    expected_path = tmp_path / "paper_US_SPY_2026-06-19.jsonl"
    assert expected_path.exists()


def test_event_log_ts_field_is_et_not_server_local(tmp_path, monkeypatch):
    """The bug: ts used to come from clock.now() (server-local/UTC), not ET.
    A VPS-recorded 13:30 ET entry was logged as ts=...T17:30:02 with no
    timezone label, looking like an after-hours trade."""
    _isolate(tmp_path, monkeypatch)
    fake_et = datetime(2026, 6, 18, 13, 30, 2)
    monkeypatch.setattr(clock, "today", lambda: fake_et.date())
    monkeypatch.setattr(clock, "now_et", lambda: fake_et)
    # Simulate a server clock far from ET (the actual bug shape on the VPS, UTC).
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 6, 18, 17, 30, 2))

    elog = PaperEventLog("US.QQQ")
    elog.signal_skip("test_reason", score=1, bonus=0, min_score=2, strategy="orb")

    path = tmp_path / "paper_US_QQQ_2026-06-18.jsonl"
    record = json.loads(path.read_text().splitlines()[0])
    assert record["ts"] == fake_et.isoformat(timespec="seconds")
    assert record["ts"] != datetime(2026, 6, 18, 17, 30, 2).isoformat(timespec="seconds")
