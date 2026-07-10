"""Unit tests for _eval_bb_kdj_loose in mm/evals.py.

Key differences from _eval_bb_kdj that are tested here:
  1. No bonus gate — any BB touch + KDJ cross fires (bonus_score ignored)
  2. No ADX/ranging filter at entry
  3. MAX_TRADES_PER_DAY=0 → unlimited global trades
"""
import importlib
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload(monkeypatch, extra_env: dict | None = None):
    """Reload config/risk/evals with a minimal paper-trading environment."""
    env = {
        "TRD_ENV": "SIMULATE",
        "LIVE_TRADING_ENABLED": "false",
        "MAX_POSITION_DOLLARS": "900",
        "FRACTIONAL_SHARES": "false",
        "MAX_TRADES_PER_DAY": "0",       # unlimited global
        "MAX_TRADES_PER_STRATEGY": "0",  # unlimited per-strategy
        "MIN_SIGNAL_SCORE": "2",         # standard gate — loose ignores this
        "KDJ_WINDOW_BARS": "3",
    }
    if extra_env:
        env.update(extra_env)
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))

    import mm.config
    importlib.reload(mm.config)
    mm.config.cfg = mm.config.Config()
    import mm.risk
    importlib.reload(mm.risk)
    import mm.clock
    importlib.reload(mm.clock)
    import mm.evals
    importlib.reload(mm.evals)
    mm.clock.is_market_open = lambda: True
    return mm.evals


def _df(close=100.0, bb_lower=101.0, bb_middle=103.0, atr=1.0,
        bb_touch=True, kdj_cross=True,
        bonus_score=0, adx=30.0, rsi=40.0, volume=1000, volume_ma=500,
        ts="2026-01-05 10:00:00", n_bars=4):
    """Build a minimal signals DataFrame for use in bb_kdj_loose tests.

    bb_touch=True requires close <= bb_lower — caller is responsible for
    passing consistent values; the flag is used for the sig_bb_touch column
    directly rather than recomputing it from close/bb_lower.
    """
    rows = []
    for i in range(n_bars):
        bar_ts = pd.Timestamp(ts) - pd.Timedelta(minutes=5 * (n_bars - 1 - i))
        rows.append({
            "time_key": str(bar_ts),
            "close": close,
            "bb_lower": bb_lower,
            "bb_middle": bb_middle,
            "atr": atr,
            "adx": adx,
            "rsi": rsi,
            "volume": volume,
            "volume_ma": volume_ma,
            "sig_bb_touch": bb_touch,
            "sig_kdj_cross": kdj_cross,
            "kdj_golden_cross": kdj_cross,
            "kdj_death_cross": False,
            "bonus_score": bonus_score,
        })
    return pd.DataFrame(rows)


def _mock_ctx(order_id="99", fill_price=None, fill_qty=None):
    """Fake broker that immediately confirms every order as FILLED_ALL."""
    ctx = MagicMock()
    ctx.place_order.return_value = (0, pd.DataFrame({"order_id": [order_id]}))

    def _order_list_query(order_id=None, trd_env=None, acc_id=None):
        fp = fill_price if fill_price is not None else 100.0
        fq = fill_qty if fill_qty is not None else 9.0
        return (0, pd.DataFrame({
            "order_status": ["FILLED_ALL"],
            "dealt_qty": [fq],
            "dealt_avg_price": [fp],
        }))

    ctx.order_list_query.side_effect = _order_list_query
    return ctx


def _elog():
    return MagicMock()


def _daily(evals_mod):
    from mm.risk import DailyTracker
    return DailyTracker()


# ---------------------------------------------------------------------------
# Test: no bonus gate
# ---------------------------------------------------------------------------

class TestNoBonusGate:
    def test_fires_with_bonus_zero(self, monkeypatch, tmp_path):
        """bb_kdj_loose enters on BB touch + KDJ cross even when bonus_score=0.

        With MIN_SIGNAL_SCORE=2, standard bb_kdj would skip this bar. The loose
        variant has no bonus gate so it must place an order.
        """
        evals = _reload(monkeypatch)
        monkeypatch.setattr(evals._config.cfg, "logs_dir", tmp_path)

        df = _df(close=100.0, bb_lower=101.0, bb_touch=True, kdj_cross=True,
                 bonus_score=0)
        ctx = _mock_ctx()
        elog = _elog()
        daily = _daily(evals)

        # reset dedup state
        evals._entry_attempted.clear()

        pos = evals._eval_bb_kdj_loose("US.SPY", df, ctx, 1, None, elog, daily)
        assert pos is not None
        ctx.place_order.assert_called_once()

    def test_fires_with_bonus_below_min_score(self, monkeypatch, tmp_path):
        """bonus_score=1 < MIN_SIGNAL_SCORE=2 still fires for loose variant."""
        evals = _reload(monkeypatch)
        monkeypatch.setattr(evals._config.cfg, "logs_dir", tmp_path)

        df = _df(close=100.0, bb_lower=101.0, bb_touch=True, kdj_cross=True,
                 bonus_score=1)
        ctx = _mock_ctx()
        evals._entry_attempted.clear()

        pos = evals._eval_bb_kdj_loose("US.SPY", df, ctx, 1, None, _elog(), _daily(evals))
        assert pos is not None

    def test_standard_bb_kdj_skips_when_bonus_zero(self, monkeypatch, tmp_path):
        """Contrast: standard bb_kdj does NOT fire when bonus=0 < MIN_SIGNAL_SCORE=2."""
        evals = _reload(monkeypatch)
        monkeypatch.setattr(evals._config.cfg, "logs_dir", tmp_path)

        df = _df(close=100.0, bb_lower=101.0, bb_touch=True, kdj_cross=True,
                 bonus_score=0)
        ctx = _mock_ctx()
        evals._entry_attempted.clear()

        pos = evals._eval_bb_kdj("US.SPY", df, ctx, 1, None, _elog(), _daily(evals))
        assert pos is None
        ctx.place_order.assert_not_called()


# ---------------------------------------------------------------------------
# Test: core gate still required (no signal → no trade)
# ---------------------------------------------------------------------------

class TestCoreGateRequired:
    def test_no_bb_touch_no_entry(self, monkeypatch, tmp_path):
        """Without BB touch the loose strategy must not fire."""
        evals = _reload(monkeypatch)
        monkeypatch.setattr(evals._config.cfg, "logs_dir", tmp_path)

        df = _df(close=105.0, bb_lower=101.0, bb_touch=False, kdj_cross=True,
                 bonus_score=3)
        ctx = _mock_ctx()
        evals._entry_attempted.clear()

        pos = evals._eval_bb_kdj_loose("US.SPY", df, ctx, 1, None, _elog(), _daily(evals))
        assert pos is None
        ctx.place_order.assert_not_called()

    def test_no_kdj_cross_no_entry(self, monkeypatch, tmp_path):
        """Without KDJ golden cross in the window the loose strategy must not fire."""
        evals = _reload(monkeypatch)
        monkeypatch.setattr(evals._config.cfg, "logs_dir", tmp_path)

        df = _df(close=100.0, bb_lower=101.0, bb_touch=True, kdj_cross=False,
                 bonus_score=3)
        ctx = _mock_ctx()
        evals._entry_attempted.clear()

        pos = evals._eval_bb_kdj_loose("US.SPY", df, ctx, 1, None, _elog(), _daily(evals))
        assert pos is None
        ctx.place_order.assert_not_called()


# ---------------------------------------------------------------------------
# Test: high ADX does NOT block entry (no ranging filter)
# ---------------------------------------------------------------------------

class TestNoAdxFilter:
    def test_fires_in_trending_market(self, monkeypatch, tmp_path):
        """ADX=40 (trending regime) must not block bb_kdj_loose entry."""
        evals = _reload(monkeypatch)
        monkeypatch.setattr(evals._config.cfg, "logs_dir", tmp_path)

        df = _df(close=100.0, bb_lower=101.0, bb_touch=True, kdj_cross=True,
                 adx=40.0, bonus_score=0)
        ctx = _mock_ctx()
        evals._entry_attempted.clear()

        pos = evals._eval_bb_kdj_loose("US.SPY", df, ctx, 1, None, _elog(), _daily(evals))
        assert pos is not None


# ---------------------------------------------------------------------------
# Test: unlimited daily trades (MAX_TRADES_PER_DAY=0)
# ---------------------------------------------------------------------------

class TestUnlimitedDailyTrades:
    def test_can_open_after_many_trades(self, monkeypatch, tmp_path):
        """DailyTracker.can_open returns True even after several trades when limit=0."""
        _reload(monkeypatch, {"MAX_TRADES_PER_DAY": "0"})
        from mm.risk import DailyTracker
        daily = DailyTracker()
        for _ in range(10):
            daily.record_trade(1.0, strategy="bb_kdj_loose")
        assert daily.can_open(strategy="bb_kdj_loose")

    def test_second_entry_allowed_same_day(self, monkeypatch, tmp_path):
        """Two consecutive entries on the same day both succeed when limit=0."""
        evals = _reload(monkeypatch)
        monkeypatch.setattr(evals._config.cfg, "logs_dir", tmp_path)
        daily = _daily(evals)

        # First entry
        df1 = _df(ts="2026-01-05 10:00:00")
        evals._entry_attempted.clear()
        pos = evals._eval_bb_kdj_loose("US.SPY", df1, _mock_ctx("1"), 1, None, _elog(), daily)
        assert pos is not None
        daily.record_trade(1.0, strategy="bb_kdj_loose")

        # Simulate position close, then second entry opportunity on same day
        df2 = _df(ts="2026-01-05 11:00:00")
        pos2 = evals._eval_bb_kdj_loose("US.SPY", df2, _mock_ctx("2"), 1, None, _elog(), daily)
        assert pos2 is not None


# ---------------------------------------------------------------------------
# Test: entry deduplication (same candle_ts → only one order)
# ---------------------------------------------------------------------------

class TestEntryDedup:
    def test_same_candle_only_one_order(self, monkeypatch, tmp_path):
        """Calling eval twice with the same candle timestamp must place only one order."""
        evals = _reload(monkeypatch)
        monkeypatch.setattr(evals._config.cfg, "logs_dir", tmp_path)

        df = _df(ts="2026-01-05 10:00:00")
        ctx = _mock_ctx()
        elog = _elog()
        daily = _daily(evals)
        evals._entry_attempted.clear()

        # First call → should open
        pos = evals._eval_bb_kdj_loose("US.SPY", df, ctx, 1, None, elog, daily)
        assert pos is not None
        assert ctx.place_order.call_count == 1

        # Second call same candle — dedup fires, no additional order
        evals._eval_bb_kdj_loose("US.SPY", df, ctx, 1, None, elog, daily)
        assert ctx.place_order.call_count == 1


# ---------------------------------------------------------------------------
# Test: exit logic
# ---------------------------------------------------------------------------

class TestExitLogic:
    def _open_position(self, evals, symbol="US.SPY"):
        from mm.events import PaperPosition
        return PaperPosition(
            symbol=symbol, strategy="bb_kdj_loose",
            entry_time="2026-01-05 10:00:00", entry_price=100.0,
            stop_price=98.0, qty=3.0, order_id="42",
        )

    def test_stop_loss_exit(self, monkeypatch, tmp_path):
        """close < stop_price triggers STOP_LOSS exit."""
        evals = _reload(monkeypatch)
        monkeypatch.setattr(evals._config.cfg, "logs_dir", tmp_path)

        pos = self._open_position(evals)
        df = _df(close=97.0, bb_lower=101.0, bb_middle=103.0)  # close < stop 98.0
        ctx = _mock_ctx()
        ctx.place_order.return_value = (0, pd.DataFrame({"order_id": ["sell1"]}))
        elog = _elog()
        daily = _daily(evals)
        evals._entry_attempted.clear()

        result = evals._eval_bb_kdj_loose("US.SPY", df, ctx, 1, pos, elog, daily)
        assert result is None  # position closed
        ctx.place_order.assert_called_once()
        elog.position_close.assert_called_once()
        args = elog.position_close.call_args
        assert args.kwargs.get("exit_reason") == "STOP_LOSS" or \
               "STOP_LOSS" in str(args)

    def test_bb_middle_target_exit(self, monkeypatch, tmp_path):
        """close >= bb_middle triggers TARGET_BB_MIDDLE exit."""
        evals = _reload(monkeypatch)
        monkeypatch.setattr(evals._config.cfg, "logs_dir", tmp_path)

        pos = self._open_position(evals)
        df = _df(close=104.0, bb_lower=101.0, bb_middle=103.0)  # close > bb_middle
        ctx = _mock_ctx()
        ctx.place_order.return_value = (0, pd.DataFrame({"order_id": ["sell2"]}))
        elog = _elog()
        daily = _daily(evals)
        evals._entry_attempted.clear()

        result = evals._eval_bb_kdj_loose("US.SPY", df, ctx, 1, pos, elog, daily)
        assert result is None
        ctx.place_order.assert_called_once()

    def test_no_exit_when_between_bands(self, monkeypatch, tmp_path):
        """close between stop and bb_middle → position held, no order."""
        evals = _reload(monkeypatch)
        monkeypatch.setattr(evals._config.cfg, "logs_dir", tmp_path)

        pos = self._open_position(evals)
        df = _df(close=101.0, bb_lower=101.0, bb_middle=103.0, bb_touch=False)
        ctx = _mock_ctx()
        elog = _elog()
        daily = _daily(evals)
        evals._entry_attempted.clear()

        result = evals._eval_bb_kdj_loose("US.SPY", df, ctx, 1, pos, elog, daily)
        assert result is pos   # same position returned, not closed
        ctx.place_order.assert_not_called()
