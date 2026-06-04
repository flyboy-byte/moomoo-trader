"""
Safety-critical tests for mm/risk.py.

These cover position sizing, daily limits, kill switch, and live-trading blocks.
All of these paths run in the paper loop before every order — they must be correct.
"""
import os
import importlib
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_risk(monkeypatch, env: dict):
    """Reload mm.config and mm.risk with patched env vars."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import mm.config
    importlib.reload(mm.config)
    mm.config.cfg = mm.config.Config()
    import mm.risk
    importlib.reload(mm.risk)
    return mm.risk


# ---------------------------------------------------------------------------
# calc_qty
# ---------------------------------------------------------------------------

class TestCalcQty:
    def test_normal_case(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_POSITION_DOLLARS": "50"})
        assert risk.calc_qty(10.0) == 5

    def test_price_equal_to_cap(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_POSITION_DOLLARS": "50"})
        assert risk.calc_qty(50.0) == 1

    def test_price_exceeds_cap_returns_zero(self, monkeypatch):
        """One share of SPY (~$550) exceeds a $50 cap — must return 0, not 1."""
        risk = _reload_risk(monkeypatch, {"MAX_POSITION_DOLLARS": "50"})
        assert risk.calc_qty(550.0) == 0

    def test_price_just_above_cap_returns_zero(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_POSITION_DOLLARS": "50"})
        assert risk.calc_qty(50.01) == 0

    def test_zero_price_returns_zero(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_POSITION_DOLLARS": "50"})
        assert risk.calc_qty(0.0) == 0

    def test_negative_price_returns_zero(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_POSITION_DOLLARS": "50"})
        assert risk.calc_qty(-10.0) == 0

    def test_floors_not_rounds(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_POSITION_DOLLARS": "50"})
        assert risk.calc_qty(16.0) == 3  # 50/16 = 3.125 → floor 3

    def test_symbol_override_used_when_set(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {
            "MAX_POSITION_DOLLARS": "50",
            "SYMBOL_SIZE_OVERRIDES": "US.IWM:300",
        })
        assert risk.calc_qty(100.0, "US.IWM") == 3   # 300/100 = 3
        assert risk.calc_qty(100.0, "US.SPY") == 0   # 50/100 = 0 (falls back to default)
        assert risk.calc_qty(100.0) == 0              # no symbol → default cap

    def test_symbol_override_allows_trade_blocked_by_default(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {
            "MAX_POSITION_DOLLARS": "50",
            "SYMBOL_SIZE_OVERRIDES": "US.IWM:220",
        })
        assert risk.calc_qty(210.0, "US.IWM") == 1   # 220/210 = 1
        assert risk.calc_qty(210.0) == 0              # 50/210 = 0


# ---------------------------------------------------------------------------
# DailyTracker — trade count limit
# ---------------------------------------------------------------------------

class TestDailyTrackerTradeCap:
    def test_allows_trades_below_limit(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_TRADES_PER_DAY": "3", "MAX_DAILY_LOSS": "5"})
        t = risk.DailyTracker()
        assert t.can_open() is True

    def test_blocks_at_limit(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_TRADES_PER_DAY": "3", "MAX_DAILY_LOSS": "5"})
        t = risk.DailyTracker()
        t.record_trade(0.0)
        t.record_trade(0.0)
        t.record_trade(0.0)
        assert t.can_open() is False

    def test_allows_up_to_limit(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_TRADES_PER_DAY": "3", "MAX_DAILY_LOSS": "5"})
        t = risk.DailyTracker()
        t.record_trade(0.0)
        t.record_trade(0.0)
        assert t.can_open() is True


# ---------------------------------------------------------------------------
# DailyTracker — daily loss limit
# ---------------------------------------------------------------------------

class TestDailyTrackerLossLimit:
    def test_allows_trades_before_limit(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_TRADES_PER_DAY": "10", "MAX_DAILY_LOSS": "5"})
        t = risk.DailyTracker()
        t.record_trade(-2.0)
        assert t.can_open() is True

    def test_blocks_at_loss_limit(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_TRADES_PER_DAY": "10", "MAX_DAILY_LOSS": "5"})
        t = risk.DailyTracker()
        t.record_trade(-5.0)
        assert t.can_open() is False

    def test_blocks_beyond_loss_limit(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_TRADES_PER_DAY": "10", "MAX_DAILY_LOSS": "5"})
        t = risk.DailyTracker()
        t.record_trade(-6.0)
        assert t.can_open() is False

    def test_positive_pnl_does_not_block(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"MAX_TRADES_PER_DAY": "10", "MAX_DAILY_LOSS": "5"})
        t = risk.DailyTracker()
        t.record_trade(10.0)
        assert t.can_open() is True


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------

class TestKillSwitch:
    def test_inactive_when_file_absent(self, monkeypatch, tmp_path):
        risk = _reload_risk(monkeypatch, {})
        monkeypatch.setattr(risk, "_KILL_SWITCH", tmp_path / "STOP_TRADING.txt")
        assert risk.kill_switch_active() is False

    def test_active_when_file_present(self, monkeypatch, tmp_path):
        risk = _reload_risk(monkeypatch, {})
        kill_file = tmp_path / "STOP_TRADING.txt"
        kill_file.touch()
        monkeypatch.setattr(risk, "_KILL_SWITCH", kill_file)
        assert risk.kill_switch_active() is True

    def test_trading_allowed_blocked_by_kill_switch(self, monkeypatch, tmp_path):
        risk = _reload_risk(monkeypatch, {"LIVE_TRADING_ENABLED": "false"})
        kill_file = tmp_path / "STOP_TRADING.txt"
        kill_file.touch()
        monkeypatch.setattr(risk, "_KILL_SWITCH", kill_file)
        assert risk.trading_allowed() is False

    def test_trading_allowed_after_kill_switch_removed(self, monkeypatch, tmp_path):
        risk = _reload_risk(monkeypatch, {"LIVE_TRADING_ENABLED": "false"})
        kill_file = tmp_path / "STOP_TRADING.txt"
        monkeypatch.setattr(risk, "_KILL_SWITCH", kill_file)
        assert risk.trading_allowed() is True


# ---------------------------------------------------------------------------
# Live trading blocked by default
# ---------------------------------------------------------------------------

class TestLiveTradingBlocked:
    def test_blocked_by_default(self, monkeypatch):
        """LIVE_TRADING_ENABLED must default to false."""
        monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
        risk = _reload_risk(monkeypatch, {})
        assert risk.live_trading_blocked() is False  # flag=false means NOT live → not blocked
        assert risk.cfg.live_trading_enabled is False

    def test_blocked_when_enabled_true(self, monkeypatch):
        """If someone sets LIVE_TRADING_ENABLED=true, live_trading_blocked() must catch it."""
        risk = _reload_risk(monkeypatch, {"LIVE_TRADING_ENABLED": "true"})
        assert risk.live_trading_blocked() is True

    def test_trading_allowed_false_when_live_enabled(self, monkeypatch, tmp_path):
        risk = _reload_risk(monkeypatch, {"LIVE_TRADING_ENABLED": "true"})
        monkeypatch.setattr(risk, "_KILL_SWITCH", tmp_path / "STOP_TRADING.txt")
        assert risk.trading_allowed() is False

    def test_trading_allowed_true_when_simulate(self, monkeypatch, tmp_path):
        risk = _reload_risk(monkeypatch, {"LIVE_TRADING_ENABLED": "false"})
        monkeypatch.setattr(risk, "_KILL_SWITCH", tmp_path / "STOP_TRADING.txt")
        assert risk.trading_allowed() is True


class TestFractionalSizing:
    def test_fractional_qty_basic(self):
        from mm.risk import calc_qty_fractional
        qty = calc_qty_fractional(price=755.0, dollars=11.11)
        assert abs(qty - 0.014715) < 0.0001

    def test_fractional_qty_zero_price(self):
        from mm.risk import calc_qty_fractional
        assert calc_qty_fractional(price=0.0, dollars=100.0) == 0.0

    def test_fractional_qty_zero_dollars(self):
        from mm.risk import calc_qty_fractional
        assert calc_qty_fractional(price=755.0, dollars=0.0) == 0.0

    def test_fractional_qty_rounds_6dp(self):
        from mm.risk import calc_qty_fractional
        qty = calc_qty_fractional(price=3.0, dollars=10.0)
        assert qty == round(qty, 6)

    def test_per_slot_dollars_divides_evenly(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"TOTAL_CAPITAL": "900", "FRACTIONAL_SHARES": "true"})
        dollars = risk.per_slot_dollars(n_symbols=3, n_strategies=3)
        assert abs(dollars - 100.0) < 0.001

    def test_per_slot_dollars_zero_when_unset(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"TOTAL_CAPITAL": "0"})
        assert risk.per_slot_dollars(n_symbols=3, n_strategies=3) == 0.0

    def test_per_slot_dollars_single_slot(self, monkeypatch):
        risk = _reload_risk(monkeypatch, {"TOTAL_CAPITAL": "500"})
        dollars = risk.per_slot_dollars(n_symbols=1, n_strategies=1)
        assert abs(dollars - 500.0) < 0.001
