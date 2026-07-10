"""End-to-end replay tests: drive the REAL paper runner over historic candles
with a fake broker and assert pipeline invariants that unit tests can't see
(cross-function wiring, day rollovers, reconcile interplay, retry loops).

Uses a short slice of the real combined CSVs — skipped if the data files are
absent (e.g. fresh clone without logs/).
"""
import json
from pathlib import Path

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
STRATS = ["bb_kdj", "bb_kdj_loose", "orb", "vwap_pb"]


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

    def test_never_fills_means_zero_trades(self, tmp_path):
        """Broker that fills nothing → no positions, no PnL, only unfilled skips.
        Under the pre-2026-06-10 fire-and-forget layer this scenario produced
        fictional PnL — this is the regression test for that entire bug class."""
        s = _run(tmp_path, "never", csvs=[CSV])
        assert s["opens"] == 0
        assert s["closes"] == 0
        assert s["total_pnl"] == 0.0
        assert s["entry_unfilled"] > 0

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


def test_symbol_from_csv():
    assert symbol_from_csv(Path("logs/US_SPY_K_5M_combined.csv")) == "US.SPY"
    assert symbol_from_csv(Path("US_IWM_K_15M_2026-05-31.csv")) == "US.IWM"
