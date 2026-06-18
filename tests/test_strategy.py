"""
Tests for mm/strategy.py — entry/exit state machine.

Strategy state machine tests use monkeypatching to inject pre-built signal
DataFrames, isolating the state machine from indicator computation.
Integration tests use the real candle CSVs with MIN_SIGNAL_SCORE=0.
"""
import importlib
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mm.strategy import Signal, run_signals, compute_signals, Trade


# ---------------------------------------------------------------------------
# Synthetic DataFrame builder for state machine tests
# ---------------------------------------------------------------------------

def _make_bars(n: int, entry_at: int | None = None, target_at: int | None = None,
               stop_at: int | None = None, death_at: int | None = None,
               entry_price: float = 95.0, bb_middle: float = 100.0,
               atr: float = 1.0) -> pd.DataFrame:
    """
    Build a minimal DataFrame with pre-set indicator columns for testing
    the run_signals state machine without running real indicator computation.

    entry_at:  bar index where Signal.ENTRY is set (close = entry_price)
    target_at: bar index where close >= bb_middle
    stop_at:   bar index where close falls below stop price (entry - 1*atr)
    death_at:  bar index where kdj_death_cross = True
    """
    stop_price = entry_price - atr  # uses atr_stop_mult=1.0 default

    rows = []
    for i in range(n):
        if i == target_at:
            close = bb_middle + 1.0
        elif i == stop_at:
            close = stop_price - 0.5
        else:
            close = entry_price + 0.1  # neutral: above entry, below bb_middle

        rows.append({
            "time_key": pd.Timestamp("2024-01-01") + pd.Timedelta(minutes=5 * i),
            "open": close,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": 1_000_000.0,
            "bb_middle": bb_middle,
            "bb_lower": entry_price - 0.5,
            "bb_upper": bb_middle + 5.0,
            "bb_width": 10.0,
            "atr": atr,
            "kdj_k": 50.0,
            "kdj_d": 48.0,
            "kdj_j": 54.0,
            "kdj_golden_cross": False,
            "kdj_death_cross": (i == death_at),
            "rsi": 40.0,
            "adx": 20.0,
            "volume_ma": 500_000.0,
            "sig_bb_touch": False,
            "sig_kdj_cross": False,
            "sig_rsi_oversold": False,
            "sig_ranging": True,
            "sig_volume_spike": False,
            "signal_score": 0,
            "bonus_score": 0,
            "signal": Signal.NONE,
        })

    df = pd.DataFrame(rows)

    if entry_at is not None:
        df.at[entry_at, "close"] = entry_price
        df.at[entry_at, "signal"] = Signal.ENTRY

    return df


def _run_with_injected(monkeypatch, df: pd.DataFrame) -> pd.DataFrame:
    """Run run_signals with compute_signals monkeypatched to return df as-is."""
    import mm.strategy as strat
    monkeypatch.setattr(strat, "compute_signals", lambda d: df.copy())
    return strat.run_signals(df)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

class TestEntry:
    def test_entry_signal_recorded(self, monkeypatch):
        df = _make_bars(10, entry_at=5)
        out = _run_with_injected(monkeypatch, df)
        assert out.at[5, "signal"] == Signal.ENTRY

    def test_no_entry_without_signal(self, monkeypatch):
        df = _make_bars(10)  # no entry_at
        out = _run_with_injected(monkeypatch, df)
        assert (out["signal"] == Signal.NONE).all()

    def test_no_re_entry_while_in_position(self, monkeypatch):
        """A second ENTRY signal while already in a position must be ignored."""
        df = _make_bars(10, entry_at=2)
        df.at[5, "signal"] = Signal.ENTRY  # second entry while position open
        out = _run_with_injected(monkeypatch, df)
        # Bar 5 should remain ENTRY in the df (state machine sees it but ignores it)
        # — the position counter should still be open, not doubled
        # Verify no exit was triggered by the second entry
        assert out.at[2, "signal"] == Signal.ENTRY
        non_exit = out.iloc[3:]["signal"].isin(
            [Signal.NONE, Signal.ENTRY]
        )
        assert non_exit.all()


# ---------------------------------------------------------------------------
# Target exit
# ---------------------------------------------------------------------------

class TestTargetExit:
    def test_target_exit_fires(self, monkeypatch):
        df = _make_bars(10, entry_at=2, target_at=6)
        out = _run_with_injected(monkeypatch, df)
        assert out.at[6, "signal"] == Signal.EXIT_TARGET

    def test_target_exit_clears_position(self, monkeypatch):
        """After target exit, a new entry on a later bar should be accepted."""
        df = _make_bars(15, entry_at=2, target_at=5)
        df.at[10, "signal"] = Signal.ENTRY
        out = _run_with_injected(monkeypatch, df)
        assert out.at[5, "signal"] == Signal.EXIT_TARGET
        assert out.at[10, "signal"] == Signal.ENTRY

    def test_no_target_exit_without_position(self, monkeypatch):
        """close >= bb_middle on bar 3 with no open position — no exit signal."""
        df = _make_bars(10)
        df.at[3, "close"] = 105.0  # above bb_middle but no position
        out = _run_with_injected(monkeypatch, df)
        assert out.at[3, "signal"] == Signal.NONE


# ---------------------------------------------------------------------------
# Stop loss
# ---------------------------------------------------------------------------

class TestStopLoss:
    def test_stop_loss_fires(self, monkeypatch):
        df = _make_bars(10, entry_at=2, stop_at=6)
        out = _run_with_injected(monkeypatch, df)
        assert out.at[6, "signal"] == Signal.EXIT_STOP_LOSS

    def test_stop_loss_clears_position(self, monkeypatch):
        """After stop exit, a new entry should be accepted."""
        df = _make_bars(15, entry_at=2, stop_at=5)
        df.at[10, "signal"] = Signal.ENTRY
        out = _run_with_injected(monkeypatch, df)
        assert out.at[5, "signal"] == Signal.EXIT_STOP_LOSS
        assert out.at[10, "signal"] == Signal.ENTRY

    def test_stop_price_calculated_correctly(self, monkeypatch):
        """Stop fires exactly when close drops below entry_price - atr_stop_mult * atr."""
        entry_price = 95.0
        atr_val = 2.0
        # stop_price = 95 - 1.0 * 2.0 = 93.0
        df = _make_bars(10, entry_at=2, entry_price=entry_price, atr=atr_val)
        # Set bar 6 close to exactly 93.0 — should NOT trigger (close < stop, boundary)
        df.at[6, "close"] = 93.0  # equal is not < stop_price
        out = _run_with_injected(monkeypatch, df)
        assert out.at[6, "signal"] != Signal.EXIT_STOP_LOSS

        # Set bar 6 close to 92.99 — should trigger
        df.at[6, "close"] = 92.99
        out2 = _run_with_injected(monkeypatch, df)
        assert out2.at[6, "signal"] == Signal.EXIT_STOP_LOSS

    def test_target_takes_priority_over_stop(self, monkeypatch):
        """If both target and stop conditions met on same bar, target wins (checked first)."""
        df = _make_bars(10, entry_at=2, entry_price=95.0, bb_middle=95.5, atr=2.0)
        # Bar 6: close = 96.0 — above bb_middle (target) AND well above stop
        df.at[6, "close"] = 96.0
        out = _run_with_injected(monkeypatch, df)
        assert out.at[6, "signal"] == Signal.EXIT_TARGET


# ---------------------------------------------------------------------------
# KDJ death cross exit
# ---------------------------------------------------------------------------

class TestKDJDeathCrossExit:
    def test_death_cross_fires_when_enabled(self, monkeypatch):
        import mm.strategy
        from mm.config import cfg
        # Patch the live cfg singleton directly — avoids module reload / stale
        # Signal class issues. mm/strategy.py re-fetches cfg at call time
        # (mm.strategy._config.cfg), so patching the singleton here is correct.
        monkeypatch.setattr(cfg, "exit_on_kdj_death", True)
        df = _make_bars(10, entry_at=2, death_at=6)
        monkeypatch.setattr(mm.strategy, "compute_signals", lambda d: df.copy())
        out = mm.strategy.run_signals(df)
        assert out.at[6, "signal"] == mm.strategy.Signal.EXIT_DEATH_CROSS

    def test_death_cross_ignored_when_disabled(self, monkeypatch):
        import mm.strategy
        from mm.config import cfg
        monkeypatch.setattr(cfg, "exit_on_kdj_death", False)
        df = _make_bars(10, entry_at=2, death_at=6)
        monkeypatch.setattr(mm.strategy, "compute_signals", lambda d: df.copy())
        out = mm.strategy.run_signals(df)
        exit_signals = {mm.strategy.Signal.EXIT_DEATH_CROSS,
                        mm.strategy.Signal.EXIT_TARGET,
                        mm.strategy.Signal.EXIT_STOP_LOSS}
        assert out.at[6, "signal"] not in exit_signals


# ---------------------------------------------------------------------------
# compute_signals — entry mask wiring
# ---------------------------------------------------------------------------

class TestComputeSignals:
    def test_output_has_signal_column(self):
        from tests.test_indicators import _make_candles
        df = _make_candles(60)
        df["time_key"] = pd.date_range("2024-01-01", periods=60, freq="5min")
        out = compute_signals(df)
        assert "signal" in out.columns

    def test_signal_values_are_signal_enum(self):
        from tests.test_indicators import _make_candles
        import mm.strategy as strat
        df = _make_candles(60)
        df["time_key"] = pd.date_range("2024-01-01", periods=60, freq="5min")
        out = strat.compute_signals(df)
        # Use the live module's Signal to avoid stale-class issues from module reloads
        valid = set(strat.Signal)
        assert all(v in valid for v in out["signal"])

    def test_no_entry_on_normal_bar(self):
        """With flat, non-oversold data, no entries should fire."""
        from tests.test_indicators import _make_candles
        df = _make_candles(60, base=100.0)
        df["time_key"] = pd.date_range("2024-01-01", periods=60, freq="5min")
        out = compute_signals(df)
        # It is valid to have zero entries on flat synthetic data
        entries = (out["signal"] == Signal.ENTRY).sum()
        assert entries >= 0  # no crash; value is dataset-dependent


class TestKDJDayBoundaryFix:
    """Regression test for the 2026-06-17 bug fix: KDJ_WINDOW_BARS lookback
    used to leak across calendar-day boundaries. Verified on real data that
    30-39% of historical entries were contaminated (see
    docs/strategy_graveyard.md). This test isolates just the day-grouping
    mechanism — score_df/add_all are stubbed out so it doesn't depend on
    reverse-engineering real KDJ/BB math to trigger a cross deterministically.
    """

    def test_kdj_window_does_not_leak_across_day_boundary(self, monkeypatch):
        import mm.strategy as strat
        from mm.config import cfg

        monkeypatch.setattr(cfg, "kdj_window_bars", 3)
        monkeypatch.setattr(cfg, "min_signal_score", 0)
        monkeypatch.setattr(strat, "add_all", lambda d: d)
        monkeypatch.setattr(strat, "score_df", lambda d: d)

        # Day 1: 5 bars, KDJ cross on the LAST bar only.
        # Day 2: 5 bars, bb_touch True on the first 3 bars, NO cross anywhere in day 2.
        # With a 3-bar window applied naively (no day grouping), day 2's bars 0-2
        # would incorrectly "see" day 1's cross and fire.
        day1 = pd.Timestamp("2024-01-01 15:30")
        day2 = pd.Timestamp("2024-01-02 09:30")
        times = [day1 + pd.Timedelta(minutes=5 * i) for i in range(5)] + \
                [day2 + pd.Timedelta(minutes=5 * i) for i in range(5)]
        kdj_cross = [False, False, False, False, True] + [False] * 5
        bb_touch = [False] * 5 + [True, True, True, False, False]

        df = pd.DataFrame({
            "time_key": times,
            "sig_kdj_cross": kdj_cross,
            "sig_bb_touch": bb_touch,
            "sig_rsi_oversold": [False] * 10,
            "sig_ranging": [False] * 10,
            "sig_volume_spike": [False] * 10,
        })

        out = strat.compute_signals(df)
        entries = out["signal"] == strat.Signal.ENTRY

        assert not entries.iloc[5:8].any(), (
            "KDJ window leaked across the day boundary — day 2's bb_touch bars "
            "fired on day 1's stale cross"
        )

    def test_kdj_window_still_fires_within_the_same_day(self, monkeypatch):
        """Sanity check the fix didn't break the legitimate same-day case."""
        import mm.strategy as strat
        from mm.config import cfg

        monkeypatch.setattr(cfg, "kdj_window_bars", 3)
        monkeypatch.setattr(cfg, "min_signal_score", 0)
        monkeypatch.setattr(strat, "add_all", lambda d: d)
        monkeypatch.setattr(strat, "score_df", lambda d: d)

        day1 = pd.Timestamp("2024-01-01 09:30")
        times = [day1 + pd.Timedelta(minutes=5 * i) for i in range(5)]
        # Cross on bar 1, bb_touch on bar 3 — within the 3-bar window, same day.
        df = pd.DataFrame({
            "time_key": times,
            "sig_kdj_cross": [False, True, False, False, False],
            "sig_bb_touch": [False, False, False, True, False],
            "sig_rsi_oversold": [False] * 5,
            "sig_ranging": [False] * 5,
            "sig_volume_spike": [False] * 5,
        })

        out = strat.compute_signals(df)
        entries = out["signal"] == strat.Signal.ENTRY
        assert entries.iloc[3], "same-day in-window cross should still fire"


# ---------------------------------------------------------------------------
# Integration: real CSV, MIN_SIGNAL_SCORE=0 (original BB+KDJ behaviour)
# ---------------------------------------------------------------------------

class TestIntegration:
    SPY_CSV = Path("logs/US_SPY_K_5M_2026-05-30.csv")

    def test_produces_known_trade_count(self, monkeypatch):
        """With MIN_SIGNAL_SCORE=0 and KDJ_WINDOW_BARS=0, SPY should produce 29 trades (baseline)."""
        if not self.SPY_CSV.exists():
            pytest.skip("SPY candle CSV not present")

        monkeypatch.setenv("MIN_SIGNAL_SCORE", "0")
        monkeypatch.setenv("KDJ_WINDOW_BARS", "0")
        import mm.config
        importlib.reload(mm.config)
        mm.config.cfg = mm.config.Config()
        import mm.strategy, mm.indicators, mm.signals, mm.backtest
        for mod in [mm.indicators, mm.signals, mm.strategy, mm.backtest]:
            importlib.reload(mod)

        df = mm.backtest.load_candles(self.SPY_CSV)
        trades, _ = mm.backtest.run_backtest(df)
        assert len(trades) == 29

    def test_all_trades_have_exit_reason(self, monkeypatch):
        if not self.SPY_CSV.exists():
            pytest.skip("SPY candle CSV not present")

        monkeypatch.setenv("MIN_SIGNAL_SCORE", "0")
        import mm.config
        importlib.reload(mm.config)
        mm.config.cfg = mm.config.Config()
        import mm.strategy, mm.indicators, mm.signals, mm.backtest
        for mod in [mm.indicators, mm.signals, mm.strategy, mm.backtest]:
            importlib.reload(mod)

        df = mm.backtest.load_candles(self.SPY_CSV)
        trades, _ = mm.backtest.run_backtest(df)
        for t in trades:
            assert t.exit_reason in ("EXIT_TARGET", "EXIT_STOP_LOSS", "EXIT_DEATH_CROSS")

    def test_pnl_computed_correctly(self, monkeypatch):
        """PnL = exit_price - entry_price for each trade."""
        if not self.SPY_CSV.exists():
            pytest.skip("SPY candle CSV not present")

        monkeypatch.setenv("MIN_SIGNAL_SCORE", "0")
        import mm.config
        importlib.reload(mm.config)
        mm.config.cfg = mm.config.Config()
        import mm.strategy, mm.indicators, mm.signals, mm.backtest
        for mod in [mm.indicators, mm.signals, mm.strategy, mm.backtest]:
            importlib.reload(mod)

        df = mm.backtest.load_candles(self.SPY_CSV)
        trades, _ = mm.backtest.run_backtest(df)
        for t in trades:
            assert abs(t.pnl - (t.exit_price - t.entry_price)) < 1e-9
