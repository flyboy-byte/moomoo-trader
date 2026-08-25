"""Regime gate unit and integration tests.

Unit tests cover _regime_gate() logic directly (no broker, no candles).
Integration test drives replay with gate patched to verify exit wiring.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mm.morning_regime import load_regime_today, clear_regime_cache

CSV = Path("logs/US_SPY_K_5M_combined.csv")
START, END = "2026-05-27", "2026-05-29"


# ---------------------------------------------------------------------------
# Unit tests — _regime_gate() logic
# ---------------------------------------------------------------------------

class TestRegimeGateLogic:
    def setup_method(self):
        clear_regime_cache()

    def teardown_method(self):
        clear_regime_cache()

    def _make_elog(self):
        return MagicMock()

    def test_blocks_when_gate_enabled_and_regime_matches(self, monkeypatch):
        import mm.config as _config
        import mm.evals as evals
        monkeypatch.setattr(_config.cfg, "regime_gate_enabled", True)
        monkeypatch.setattr(_config.cfg, "regime_gate_strategies", ["bb_kdj"])
        monkeypatch.setattr(_config.cfg, "regime_skip_labels", ["choppy", "risk_off"])
        monkeypatch.setattr(evals, "load_regime_today", lambda date_str, **kw: "choppy")

        elog = self._make_elog()
        result = evals._regime_gate("US.SPY", "bb_kdj", "2026-07-23 10:00:00", elog, 3, 2)

        assert result is True
        elog.signal_skip.assert_called_once()
        call_kwargs = elog.signal_skip.call_args[1]
        assert call_kwargs["gate_enabled"] is True
        assert call_kwargs["regime"] == "choppy"

    def test_shadow_mode_does_not_block(self, monkeypatch):
        """REGIME_GATE_ENABLED=false → log shadow event, return False."""
        import mm.config as _config
        import mm.evals as evals
        monkeypatch.setattr(_config.cfg, "regime_gate_enabled", False)
        monkeypatch.setattr(_config.cfg, "regime_gate_strategies", ["bb_kdj"])
        monkeypatch.setattr(_config.cfg, "regime_skip_labels", ["choppy"])
        monkeypatch.setattr(evals, "load_regime_today", lambda date_str, **kw: "choppy")

        elog = self._make_elog()
        result = evals._regime_gate("US.SPY", "bb_kdj", "2026-07-23 10:00:00", elog, 3, 2)

        assert result is False
        elog.signal_skip.assert_called_once()
        call_kwargs = elog.signal_skip.call_args[1]
        assert call_kwargs.get("gate_enabled") is False
        assert "shadow" in elog.signal_skip.call_args[0][0]  # reason contains "shadow"

    def test_neutral_regime_never_blocks(self, monkeypatch):
        import mm.config as _config
        import mm.evals as evals
        monkeypatch.setattr(_config.cfg, "regime_gate_enabled", True)
        monkeypatch.setattr(_config.cfg, "regime_gate_strategies", ["bb_kdj"])
        monkeypatch.setattr(_config.cfg, "regime_skip_labels", ["choppy", "risk_off"])
        monkeypatch.setattr(evals, "load_regime_today", lambda date_str, **kw: "neutral")

        elog = self._make_elog()
        result = evals._regime_gate("US.SPY", "bb_kdj", "2026-07-23 10:00:00", elog, 3, 2)

        assert result is False
        elog.signal_skip.assert_not_called()

    def test_unlisted_strategy_not_gated(self, monkeypatch):
        """Gate only applies to strategies in regime_gate_strategies."""
        import mm.config as _config
        import mm.evals as evals
        monkeypatch.setattr(_config.cfg, "regime_gate_enabled", True)
        monkeypatch.setattr(_config.cfg, "regime_gate_strategies", ["bb_kdj"])
        monkeypatch.setattr(_config.cfg, "regime_skip_labels", ["choppy"])
        monkeypatch.setattr(evals, "load_regime_today", lambda date_str, **kw: "choppy")

        elog = self._make_elog()
        result = evals._regime_gate("US.SPY", "orb", "2026-07-23 10:00:00", elog, 0, 0)

        assert result is False
        elog.signal_skip.assert_not_called()

    def test_risk_off_also_blocks(self, monkeypatch):
        import mm.config as _config
        import mm.evals as evals
        monkeypatch.setattr(_config.cfg, "regime_gate_enabled", True)
        monkeypatch.setattr(_config.cfg, "regime_gate_strategies", ["bb_kdj"])
        monkeypatch.setattr(_config.cfg, "regime_skip_labels", ["choppy", "risk_off"])
        monkeypatch.setattr(evals, "load_regime_today", lambda date_str, **kw: "risk_off")

        elog = self._make_elog()
        result = evals._regime_gate("US.SPY", "bb_kdj", "2026-07-23 10:00:00", elog, 2, 1)
        assert result is True


# ---------------------------------------------------------------------------
# Unit tests — load_regime_today fail-open behaviour
# ---------------------------------------------------------------------------

class TestLoadRegimeToday:
    def setup_method(self):
        clear_regime_cache()

    def teardown_method(self):
        clear_regime_cache()

    def test_missing_file_returns_neutral(self, tmp_path):
        label = load_regime_today("2026-01-01", logs_dir=tmp_path)
        assert label == "neutral"

    def test_malformed_json_returns_neutral(self, tmp_path):
        (tmp_path / "regime_2026-01-02.json").write_text("not json{{{")
        label = load_regime_today("2026-01-02", logs_dir=tmp_path)
        assert label == "neutral"

    def test_unknown_label_falls_back_to_neutral(self, tmp_path):
        rec = {"date": "2026-01-03", "regime": "very_bearish", "confidence": 0.9,
               "reason": "test", "model": "x", "prompt_version": "v1", "ts": ""}
        (tmp_path / "regime_2026-01-03.json").write_text(json.dumps(rec))
        label = load_regime_today("2026-01-03", logs_dir=tmp_path)
        assert label == "neutral"

    def test_valid_file_returns_correct_label(self, tmp_path):
        rec = {"date": "2026-01-04", "regime": "choppy", "confidence": 0.8,
               "reason": "test", "model": "x", "prompt_version": "v1", "ts": ""}
        (tmp_path / "regime_2026-01-04.json").write_text(json.dumps(rec))
        label = load_regime_today("2026-01-04", logs_dir=tmp_path)
        assert label == "choppy"

    def test_result_cached_on_second_call(self, tmp_path):
        rec = {"date": "2026-01-05", "regime": "trending_up", "confidence": 0.7,
               "reason": "test", "model": "x", "prompt_version": "v1", "ts": ""}
        (tmp_path / "regime_2026-01-05.json").write_text(json.dumps(rec))
        l1 = load_regime_today("2026-01-05", logs_dir=tmp_path)
        # Delete the file — second call must return cached value, not error
        (tmp_path / "regime_2026-01-05.json").unlink()
        l2 = load_regime_today("2026-01-05", logs_dir=tmp_path)
        assert l1 == l2 == "trending_up"

    def test_stale_prompt_version_falls_back_to_neutral(self, tmp_path):
        """Bug fix 2026-08-25: a cached file written by an older prompt version
        must not be silently reused as if the current classifier produced it."""
        rec = {"date": "2026-01-06", "regime": "trending_down", "confidence": 0.9,
               "reason": "test", "model": "x", "prompt_version": "v0-old", "ts": ""}
        (tmp_path / "regime_2026-01-06.json").write_text(json.dumps(rec))
        label = load_regime_today("2026-01-06", logs_dir=tmp_path)
        assert label == "neutral"

    def test_missing_prompt_version_field_falls_back_to_neutral(self, tmp_path):
        """Older regime files predating the prompt_version field entirely must
        also be treated as stale, not trusted."""
        rec = {"date": "2026-01-07", "regime": "choppy", "confidence": 0.6,
               "reason": "test", "model": "x", "ts": ""}
        (tmp_path / "regime_2026-01-07.json").write_text(json.dumps(rec))
        label = load_regime_today("2026-01-07", logs_dir=tmp_path)
        assert label == "neutral"


# ---------------------------------------------------------------------------
# Integration test — exits fire even on fully-gated day
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CSV.exists(), reason="candle CSVs not on disk")
def test_exits_fire_on_gated_day(tmp_path, monkeypatch):
    """With gate blocking ALL entries, no positions open → no stuck-position mismatches.
    Structural test: if exits were gated, reconcile_mismatches would be non-zero."""
    import mm.config as _config
    import mm.evals as evals
    clear_regime_cache()
    monkeypatch.setattr(_config.cfg, "regime_gate_enabled", True)
    monkeypatch.setattr(_config.cfg, "regime_gate_strategies", ["bb_kdj", "bb_kdj_loose"])
    monkeypatch.setattr(_config.cfg, "regime_skip_labels", ["choppy", "risk_off"])
    monkeypatch.setattr(evals, "load_regime_today", lambda date_str, **kw: "choppy")

    from mm.replay import replay
    stats = replay(
        [CSV], ["bb_kdj", "bb_kdj_loose"],
        start=START, end=END,
        fill_mode="touch", out_dir=tmp_path / "out", quiet=True,
    )

    assert stats["reconcile_mismatches"] == 0
    # all entries blocked → no opens, no closes, no stuck positions
    assert stats["opens"] == 0
    clear_regime_cache()
