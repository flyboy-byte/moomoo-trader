"""ORB setup scorer gate tests.

Regression tests for two bugs fixed 2026-07-25:
  1. Fail-open confidence was 0.5 (below the 0.65 gate) — should be 1.0.
     With confidence=0.5, any API failure silently blocked ALL ORB entries.
  2. signal_skip("orb_claude_score", ..., reason=...) passed 'reason' both as
     positional arg and keyword arg → TypeError on every block → the exception
     was swallowed by the paper runner's main loop, entries skipped by crash
     rather than by the intended code path, no skip events in JSONL.

Plus forward-looking coverage: low confidence blocks entry (skip event appears),
high confidence allows entry, scorer not called when API key absent.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

CSV_SPY = Path("logs/US_SPY_K_5M_combined.csv")
START, END = "2026-05-27", "2026-05-29"


# ---------------------------------------------------------------------------
# Unit tests — fail-open invariants
# ---------------------------------------------------------------------------

def test_fail_open_confidence_is_1():
    """Regression: fail-open score must have confidence >= ORB_ENTRY_MIN_CONFIDENCE.
    If it's below the gate threshold (0.65), every API failure silently blocks entries."""
    from mm.morning_regime import _FAIL_OPEN_SCORE
    assert _FAIL_OPEN_SCORE["confidence"] == 1.0, (
        "Fail-open must be 1.0 so API failures never block ORB entries. "
        "Confidence 0.5 was the original bug — see 2026-07-25 fix."
    )


def test_fail_open_confidence_above_default_gate():
    """Fail-open confidence must exceed the default ORB_ENTRY_MIN_CONFIDENCE (0.65)."""
    from mm.morning_regime import _FAIL_OPEN_SCORE
    import mm.config as _config
    assert _FAIL_OPEN_SCORE["confidence"] > _config.cfg.orb_entry_min_confidence


# ---------------------------------------------------------------------------
# Integration tests — scorer gate wiring (replay-based)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CSV_SPY.exists(), reason="candle CSVs not on disk")
class TestOrbScorerGate:
    def setup_method(self):
        # test_bb_kdj_loose.py reloads mm.evals but not mm.paper, leaving paper.py
        # with stale function references. Reload paper so monkeypatches on mm.evals
        # are visible to the functions the replay actually calls.
        import importlib, mm.paper, mm.evals
        importlib.reload(mm.paper)
        mm.evals._vix_cache.clear()

    def teardown_method(self):
        import mm.evals
        mm.evals._vix_cache.clear()

    def test_low_confidence_emits_skip_not_error(self, tmp_path, monkeypatch):
        """Regression: scorer returning low confidence must emit orb_claude_score skip,
        NOT an error event. Before the 2026-07-25 fix, a TypeError in signal_skip
        caused an error event instead — entries were blocked by crash, not by gate."""
        import mm.config as _config
        import mm.evals as evals

        monkeypatch.setattr(_config.cfg, "orb_setup_scorer_enabled", True)
        monkeypatch.setattr(_config.cfg, "orb_entry_min_confidence", 0.65)
        monkeypatch.setattr(_config.cfg, "anthropic_api_key", "test-key")
        monkeypatch.setattr(_config.cfg, "orb_vix_max", None)
        monkeypatch.setattr(_config.cfg, "orb_vix_max_overrides", {})
        # Scorer always returns low confidence → should block all ORB entries
        monkeypatch.setattr(evals, "score_orb_setup",
                            lambda sym, ts, setup: {"confidence": 0.2, "reason": "test-block"})

        from mm.replay import replay
        import json
        stats = replay([CSV_SPY], ["orb"], start=START, end=END,
                       fill_mode="touch", out_dir=tmp_path / "out", quiet=True)

        out = Path(stats["out_dir"])
        events = [json.loads(l) for f in out.glob("paper_*.jsonl")
                  for l in f.read_text().splitlines()]

        scorer_skips = [e for e in events
                        if e.get("event") == "signal_skip"
                        and e.get("reason") == "orb_claude_score"]
        error_events = [e for e in events if e.get("event") == "error"]

        assert len(scorer_skips) > 0, (
            "orb_claude_score skip events must appear when scorer blocks. "
            "If zero, the signal_skip call is crashing (TypeError bug)."
        )
        # No TypeError errors from the scorer path
        scorer_errors = [e for e in error_events
                         if "multiple values" in e.get("message", "")
                         or "signal_skip" in e.get("message", "")]
        assert scorer_errors == [], f"signal_skip TypeError still occurring: {scorer_errors}"
        assert stats["opens"] == 0, "No ORB entries should fire when scorer blocks all"

    def test_high_confidence_allows_entry(self, tmp_path, monkeypatch):
        """Scorer returning confidence >= gate threshold must not block entries."""
        import mm.config as _config
        import mm.evals as evals
        import mm.evals as _evals
        _evals._vix_cache.clear()

        monkeypatch.setattr(_config.cfg, "orb_setup_scorer_enabled", True)
        monkeypatch.setattr(_config.cfg, "orb_entry_min_confidence", 0.65)
        monkeypatch.setattr(_config.cfg, "anthropic_api_key", "test-key")
        monkeypatch.setattr(_config.cfg, "orb_vix_max", None)
        monkeypatch.setattr(_config.cfg, "orb_vix_max_overrides", {})
        # Scorer always passes → entries allowed
        monkeypatch.setattr(evals, "score_orb_setup",
                            lambda sym, ts, setup: {"confidence": 0.9, "reason": "test-allow"})
        monkeypatch.setattr(evals, "_load_vix_today", lambda d: None)

        from mm.replay import replay
        import json
        stats = replay([CSV_SPY], ["orb"], start=START, end=END,
                       fill_mode="touch", out_dir=tmp_path / "out", quiet=True)

        out = Path(stats["out_dir"])
        events = [json.loads(l) for f in out.glob("paper_*.jsonl")
                  for l in f.read_text().splitlines()]
        scorer_skips = [e for e in events
                        if e.get("event") == "signal_skip"
                        and e.get("reason") == "orb_claude_score"]

        assert len(scorer_skips) == 0, "Scorer should not block when confidence is high"
        # Some entries may or may not fire (depends on vol/OR conditions), but none
        # should be blocked by the scorer
        _evals._vix_cache.clear()

    def test_scorer_not_called_when_api_key_absent(self, tmp_path, monkeypatch):
        """With no API key, score_orb_setup must never be called."""
        import mm.config as _config
        import mm.evals as evals

        monkeypatch.setattr(_config.cfg, "anthropic_api_key", "")
        monkeypatch.setattr(_config.cfg, "orb_vix_max", None)
        monkeypatch.setattr(_config.cfg, "orb_vix_max_overrides", {})

        calls = []
        monkeypatch.setattr(evals, "score_orb_setup",
                            lambda sym, ts, setup: calls.append((sym, ts)) or {"confidence": 0.0, "reason": "x"})

        from mm.replay import replay
        replay([CSV_SPY], ["orb"], start=START, end=END,
               fill_mode="touch", out_dir=tmp_path / "out", quiet=True)

        assert calls == [], f"score_orb_setup called {len(calls)} times with no API key"

    def test_scorer_skip_contains_confidence_field(self, tmp_path, monkeypatch):
        """orb_claude_score skip events must include confidence and claude_reason fields
        so api_usage.jsonl and log analysis can track what the scorer returned."""
        import mm.config as _config
        import mm.evals as evals
        import json

        monkeypatch.setattr(_config.cfg, "orb_setup_scorer_enabled", True)
        monkeypatch.setattr(_config.cfg, "orb_entry_min_confidence", 0.65)
        monkeypatch.setattr(_config.cfg, "anthropic_api_key", "test-key")
        monkeypatch.setattr(_config.cfg, "orb_vix_max", None)
        monkeypatch.setattr(_config.cfg, "orb_vix_max_overrides", {})
        monkeypatch.setattr(evals, "score_orb_setup",
                            lambda sym, ts, setup: {"confidence": 0.3, "reason": "weak-setup"})

        from mm.replay import replay
        stats = replay([CSV_SPY], ["orb"], start=START, end=END,
                       fill_mode="touch", out_dir=tmp_path / "out", quiet=True)

        out = Path(stats["out_dir"])
        events = [json.loads(l) for f in out.glob("paper_*.jsonl")
                  for l in f.read_text().splitlines()]
        scorer_skips = [e for e in events if e.get("reason") == "orb_claude_score"]

        if scorer_skips:
            s = scorer_skips[0]
            assert "confidence" in s, "Skip event must include confidence field"
            assert "claude_reason" in s, "Skip event must include claude_reason (not 'reason' collision)"
            assert s["confidence"] == 0.3
            assert s["claude_reason"] == "weak-setup"
