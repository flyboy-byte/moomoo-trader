"""End-to-end replay tests: drive the REAL paper runner over historic candles
with a fake broker and assert pipeline invariants that unit tests can't see
(cross-function wiring, day rollovers, reconcile interplay, retry loops).

Uses a short slice of the real combined CSVs — skipped if the data files are
absent (e.g. fresh clone without logs/).
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mm.replay import replay, FakeBroker, symbol_from_csv

CSV = Path("logs/US_SPY_K_5M_combined.csv")
CSVS_ALL = [
    Path("logs/US_SPY_K_5M_combined.csv"),
    Path("logs/US_QQQ_K_5M_combined.csv"),
    Path("logs/US_IWM_K_5M_combined.csv"),
]

pytestmark = pytest.mark.skipif(not CSV.exists(), reason="combined candle CSVs not on disk")

# Three sessions with known trade activity (replay smoke window)
START, END = "2026-05-27", "2026-05-29"
STRATS = ["bb_kdj", "bb_kdj_loose", "orb", "vwap_pb", "gap_fade"]


def _run(tmp_path, fill_mode, csvs=None):
    return replay(csvs or CSVS_ALL, STRATS, start=START, end=END,
                  fill_mode=fill_mode, out_dir=tmp_path / fill_mode, quiet=True)


class TestReplayInvariants:
    def test_touch_mode_runs_clean(self, tmp_path):
        s = _run(tmp_path, "touch")
        # every close pairs with an open; the runner never books an unconfirmed close
        assert s["closes"] + len(s["still_open"]) == s["opens"]
        assert s["reconcile_mismatches"] == 0
        assert s["opens"] > 0  # the window is known to produce trades

    def test_never_fills_means_zero_trades(self, tmp_path, monkeypatch):
        """Broker that fills nothing → no positions, no PnL, only unfilled skips.
        Under the pre-2026-06-10 fire-and-forget layer this scenario produced
        fictional PnL — this is the regression test for that entire bug class.

        Scorer is suppressed (api_key="") so ORB entries reach order placement —
        otherwise the scorer gate blocks them before any order is placed and
        entry_unfilled stays 0 (correct behaviour, wrong for this test's intent)."""
        import mm.config as _config
        import mm.evals as _evals
        monkeypatch.setattr(_config.cfg, "anthropic_api_key", "")
        monkeypatch.setattr(_config.cfg, "orb_vix_max", None)
        monkeypatch.setattr(_config.cfg, "orb_vix_max_overrides", {})
        _evals._vix_cache.clear()
        s = _run(tmp_path, "never", csvs=[CSV])
        assert s["opens"] == 0
        assert s["closes"] == 0
        assert s["total_pnl"] == 0.0
        assert s["entry_unfilled"] > 0
        _evals._vix_cache.clear()

    def test_entry_only_keeps_positions_open(self, tmp_path):
        """Exits that never fill must keep the position and book nothing
        (the June 4 failure shape: SPY/QQQ ORB exits died unfilled while
        the old layer booked wins)."""
        s = _run(tmp_path, "entry_only", csvs=[CSV])
        assert s["closes"] == 0
        assert s["total_pnl"] == 0.0
        if s["opens"]:
            assert s["still_open"]          # positions survive to the end
            assert s["exit_unfilled"] > 0   # and the runner kept retrying

    def test_pnl_matches_fill_prices(self, tmp_path):
        """Every recorded close PnL must equal (exit−entry)×qty from the
        actual fill prices in the same event stream — no model PnL anywhere."""
        s = _run(tmp_path, "touch", csvs=[CSV])
        out = Path(s["out_dir"])
        events = [json.loads(l) for f in out.glob("paper_*.jsonl")
                  for l in f.read_text().splitlines()]
        opens = [e for e in events if e["event"] == "position_open"]
        for c in (e for e in events if e["event"] == "position_close"):
            o = next(o for o in opens
                     if o["strategy"] == c["strategy"] and o["symbol"] == c["symbol"]
                     and o["ts"] <= c["ts"])
            sign = -1 if c.get("direction") == "short" else 1
            expected = sign * (c["exit"] - o["entry"]) * o["qty"]
            assert abs(expected - c["pnl"]) < 0.01, (
                f"{c['symbol']}/{c['strategy']}: booked {c['pnl']} != fills {expected:.4f}")


class TestFakeBroker:
    def test_touch_fill_uses_next_bar(self):
        import pandas as pd
        df = pd.DataFrame({
            "time_key": pd.to_datetime(["2026-01-05 09:30:00", "2026-01-05 09:35:00"]),
            "open": [100.0, 99.0], "high": [101.0, 99.5],
            "low": [99.5, 98.0], "close": [100.5, 99.2], "volume": [1000, 1000],
        })
        b = FakeBroker({"US.TEST": df}, fill_mode="touch")
        b.set_index("US.TEST", 0)
        # buy limit 100: next bar opens at 99 → gap fill at the open
        ret, data = b.place_order(price=100.0, qty=1, code="US.TEST", trd_side="BUY")
        oid = data["order_id"].iloc[0]
        _, od = b.order_list_query(order_id=oid)
        assert od.iloc[0]["order_status"] == "FILLED_ALL"
        assert od.iloc[0]["dealt_avg_price"] == 99.0
        # buy limit 50: next bar never trades there → stays SUBMITTED, cancellable
        _, data = b.place_order(price=50.0, qty=1, code="US.TEST", trd_side="BUY")
        oid2 = data["order_id"].iloc[0]
        _, od2 = b.order_list_query(order_id=oid2)
        assert od2.iloc[0]["order_status"] == "SUBMITTED"
        b.modify_order(None, oid2, 0, 0)
        _, od2 = b.order_list_query(order_id=oid2)
        assert od2.iloc[0]["order_status"] == "CANCELLED_ALL"

    def test_position_tracking(self):
        import pandas as pd
        df = pd.DataFrame({
            "time_key": pd.to_datetime(["2026-01-05 09:30:00"]),
            "open": [100.0], "high": [100.0], "low": [100.0],
            "close": [100.0], "volume": [1000],
        })
        b = FakeBroker({"US.TEST": df}, fill_mode="instant")
        b.place_order(price=100, qty=2, code="US.TEST", trd_side="BUY")
        _, pos = b.position_list_query()
        assert float(pos.iloc[0]["qty"]) == 2.0
        b.place_order(price=101, qty=2, code="US.TEST", trd_side="SELL")
        _, pos = b.position_list_query()
        assert pos.empty  # flat positions are not reported


def test_close_fill_mode_ignores_marketable_buffer():
    """fill_mode='close' fills at the signal bar's close, not the buffered limit."""
    import pandas as pd
    df = pd.DataFrame({
        "time_key": pd.to_datetime(["2026-01-05 09:30:00", "2026-01-05 09:35:00"]),
        "open": [100.0, 99.0], "high": [101.0, 99.5], "low": [99.0, 98.0],
        "close": [100.0, 99.0], "volume": [1000, 1000],
    })
    b = FakeBroker({"US.TEST": df}, fill_mode="close")
    b.set_index("US.TEST", 0)
    _, data = b.place_order(price=99.7, qty=1, code="US.TEST", trd_side="SELL")
    _, od = b.order_list_query(order_id=data["order_id"].iloc[0])
    assert float(od.iloc[0]["dealt_avg_price"]) == 100.0


def test_symbol_from_csv():
    assert symbol_from_csv(Path("logs/US_SPY_K_5M_combined.csv")) == "US.SPY"
    assert symbol_from_csv(Path("US_IWM_K_15M_2026-05-31.csv")) == "US.IWM"


# ---------------------------------------------------------------------------
# Regime gate end-to-end: verify wiring through the full replay pipeline
# IWM 2024-01-02→10 is a known bb_kdj trade window (1 trade fires naturally)
# ---------------------------------------------------------------------------

CSV_IWM = Path("logs/US_IWM_K_5M_combined.csv")
BB_STRATS = ["bb_kdj", "bb_kdj_loose"]
REGIME_START, REGIME_END = "2024-01-02", "2024-01-10"


def _regime_replay(tmp_path, regime_label, monkeypatch):
    import mm.config as _config
    from mm.morning_regime import clear_regime_cache
    clear_regime_cache()
    monkeypatch.setattr(_config.cfg, "regime_gate_enabled", True)
    monkeypatch.setattr(_config.cfg, "regime_gate_strategies", BB_STRATS)
    monkeypatch.setattr(_config.cfg, "regime_skip_labels", ["trending_up", "trending_down"])
    with patch("mm.evals.load_regime_today", return_value=regime_label):
        stats = replay(
            [CSV_IWM], BB_STRATS,
            start=REGIME_START, end=REGIME_END,
            fill_mode="touch", out_dir=tmp_path / "out", quiet=True,
        )
    events = [
        json.loads(line)
        for f in (tmp_path / "out").glob("paper_*.jsonl")
        for line in f.read_text().splitlines()
    ]
    clear_regime_cache()
    return stats, events


@pytest.mark.skipif(not CSV_IWM.exists(), reason="IWM candle CSV not on disk")
def test_trending_up_blocks_bb_kdj_entries(tmp_path, monkeypatch):
    """regime=trending_up (live skip label) must suppress all bb_kdj entries end-to-end."""
    stats, events = _regime_replay(tmp_path, "trending_up", monkeypatch)

    assert stats["opens"] == 0, "no entries should open when regime is a skip label"

    regime_skips = [
        e for e in events
        if e.get("event") == "signal_skip" and e.get("reason") == "regime_gate"
    ]
    assert len(regime_skips) > 0, "regime_gate signal_skip events must be logged"


@pytest.mark.skipif(not CSV_IWM.exists(), reason="IWM candle CSV not on disk")
def test_neutral_regime_does_not_block_bb_kdj(tmp_path, monkeypatch):
    """regime=neutral must not emit any regime_gate skips — gate should be transparent."""
    stats, events = _regime_replay(tmp_path, "neutral", monkeypatch)

    regime_skips = [
        e for e in events
        if e.get("event") == "signal_skip" and e.get("reason") == "regime_gate"
    ]
    assert len(regime_skips) == 0, "neutral regime must never produce regime_gate skips"

    # The window is known to produce at least one bb_kdj trade when unblocked
    assert stats["opens"] >= 1, "neutral regime should allow entries in this known-trade window"


# ---------------------------------------------------------------------------
# Gap Fade large gap-up short filter, end-to-end through the live eval path.
# QQQ 2026-03-23 gapped up 1.58% and faded — the research engine filters it;
# until 2026-09-17 the live path ignored GAP_LARGE_SHORT_FILTER_ENABLED.
# ---------------------------------------------------------------------------

CSV_QQQ = Path("logs/US_QQQ_K_5M_combined.csv")


def _gap_replay(tmp_path, monkeypatch, enabled):
    import mm.gap_fade as _gf
    monkeypatch.setattr(_gf, "GAP_LARGE_SHORT_FILTER_ENABLED", enabled)
    monkeypatch.setattr(_gf, "GAP_MAX_SHORT_PCT", 0.01)
    stats = replay([CSV_QQQ], ["gap_fade"], start="2026-03-20", end="2026-03-23",
                   fill_mode="close", out_dir=tmp_path / "out", quiet=True)
    events = [json.loads(line)
              for f in (tmp_path / "out").glob("paper_*.jsonl")
              for line in f.read_text().splitlines()]
    return stats, [e for e in events if e.get("event") == "signal_skip"
                   and str(e.get("reason", "")).startswith("gap_large_short")]


@pytest.mark.skipif(not CSV_QQQ.exists(), reason="QQQ candle CSV not on disk")
def test_large_gap_short_blocked_live_when_enabled(tmp_path, monkeypatch):
    stats, skips = _gap_replay(tmp_path, monkeypatch, enabled=True)
    assert stats["opens"] == 0
    assert [s["reason"] for s in skips] == ["gap_large_short"]


@pytest.mark.skipif(not CSV_QQQ.exists(), reason="QQQ candle CSV not on disk")
def test_large_gap_short_shadow_logs_but_trades_when_disabled(tmp_path, monkeypatch):
    stats, skips = _gap_replay(tmp_path, monkeypatch, enabled=False)
    assert stats["opens"] == 1
    assert [s["reason"] for s in skips] == ["gap_large_short_shadow"]


def test_replay_never_writes_to_real_logs_after_config_reload(tmp_path, monkeypatch):
    """Regression 2026-09-17: after a test reloaded mm.config (but not mm.paper),
    replay redirected only paper.cfg, and mm.events kept writing JSONL and
    *_traded.json into the real logs/ directory."""
    import importlib
    import mm.config
    import mm.paper
    importlib.reload(mm.config)
    mm.config.cfg = mm.config.Config()
    assert mm.config.cfg is not mm.paper.cfg          # the split that caused the leak
    decoy = tmp_path / "real_logs"
    monkeypatch.setattr(mm.config.cfg, "logs_dir", decoy)
    replay([CSV_QQQ], ["gap_fade"], start="2026-03-20", end="2026-03-23",
           fill_mode="close", out_dir=tmp_path / "out", quiet=True)
    assert not decoy.exists() or not any(decoy.iterdir())
    assert any((tmp_path / "out").glob("paper_*.jsonl"))
    assert mm.config.cfg.logs_dir == decoy            # restored afterwards
