"""Step 6c selection rules and Step 11 holdout discipline (mm/scan.py, scripts/wide_scan.py)."""
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from mm import scan


def test_bh_step_up():
    p = {"a": 0.001, "b": 0.02, "c": 0.03, "d": 0.5}
    # thresholds at q=0.10, m=4: .025 .05 .075 .10 -> a, b, c pass (c by step-up)
    assert scan.benjamini_hochberg(p, 0.10) == {"a", "b", "c"}
    assert scan.benjamini_hochberg({"a": 0.2, "b": 0.3}, 0.10) == set()


def _lane(n, p, lo):
    return {"n": n, "p_one_sided": p, "net_bps_ci": (lo, lo + 5)}


def test_finalists_need_min_trades_and_are_ranked_and_capped():
    lanes = {f"L{i}": _lane(100, 0.0001, float(i)) for i in range(15)}
    lanes["thin"] = _lane(10, 0.00001, 99.0)          # ineligible: too few trades
    got = scan.select_finalists(lanes, cap=10)
    assert "thin" not in got
    assert got == [f"L{i}" for i in range(14, 4, -1)]


def test_no_survivors_means_no_finalists():
    lanes = {f"L{i}": _lane(100, 0.4, 1.0) for i in range(20)}
    assert scan.select_finalists(lanes) == []


def test_holdout_verdicts():
    good = {"n": 50, "p_one_sided": 0.001, "mean_net_bps": 4.0}
    assert scan.holdout_verdict(good, {"mean_net_bps": 0.5}, 0.01) == "replicated"
    assert scan.holdout_verdict(good, {"mean_net_bps": -0.1}, 0.01) == "not_replicated"
    assert scan.holdout_verdict({**good, "p_one_sided": 0.02}, {"mean_net_bps": 1}, 0.01) \
        == "not_replicated"
    assert scan.holdout_verdict({**good, "n": 5}, {"mean_net_bps": 1}, 0.01) == "not_testable"


@dataclass
class _T:
    entry_time: pd.Timestamp
    entry_price: float
    pnl: float
    direction: str = "long"


def test_trade_rows_drop_warmup_and_apply_costs():
    trades = [_T(pd.Timestamp("2021-12-20 10:00"), 100.0, 1.0),
              _T(pd.Timestamp("2022-01-03 10:00"), 100.0, 1.0)]
    rows = scan.trade_rows("US.SPY", "orb", trades, scan.DEV_START, scan.DEV_END)
    assert [r["date"] for r in rows] == ["2022-01-03"]
    assert rows[0]["gross_bps"] == pytest.approx(100.0)
    assert rows[0]["net_bps"] == pytest.approx(100.0 - 1.5)


def test_lane_stats_stress_lowers_mean():
    rows = [{"date": f"2022-01-{d:02d}", "direction": "long", "gross_pnl": 0.1, "net_pnl": 0.08,
             "gross_bps": 5.0, "net_bps": 3.5, "cost_bps": 1.5} for d in range(3, 28)]
    plain, stressed = scan.lane_stats(rows), scan.lane_stats(rows, 3.5)
    assert plain["mean_net_bps"] == pytest.approx(3.5)
    assert stressed["mean_net_bps"] == pytest.approx(0.0)


def test_holdout_refuses_without_committed_finalists(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path("scripts").resolve()))
    import wide_scan
    monkeypatch.setattr(wide_scan, "FINALISTS", tmp_path / "finalists.json")
    monkeypatch.setattr(wide_scan, "ROOT", tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    args = type("A", (), {"data_dir": tmp_path, "workers": 1})()
    with pytest.raises(SystemExit, match="refusing"):
        wide_scan.cmd_holdout(args)
    (tmp_path / "finalists.json").write_text('{"pooled_passing_dev": [], "finalists": []}')
    with pytest.raises(SystemExit, match="refusing"):          # exists but not committed
        wide_scan.cmd_holdout(args)
