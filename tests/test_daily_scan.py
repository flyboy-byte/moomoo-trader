"""Route 3 engine rules (mm/daily_scan.py): no lookahead, costs on turnover, selection."""
import numpy as np
import pandas as pd
import pytest

from mm import daily_scan as ds


def _daily(closes, sigs=None, opens=None):
    idx = pd.bdate_range("2022-01-03", periods=len(closes)).strftime("%Y-%m-%d")
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": closes if opens is None else opens, "close": closes,
                         "sig": closes if sigs is None else sigs}, index=idx)


def test_build_daily_signal_is_15_minutes_before_close(tmp_path):
    times = pd.date_range("2022-01-03 09:35", "2022-01-03 16:00", freq="5min")
    df = pd.DataFrame({"time_key": times.strftime("%Y-%m-%d %H:%M:%S"),
                       "open": np.arange(len(times)) + 100.5,
                       "close": np.arange(len(times)) + 101.0})
    p = tmp_path / "x.csv"
    df.to_csv(p, index=False)
    d = ds.build_daily(p)
    last = df.iloc[-1]
    assert d.loc["2022-01-03", "open"] == 100.5
    assert d.loc["2022-01-03", "close"] == last["close"]
    assert d.loc["2022-01-03", "sig"] == df.loc[df.time_key.str.endswith("15:45:00"),
                                                "close"].item()


def test_overnight_uses_next_open_and_charges_cost():
    d = _daily([100, 100, 100], opens=[100, 101, 100])
    r = ds.overnight_rows(d, cost_bps=2.0)
    assert len(r) == 2
    assert r["gross_bps"].iloc[0] == pytest.approx(100.0)
    assert r["net_bps"].iloc[0] == pytest.approx(98.0)


def test_trend_exposure_never_sees_the_day_it_holds():
    base = list(np.linspace(100, 150, 260))
    d1, d2 = _daily(base), _daily(base[:-1] + [10.0])     # crash on the last day only
    w1, w2 = ds.trend_exposure(d1), ds.trend_exposure(d2)
    assert w1.iloc[-1] == w2.iloc[-1] == 1.0
    assert w1.iloc[:201].isna().all() and w1.iloc[201:].notna().all()


def test_vol_exposure_is_lagged_and_capped():
    rng = np.random.default_rng(0)
    closes = 100 * np.cumprod(1 + rng.normal(0, 0.01, 200))
    d = _daily(closes)
    w = ds.vol_exposure(d)
    changed = d.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] *= 1.5
    changed.iloc[-1, changed.columns.get_loc("sig")] *= 1.5
    assert ds.vol_exposure(changed).iloc[-1] == w.iloc[-1]
    assert (w.dropna() <= 1.0).all() and w.dropna().gt(0).all()


def test_constant_exposure_has_zero_timing_return_after_entry():
    d = _daily([100, 101, 99, 103, 104])
    w = pd.Series([np.nan, 1.0, 1.0, 1.0, 1.0], index=d.index)
    rows = ds.timing_rows(d, w, cost_bps=4.0)
    assert rows["gross_bps"].abs().max() == pytest.approx(0.0)
    assert rows["turnover"].tolist() == [1.0, 0.0, 0.0, 0.0]
    assert rows["net_bps"].iloc[0] == pytest.approx(-2.0)


def test_xsec_picks_top_n_and_charges_both_legs():
    idx = pd.bdate_range("2022-01-03", periods=15).strftime("%Y-%m-%d")
    panel = {}
    for k in range(4):
        closes = 100 * (1 + 0.01 * k) ** np.arange(15)
        panel[f"S{k}"] = pd.DataFrame({"open": closes, "close": closes, "sig": closes},
                                      index=idx)
    rows = ds.xsec_rows(panel, {s: 2.0 for s in panel}, lookback=2, highest=True, top=2)
    # after the first Friday rebalance: long S2+S3 vs equal-weight all four
    assert rows["gross_bps"].iloc[1] == pytest.approx(
        (0.02 + 0.03) / 2 * 1e4 - (0.0 + 0.01 + 0.02 + 0.03) / 4 * 1e4)
    first = rows.iloc[0]
    assert first["net_bps"] == pytest.approx(first["gross_bps"] - 2.0 / 2 + 2.0 / 2)
