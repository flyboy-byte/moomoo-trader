"""Crypto pilot engine (mm/crypto.py): archive parsing, no lookahead, eligibility."""
import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from mm import crypto as cx


def _zip(rows, header=False):
    buf = io.BytesIO()
    lines = ([",".join(cx.KLINE_COLS)] if header else []) + [",".join(map(str, r)) for r in rows]
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", "\n".join(lines) + "\n")
    return buf.getvalue()


def _row(ts, close):
    return [ts, close, close, close, close, 1, ts + 1, 1, 1, 1, 1, 0]


def test_parse_handles_ms_us_and_header():
    ms = cx.parse_klines(_zip([_row(1514764800000, 1.0)]))
    us = cx.parse_klines(_zip([_row(1735689600000000, 2.0)], header=True))
    assert ms["ts"].iloc[0] == pd.Timestamp("2018-01-01")
    assert us["ts"].iloc[0] == pd.Timestamp("2025-01-01")
    assert len(us) == 1


class _Resp:
    def __init__(self, code, content=b""):
        self.status_code, self.content = code, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_fetch_skips_missing_months_and_caches(tmp_path):
    calls = []

    def get(url):
        calls.append(url)
        if "2018-02" in url:
            return _Resp(404)
        return _Resp(200, _zip([_row(1514764800000, 1.0)]))

    out = tmp_path / "x.csv"
    cx.fetch_klines("BTCUSDT", "1d", "2018-01", "2018-02", out, get=get)
    cx.fetch_klines("BTCUSDT", "1d", "2018-01", "2018-02", out, get=get)
    assert len(pd.read_csv(out)) == 1
    assert sum("2018-01" in c for c in calls) == 1          # cached on the second run


def _daily(closes):
    idx = pd.date_range("2018-01-01", periods=len(closes)).strftime("%Y-%m-%d")
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": c, "close": c, "sig": c}, index=idx)


def test_trend_is_lagged_and_waits_for_eligibility():
    base = list(np.linspace(100, 200, 150))
    w = cx.trend_exposure(_daily(base))
    assert w.iloc[:cx.ELIGIBLE_AFTER_DAYS + 1].isna().all()
    assert w.iloc[-1] == 1.0
    crashed = cx.trend_exposure(_daily(base[:-1] + [1.0]))
    assert crashed.iloc[-1] == 1.0                          # today's crash is not seen today


def test_trend_votes_are_thirds():
    closes = list(np.linspace(100, 200, 120)) + list(np.linspace(200, 150, 15))
    w = cx.trend_exposure(_daily(closes)).dropna()
    assert set(np.round(w.unique() * 3)).issubset({0, 1, 2, 3})
    assert w.iloc[-1] == pytest.approx(1 / 3)               # 10d and 30d down, 90d still up


def test_xmom_ignores_coins_before_eligibility():
    n = 140
    panel = {f"C{k}": _daily(100 * (1 + 0.001 * k) ** np.arange(n)) for k in range(10)}
    late = _daily(np.r_[np.full(60, np.nan), 100 * 1.05 ** np.arange(n - 60)])
    panel["LATE"] = late.dropna()
    rows = cx.xmom_rows(panel, {s: 50.0 for s in panel}, "2018-01-01", "2018-12-31")
    assert not rows.empty
    # LATE has the best return but only becomes eligible 90 days after its first bar
    assert rows["date"].iloc[0] >= pd.Timestamp("2018-04-01").strftime("%Y-%m-%d")
