"""Canonical trade reconstruction (mm/trades.py) and reporter agreement.

Added 2026-08-29 with the module. The bug this guards against is not a crash — it is
two reporters quietly disagreeing about the same trades:

    web dashboard      +$12.92  PF 1.189   (uncosted, and labelled "net_pnl")
    analyze_trades.py  -$ 0.57  PF 0.992   (net of mm/costs.py)

Both read the same JSONL. Whichever a session opened first won. On top of the missing
cost model, the dashboard also had no pre-confirmed-fill cutoff, so it counted 119
trades where analyze_trades counted 102.

The agreement test at the bottom is the real guard: it fails if either reporter starts
computing its own numbers again.
"""
import json
from pathlib import Path

import pytest

from mm import trades as mmt

LOGS = Path("logs")


# ---------------------------------------------------------------------------
# Pairing and cost application
# ---------------------------------------------------------------------------

def _open(ts, sym="US.SPY", strat="orb", entry=100.0, stop=99.0, qty=10):
    return {"event": "position_open", "ts": ts, "symbol": sym, "strategy": strat,
            "entry": entry, "stop": stop, "qty": qty, "direction": "long"}


def _close(ts, sym="US.SPY", strat="orb", pnl=5.0, exit_=100.5):
    return {"event": "position_close", "ts": ts, "symbol": sym, "strategy": strat,
            "pnl": pnl, "exit": exit_, "reason": "TARGET", "hold_bars": 4}


def test_pairs_an_open_to_its_following_close():
    t = mmt.pair_trades([_open("2026-08-01T10:00:00"), _close("2026-08-01T10:20:00")])
    assert len(t) == 1
    assert t[0]["closed"] is True
    assert t[0]["pnl"] == 5.0


def test_a_close_before_the_open_is_not_matched():
    t = mmt.pair_trades([_open("2026-08-01T10:00:00"), _close("2026-08-01T09:00:00")])
    assert t[0]["closed"] is False
    assert t[0]["pnl"] is None


def test_net_is_strictly_worse_than_gross_for_a_winner():
    """Costs must reduce a win. If net >= gross the cost model isn't being applied."""
    t = mmt.pair_trades([_open("2026-08-01T10:00:00"), _close("2026-08-01T10:20:00")])[0]
    assert t["pnl_net"] < t["pnl"]
    assert t["bps_net"] < t["bps"]


def test_net_is_more_negative_than_gross_for_a_loser():
    """Costs are paid on losers too — they must not shrink a loss toward zero."""
    t = mmt.pair_trades([
        _open("2026-08-01T10:00:00"),
        _close("2026-08-01T10:20:00", pnl=-5.0),
    ])[0]
    assert t["pnl_net"] < t["pnl"] < 0


def test_cost_scales_with_notional_not_with_pnl():
    small = mmt.pair_trades([
        _open("2026-08-01T10:00:00", entry=10.0, qty=1),
        _close("2026-08-01T10:20:00"),
    ])[0]
    large = mmt.pair_trades([
        _open("2026-08-01T10:00:00", entry=1000.0, qty=100),
        _close("2026-08-01T10:20:00"),
    ])[0]
    assert (large["pnl"] - large["pnl_net"]) > (small["pnl"] - small["pnl_net"])


def test_deduplicates_fire_and_forget_repeats():
    """Pre-2026-06-10 logs wrote open/close once per poll cycle, not once per trade."""
    o, c = _open("2026-08-01T10:00:00"), _close("2026-08-01T10:20:00")
    assert len(mmt.pair_trades([o, dict(o), dict(o), c, dict(c)])) == 1


def test_different_strategies_on_one_symbol_do_not_cross_pair():
    t = mmt.pair_trades([
        _open("2026-08-01T10:00:00", strat="orb"),
        _open("2026-08-01T10:01:00", strat="vwap_pb"),
        _close("2026-08-01T10:20:00", strat="vwap_pb", pnl=3.0),
    ])
    by = {x["strategy"]: x for x in t}
    assert by["vwap_pb"]["pnl"] == 3.0
    assert by["orb"]["closed"] is False


# ---------------------------------------------------------------------------
# No ninth profit factor
# ---------------------------------------------------------------------------

def test_reexports_canonical_profit_factor_not_a_copy():
    """Seven reimplementations of this metric have been written and caught in this
    repo. mm/trades.py must re-export, never redefine.

    Identity (`is`) is the obvious assertion but is wrong here: other tests reload
    mm.config/mm.backtest to exercise the module-ref pattern, after which a re-export
    bound at import time is a different object from a freshly imported one while being
    exactly as correct. Checking provenance catches a local redefinition — the thing
    that actually matters — without failing on reload order."""
    assert mmt.profit_factor.__module__ == "mm.backtest"
    assert mmt.profit_factor.__qualname__ == "profit_factor"


def test_module_defines_no_local_profit_factor():
    src = Path("mm/trades.py").read_text()
    assert "def profit_factor" not in src


def test_summarize_costs_reports_both_rulers():
    t = mmt.pair_trades([
        _open("2026-08-01T10:00:00"), _close("2026-08-01T10:20:00", pnl=5.0),
        _open("2026-08-02T10:00:00"), _close("2026-08-02T10:20:00", pnl=-2.0),
    ])
    s = mmt.summarize_costs(t)
    assert s["trades"] == 2 and s["wins"] == 1
    assert s["net_pnl"] < s["gross_pnl"]
    assert s["net_pf"] < s["gross_pf"]


# ---------------------------------------------------------------------------
# The pre-confirmed-fill cutoff
# ---------------------------------------------------------------------------

def test_cutoff_excludes_the_fire_and_forget_era(tmp_path):
    for day, pnl in (("2026-06-09", 100.0), ("2026-06-11", 1.0)):
        (tmp_path / f"paper_US_SPY_{day}.jsonl").write_text(
            json.dumps(_open(f"{day}T10:00:00")) + "\n"
            + json.dumps(_close(f"{day}T10:20:00", pnl=pnl)) + "\n"
        )
    kept = mmt.load_trades(tmp_path)
    assert [t["pnl"] for t in kept] == [1.0], "pre-2026-06-10 logs must be excluded"
    assert len(mmt.load_trades(tmp_path, default_start=None)) == 2


def test_explicit_start_overrides_the_default_cutoff(tmp_path):
    for day in ("2026-06-11", "2026-07-01"):
        (tmp_path / f"paper_US_SPY_{day}.jsonl").write_text(
            json.dumps(_open(f"{day}T10:00:00")) + "\n"
            + json.dumps(_close(f"{day}T10:20:00")) + "\n"
        )
    assert len(mmt.load_trades(tmp_path, start="2026-07-01")) == 1


# ---------------------------------------------------------------------------
# The reporters must not diverge again
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not list(LOGS.glob("paper_*_????-??-??.jsonl")),
                    reason="no live logs on disk")
def test_dashboard_and_analyze_trades_report_identical_numbers():
    """The whole point of mm/trades.py. If these ever disagree again, the project is
    back to publishing two contradictory sets of numbers for the same trades."""
    import sys
    sys.path.insert(0, "scripts")
    import analyze_trades as at
    import web_dashboard as wd

    at_trades = [t for t in at._pair_trades(at._load_jsonl(
        at._find_logs(LOGS, None, None, True, mmt.LIVE_LOGS_START)))
        if t["closed"]]

    with wd.app.test_request_context():
        rows = wd.api_scoreboard().get_json()

    assert sum(r["trades"] for r in rows) == len(at_trades)
    assert round(sum(r["gross_pnl"] for r in rows), 2) == round(
        sum(t["pnl"] for t in at_trades), 2)
    assert round(sum(r["net_pnl"] for r in rows), 2) == round(
        sum(t["pnl_net"] for t in at_trades), 2)


@pytest.mark.skipif(not list(LOGS.glob("paper_*_????-??-??.jsonl")),
                    reason="no live logs on disk")
def test_scoreboard_flags_zero_edge_strategies():
    """Every live strategy's net-PF CI currently contains 1.0. The dashboard must say
    so rather than presenting the point estimate as a result."""
    import sys
    sys.path.insert(0, "scripts")
    import web_dashboard as wd

    with wd.app.test_request_context():
        rows = wd.api_scoreboard().get_json()
    assert rows, "expected live strategies in the logs"
    for r in rows:
        if r["ci_lo"] is not None:
            expected = r["ci_lo"] <= 1.0 <= (r["ci_hi"] if r["ci_hi"] is not None
                                             else float("inf"))
            assert r["inconclusive"] is expected


@pytest.mark.skipif(not list(LOGS.glob("paper_*_????-??-??.jsonl")),
                    reason="no live logs on disk")
def test_scoreboard_emits_json_safe_numbers():
    """inf is not valid JSON — an infinite PF must serialize as null, not NaN."""
    import sys
    sys.path.insert(0, "scripts")
    import web_dashboard as wd

    with wd.app.test_request_context():
        payload = wd.api_scoreboard().get_data(as_text=True)
    assert "Infinity" not in payload and "NaN" not in payload
    json.loads(payload)


# ---------------------------------------------------------------------------
# Endpoint smoke tests
# ---------------------------------------------------------------------------

def _client():
    import sys
    sys.path.insert(0, "scripts")
    import web_dashboard as wd
    wd.app.config["TESTING"] = True
    c = wd.app.test_client()
    with c.session_transaction() as s:
        s["authed"] = True
        s["logged_in"] = True
    return c


@pytest.mark.parametrize("endpoint", [
    "/api/scoreboard",
    "/api/trades?limit=5",
    "/api/pnl_history",
    "/api/today_summary",
])
def test_reporting_endpoints_respond(endpoint):
    """Regression: while adding the cost columns, two module-level helpers were
    inserted between `@app.route("/api/scoreboard")` and its function, so the route
    decorated a helper and the endpoint raised TypeError on every request. The page
    itself still rendered 200, so nothing else would have caught it."""
    r = _client().get(endpoint)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    json.loads(r.get_data(as_text=True))


def test_trade_rows_carry_both_gross_and_net():
    rows = _client().get("/api/trades?limit=5").get_json()
    if not rows:
        pytest.skip("no closed trades on disk")
    for r in rows:
        assert "pnl" in r and "pnl_net" in r and "bps_net" in r


def test_today_summary_carries_net_alongside_gross():
    d = _client().get("/api/today_summary").get_json()
    for k in ("pnl", "pnl_net", "pf", "net_pf"):
        assert k in d
