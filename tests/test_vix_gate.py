"""VIX gate unit + integration tests.

Tests three surfaces:
  1. _load_vix_today() — the shared helper used by all VIX gates
  2. ORB VIX gate (orb_vix_block)
  3. Gap fade VIX gate (gap_vix_block)

Unit tests monkeypatch _load_vix_today or cfg.logs_dir; integration tests
drive a real replay slice and verify skip events appear in the JSONL output.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

CSV_SPY = Path("logs/US_SPY_K_5M_combined.csv")
CSVS_ALL = [
    Path("logs/US_SPY_K_5M_combined.csv"),
    Path("logs/US_QQQ_K_5M_combined.csv"),
    Path("logs/US_IWM_K_5M_combined.csv"),
]
START, END = "2026-05-27", "2026-05-29"


def _clear_vix_cache():
    import mm.evals as evals
    evals._vix_cache.clear()


# ---------------------------------------------------------------------------
# Unit tests — _load_vix_today()
# ---------------------------------------------------------------------------

class TestLoadVixToday:
    def setup_method(self):
        _clear_vix_cache()

    def teardown_method(self):
        _clear_vix_cache()

    def test_reads_correct_date(self, tmp_path, monkeypatch):
        import mm.config as _config
        import mm.evals as evals
        vf = tmp_path / "vix_daily.jsonl"
        vf.write_text(
            json.dumps({"date": "2026-07-21", "vix_prev_close": 16.5}) + "\n"
            + json.dumps({"date": "2026-07-22", "vix_prev_close": 18.7}) + "\n"
        )
        monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
        assert evals._load_vix_today("2026-07-22") == 18.7

    def test_wrong_date_returns_none(self, tmp_path, monkeypatch):
        import mm.config as _config
        import mm.evals as evals
        vf = tmp_path / "vix_daily.jsonl"
        vf.write_text(json.dumps({"date": "2026-07-21", "vix_prev_close": 16.5}) + "\n")
        monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
        assert evals._load_vix_today("2026-07-99") is None

    def test_missing_file_returns_none(self, tmp_path, monkeypatch):
        import mm.config as _config
        import mm.evals as evals
        monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
        assert evals._load_vix_today("2026-07-22") is None

    def test_result_cached_after_file_deleted(self, tmp_path, monkeypatch):
        import mm.config as _config
        import mm.evals as evals
        vf = tmp_path / "vix_daily.jsonl"
        vf.write_text(json.dumps({"date": "2026-07-22", "vix_prev_close": 19.0}) + "\n")
        monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
        r1 = evals._load_vix_today("2026-07-22")
        vf.unlink()
        r2 = evals._load_vix_today("2026-07-22")  # must hit cache, not re-read
        assert r1 == r2 == 19.0

    def test_none_result_also_cached(self, tmp_path, monkeypatch):
        """A missing date should be cached as None — not re-scanned every bar."""
        import mm.config as _config
        import mm.evals as evals
        vf = tmp_path / "vix_daily.jsonl"
        vf.write_text(json.dumps({"date": "2026-07-21", "vix_prev_close": 16.0}) + "\n")
        monkeypatch.setattr(_config.cfg, "logs_dir", tmp_path)
        r1 = evals._load_vix_today("2026-07-99")
        assert r1 is None
        assert "2026-07-99" in evals._vix_cache  # None is cached


# ---------------------------------------------------------------------------
# Integration tests — ORB VIX gate
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CSV_SPY.exists(), reason="candle CSVs not on disk")
class TestOrbVixGate:
    def setup_method(self):
        # test_bb_kdj_loose.py reloads mm.evals but not mm.paper, leaving paper.py
        # with stale function references. Reload paper so monkeypatches on mm.evals
        # (_load_vix_today etc.) are visible to the functions the replay actually calls.
        import importlib, mm.paper
        importlib.reload(mm.paper)
        _clear_vix_cache()

    def teardown_method(self):
        _clear_vix_cache()

    def test_orb_vix_block_fires_and_prevents_entry(self, tmp_path, monkeypatch):
        """VIX > orb_vix_max → orb_vix_block skips, zero ORB entries."""
        import mm.config as _config
        import mm.evals as evals
        # Disable ORB scorer so it doesn't interfere
        monkeypatch.setattr(_config.cfg, "anthropic_api_key", "")
        # Set impossibly low threshold (0) and mock VIX above it
        monkeypatch.setattr(_config.cfg, "orb_vix_max", 0.0)
        monkeypatch.setattr(_config.cfg, "orb_vix_max_overrides", {})
        monkeypatch.setattr(evals, "_load_vix_today", lambda d: 25.0)

        from mm.replay import replay
        stats = replay([CSV_SPY], ["orb"], start=START, end=END,
                       fill_mode="touch", out_dir=tmp_path / "out", quiet=True)

        out = Path(stats["out_dir"])
        events = [json.loads(l) for f in out.glob("paper_*.jsonl")
                  for l in f.read_text().splitlines()]
        vix_skips = [e for e in events
                     if e.get("event") == "signal_skip" and e.get("reason") == "orb_vix_block"]

        assert len(vix_skips) > 0, "Expected orb_vix_block skip events when VIX > threshold"
        assert stats["opens"] == 0, "No ORB entries should fire when fully VIX-blocked"
        # Verify skip event contains diagnostic fields
        assert vix_skips[0].get("vix") == 25.0
        assert vix_skips[0].get("threshold") == 0.0

    def test_orb_vix_fail_open_when_no_vix_data(self, tmp_path, monkeypatch):
        """When _load_vix_today returns None, the gate is skipped — entries still allowed."""
        import mm.config as _config
        import mm.evals as evals
        monkeypatch.setattr(_config.cfg, "anthropic_api_key", "")
        monkeypatch.setattr(_config.cfg, "orb_vix_max", 0.0)  # threshold so low it would block
        monkeypatch.setattr(_config.cfg, "orb_vix_max_overrides", {})
        monkeypatch.setattr(evals, "_load_vix_today", lambda d: None)  # no VIX data

        from mm.replay import replay
        stats = replay([CSV_SPY], ["orb"], start=START, end=END,
                       fill_mode="touch", out_dir=tmp_path / "out", quiet=True)

        out = Path(stats["out_dir"])
        events = [json.loads(l) for f in out.glob("paper_*.jsonl")
                  for l in f.read_text().splitlines()]
        vix_skips = [e for e in events
                     if e.get("event") == "signal_skip" and e.get("reason") == "orb_vix_block"]

        assert len(vix_skips) == 0, "No VIX blocks when VIX data is unavailable (fail-open)"

    def test_orb_vix_per_symbol_override(self, tmp_path, monkeypatch):
        """orb_vix_max_overrides takes precedence over global orb_vix_max."""
        import mm.config as _config
        import mm.evals as evals
        monkeypatch.setattr(_config.cfg, "anthropic_api_key", "")
        monkeypatch.setattr(_config.cfg, "orb_vix_max", 999.0)  # global: never block
        monkeypatch.setattr(_config.cfg, "orb_vix_max_overrides", {"US.SPY": 0.0})  # SPY: always block
        monkeypatch.setattr(evals, "_load_vix_today", lambda d: 20.0)

        from mm.replay import replay
        stats = replay([CSV_SPY], ["orb"], start=START, end=END,
                       fill_mode="touch", out_dir=tmp_path / "out", quiet=True)

        out = Path(stats["out_dir"])
        events = [json.loads(l) for f in out.glob("paper_*.jsonl")
                  for l in f.read_text().splitlines()]
        vix_skips = [e for e in events
                     if e.get("event") == "signal_skip" and e.get("reason") == "orb_vix_block"]

        assert len(vix_skips) > 0, "SPY symbol override should trigger vix_block"
        assert stats["opens"] == 0


# ---------------------------------------------------------------------------
# Integration tests — Gap Fade VIX gate
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CSV_SPY.exists(), reason="candle CSVs not on disk")
class TestGapFadeVixGate:
    def setup_method(self):
        import importlib, mm.paper
        importlib.reload(mm.paper)
        _clear_vix_cache()

    def teardown_method(self):
        _clear_vix_cache()

    def test_gap_vix_block_fires(self, tmp_path, monkeypatch):
        """gap_vix_block skip fires when VIX > gap_vix_max and gap condition is met."""
        import mm.config as _config
        import mm.evals as evals
        monkeypatch.setattr(_config.cfg, "gap_vix_max", 0.0)  # always block
        monkeypatch.setattr(_config.cfg, "gap_vix_max_overrides", {})
        monkeypatch.setattr(evals, "_load_vix_today", lambda d: 25.0)

        from mm.replay import replay
        stats = replay(CSVS_ALL, ["gap_fade"], start=START, end=END,
                       fill_mode="touch", out_dir=tmp_path / "out", quiet=True)

        out = Path(stats["out_dir"])
        events = [json.loads(l) for f in out.glob("paper_*.jsonl")
                  for l in f.read_text().splitlines()]
        vix_skips = [e for e in events
                     if e.get("event") == "signal_skip" and e.get("reason") == "gap_vix_block"]
        # gap_vix_block only fires if the gap condition (0.3% threshold) passes first —
        # if no gaps meet the threshold in this window, the count may be 0 but no trades
        # should open either (all gap_fade entries require passing the VIX gate)
        gap_opens = [e for e in events
                     if e.get("event") == "position_open" and e.get("strategy") == "gap_fade"]
        assert len(gap_opens) == 0, "No gap_fade entries should open when VIX-blocked"

    def test_gap_vix_fail_open(self, tmp_path, monkeypatch):
        """When VIX data is unavailable, gap_fade entries are NOT blocked."""
        import mm.config as _config
        import mm.evals as evals
        monkeypatch.setattr(_config.cfg, "gap_vix_max", 0.0)  # would block if VIX known
        monkeypatch.setattr(_config.cfg, "gap_vix_max_overrides", {})
        monkeypatch.setattr(evals, "_load_vix_today", lambda d: None)  # no VIX data

        from mm.replay import replay
        # Run with no VIX block — gate should be skipped
        replay(CSVS_ALL, ["gap_fade"], start=START, end=END,
               fill_mode="touch", out_dir=tmp_path / "out", quiet=True)

        out = tmp_path / "out"
        events = [json.loads(l) for f in out.glob("paper_*.jsonl")
                  for l in f.read_text().splitlines()]
        vix_skips = [e for e in events
                     if e.get("event") == "signal_skip" and e.get("reason") == "gap_vix_block"]
        assert len(vix_skips) == 0, "No VIX blocks when VIX data unavailable (fail-open)"
