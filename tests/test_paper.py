"""
Tests for mm/paper.py — order placement pricing, qty fallback, entry dedup.

These cover the three silent-failure bugs found in live operation:
  1. Moomoo rejects prices with >2 decimal places (_place_* rounding)
  2. Sub-1 fractional qty causes "Invalid quantity" rejection (_qty fallback)
  3. Failed entry retried every 60s until new candle (_entry_attempted dedup)
"""
import importlib
from unittest.mock import MagicMock

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_paper(monkeypatch, env: dict):
    """Reload mm.config, mm.risk, mm.paper with patched env vars."""
    base = {
        "TRD_ENV": "SIMULATE",
        "LIVE_TRADING_ENABLED": "false",
        "MAX_POSITION_DOLLARS": "900",
        "FRACTIONAL_SHARES": "false",
    }
    base.update(env)
    for k, v in base.items():
        monkeypatch.setenv(k, str(v))
    import mm.config
    importlib.reload(mm.config)
    mm.config.cfg = mm.config.Config()
    import mm.risk
    importlib.reload(mm.risk)
    import mm.paper
    importlib.reload(mm.paper)
    return mm.paper


RET_OK = 0


def _mock_ctx_ok(order_id="12345"):
    ctx = MagicMock()
    ctx.place_order.return_value = (RET_OK, pd.DataFrame({"order_id": [order_id]}))
    return ctx


def _mock_ctx_fail():
    ctx = MagicMock()
    ctx.place_order.return_value = (1, "Invalid quantity.")
    return ctx


def _placed_price(ctx):
    return ctx.place_order.call_args[1]["price"]


# ---------------------------------------------------------------------------
# _place_*() — price rounding to 2 decimal places
# ---------------------------------------------------------------------------

class TestPlaceOrderPricing:
    """Moomoo rejects prices with >2 decimal places (caught June 4 QQQ, June 8 SPY)."""

    def test_buy_rounds_3dp_price(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        ctx = _mock_ctx_ok()
        p._place_buy(ctx, acc_id=1, symbol="US.SPY", price=740.835, qty=1)
        assert _placed_price(ctx) == round(740.835, 2)

    def test_sell_rounds_3dp_price(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        ctx = _mock_ctx_ok()
        p._place_sell(ctx, acc_id=1, symbol="US.SPY", price=740.835, qty=1)
        assert _placed_price(ctx) == round(740.835, 2)

    def test_short_rounds_3dp_price(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        ctx = _mock_ctx_ok()
        p._place_short(ctx, acc_id=1, symbol="US.SPY", price=740.835, qty=1)
        assert _placed_price(ctx) == round(740.835, 2)

    def test_cover_rounds_3dp_price(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        ctx = _mock_ctx_ok()
        p._place_cover(ctx, acc_id=1, symbol="US.SPY", price=740.835, qty=1)
        assert _placed_price(ctx) == round(740.835, 2)

    def test_clean_2dp_price_unchanged(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        ctx = _mock_ctx_ok()
        p._place_buy(ctx, acc_id=1, symbol="US.SPY", price=740.50, qty=1)
        assert _placed_price(ctx) == 740.50

    def test_integer_price_unchanged(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        ctx = _mock_ctx_ok()
        p._place_buy(ctx, acc_id=1, symbol="US.SPY", price=740.0, qty=1)
        assert _placed_price(ctx) == 740.0

    def test_buy_returns_order_id_on_success(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        ctx = _mock_ctx_ok(order_id="99999")
        result = p._place_buy(ctx, acc_id=1, symbol="US.SPY", price=100.0, qty=1)
        assert result == "99999"

    def test_buy_returns_empty_string_on_failure(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        ctx = _mock_ctx_fail()
        result = p._place_buy(ctx, acc_id=1, symbol="US.SPY", price=100.0, qty=1)
        assert result == ""

    def test_sell_returns_empty_string_on_failure(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        ctx = _mock_ctx_fail()
        result = p._place_sell(ctx, acc_id=1, symbol="US.SPY", price=100.0, qty=1)
        assert result == ""


# ---------------------------------------------------------------------------
# _qty() — fractional fallback
# ---------------------------------------------------------------------------

class TestQtyFallback:
    """Sub-1 fractional qty must fall back to whole-share (caught June 5 zero-trade session)."""

    def test_whole_share_mode_returns_int(self, monkeypatch):
        p = _reload_paper(monkeypatch, {"MAX_POSITION_DOLLARS": "900"})
        p._slot_dollars = 0.0
        qty = p._qty(500.0, "US.SPY")
        assert isinstance(qty, int)
        assert qty == 1

    def test_fractional_large_capital_returns_float_above_one(self, monkeypatch):
        p = _reload_paper(monkeypatch, {"FRACTIONAL_SHARES": "true", "MAX_POSITION_DOLLARS": "900"})
        p._slot_dollars = 5000.0
        qty = p._qty(100.0, "US.SPY")
        assert qty >= 1.0
        assert isinstance(qty, float)

    def test_fractional_sub_one_falls_back_to_whole_share(self, monkeypatch):
        """$12.50 slot at $720/share → 0.017 fractional → must fall back to qty=1."""
        p = _reload_paper(monkeypatch, {"FRACTIONAL_SHARES": "true", "MAX_POSITION_DOLLARS": "900"})
        p._slot_dollars = 12.50
        qty = p._qty(720.0, "US.SPY")
        assert qty >= 1
        assert isinstance(qty, int)

    def test_fractional_exactly_one_not_fallen_back(self, monkeypatch):
        p = _reload_paper(monkeypatch, {"FRACTIONAL_SHARES": "true", "MAX_POSITION_DOLLARS": "900"})
        p._slot_dollars = 720.0
        qty = p._qty(720.0, "US.SPY")
        assert qty >= 1.0

    def test_fallback_still_respects_position_cap(self, monkeypatch):
        """Whole-share fallback returns 0 when even 1 share exceeds the dollar cap."""
        p = _reload_paper(monkeypatch, {"FRACTIONAL_SHARES": "true", "MAX_POSITION_DOLLARS": "500"})
        p._slot_dollars = 12.50
        qty = p._qty(720.0, "US.SPY")
        assert qty == 0

    def test_zero_slot_dollars_uses_whole_share(self, monkeypatch):
        p = _reload_paper(monkeypatch, {"MAX_POSITION_DOLLARS": "900"})
        p._slot_dollars = 0.0
        qty = p._qty(300.0, "US.IWM")
        assert isinstance(qty, int)
        assert qty == 3


# ---------------------------------------------------------------------------
# _entry_attempted — per-candle dedup
# ---------------------------------------------------------------------------

class TestEntryAttempted:
    """One order attempt per (symbol, strategy, candle) — prevents the 60s retry storm."""

    def test_fresh_symbol_strategy_not_blocked(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        p._entry_attempted.clear()
        assert p._entry_attempted.get(("US.SPY", "bb_kdj")) != "2026-06-08 09:45:00"

    def test_same_candle_blocked_after_attempt(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        p._entry_attempted.clear()
        key = ("US.SPY", "bb_kdj")
        candle_ts = "2026-06-08 09:45:00"
        p._entry_attempted[key] = candle_ts
        assert p._entry_attempted.get(key) == candle_ts

    def test_next_candle_not_blocked(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        p._entry_attempted.clear()
        key = ("US.SPY", "bb_kdj")
        p._entry_attempted[key] = "2026-06-08 09:45:00"
        assert p._entry_attempted.get(key) != "2026-06-08 09:50:00"

    def test_different_strategy_independent(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        p._entry_attempted.clear()
        candle_ts = "2026-06-08 09:45:00"
        p._entry_attempted[("US.SPY", "bb_kdj")] = candle_ts
        assert p._entry_attempted.get(("US.SPY", "orb")) != candle_ts

    def test_different_symbol_independent(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        p._entry_attempted.clear()
        candle_ts = "2026-06-08 09:45:00"
        p._entry_attempted[("US.SPY", "bb_kdj")] = candle_ts
        assert p._entry_attempted.get(("US.QQQ", "bb_kdj")) != candle_ts

    def test_dedup_clears_on_module_reload(self, monkeypatch):
        p = _reload_paper(monkeypatch, {})
        p._entry_attempted[("US.SPY", "bb_kdj")] = "2026-06-08 09:45:00"
        p2 = _reload_paper(monkeypatch, {})
        assert len(p2._entry_attempted) == 0
