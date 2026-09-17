"""Quota-safe bulk fetch (PLAN.md Step 9) — all behaviour pinned without OpenD."""
from pathlib import Path

import pytest

from mm.bulk_fetch import (Ledger, Quota, QuotaAnomaly, QuotaRefused, Target, Throttle,
                           load_universe, plan_fetch, resolve_targets, run_fetch)


class FakeOpenD:
    """Counts distinct symbols like the real 30-day history quota."""

    def __init__(self, total=100, used=(), unavailable=(), flaky=(), overspend=()):
        self.total = total
        self.codes = set(used)
        self.unavailable = set(unavailable)
        self.flaky = dict.fromkeys(flaky, 1)   # symbol -> failures left
        self.overspend = set(overspend)
        self.calls: list[str] = []

    def quota(self):
        return Quota(len(self.codes), self.total - len(self.codes), set(self.codes))

    def fetch(self, symbol):
        self.calls.append(symbol)
        if symbol in self.unavailable:
            raise RuntimeError(f"Unknown stock {symbol}")
        if self.flaky.get(symbol):
            self.flaky[symbol] -= 1
            raise RuntimeError("request too frequent")
        self.codes.add(symbol)
        if symbol in self.overspend:
            self.codes.add(symbol + "-ghost")
        return [1, 2, 3]


def _t(slot, sym, cls="etf", status="primary"):
    return Target(slot, sym, cls, status)


def _run(opend, targets, reserves, ledger, **kw):
    saved = {}
    out = run_fetch(targets, reserves, ledger, fetch=opend.fetch,
                    save=lambda s, df: saved.setdefault(s, len(df)),
                    quota=opend.quota, sleep=lambda s: None, log=lambda m: None, **kw)
    return out, saved


def test_throttle_spaces_requests():
    now = [0.0]
    slept = []
    th = Throttle(1.1, sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)),
                  monotonic=lambda: now[0])
    th(); th()
    now[0] += 5.0
    th()
    assert slept == [pytest.approx(1.1)]


def test_plan_refuses_when_slots_run_short(tmp_path):
    targets = [_t(i, f"US.S{i}") for i in range(10)]
    with pytest.raises(QuotaRefused):
        plan_fetch(targets, Ledger(tmp_path / "l.jsonl"), Quota(92, 8), margin=3)


def test_plan_counts_already_held_symbols_as_free(tmp_path):
    targets = [_t(1, "US.SPY"), _t(2, "US.AAA")]
    todo, cost = plan_fetch(targets, Ledger(tmp_path / "l.jsonl"),
                            Quota(3, 97, {"US.SPY"}))
    assert len(todo) == 2 and cost == 1


def test_full_run_then_rerun_is_a_no_op(tmp_path):
    opend = FakeOpenD(used={"US.SPY"})
    ledger = Ledger(tmp_path / "l.jsonl")
    targets = [_t(1, "US.SPY"), _t(2, "US.AAA"), _t(3, "US.BBB")]
    out, saved = _run(opend, targets, [], ledger)
    assert out == {"fetched": 3, "slots_spent": 2, "remaining": 0}
    assert len(opend.codes) == 3
    calls = len(opend.calls)
    out2, _ = _run(opend, targets, [], ledger)
    assert out2["fetched"] == 0 and len(opend.calls) == calls


def test_limit_then_resume(tmp_path):
    opend = FakeOpenD()
    ledger = Ledger(tmp_path / "l.jsonl")
    targets = [_t(i, f"US.S{i}") for i in range(5)]
    assert _run(opend, targets, [], ledger, limit=1)[0]["fetched"] == 1
    assert _run(opend, targets, [], ledger)[0]["fetched"] == 4
    assert opend.calls == [f"US.S{i}" for i in range(5)]


def test_unavailable_primary_gets_same_class_reserve(tmp_path):
    opend = FakeOpenD(unavailable={"US.BAD"})
    ledger = Ledger(tmp_path / "l.jsonl")
    targets = [_t(1, "US.BAD", "stock"), _t(2, "US.OK")]
    reserves = [_t(3, "US.RE", "etf", "reserve"), _t(4, "US.RS", "stock", "reserve")]
    out, saved = _run(opend, targets, reserves, ledger)
    assert set(saved) == {"US.RS", "US.OK"}
    assert ledger.substitutions() == {"US.BAD": "US.RS"}
    assert [t.symbol for t in resolve_targets(targets, reserves, ledger)] == ["US.RS", "US.OK"]


def test_transient_error_is_retried_not_substituted(tmp_path):
    opend = FakeOpenD(flaky={"US.AAA"})
    ledger = Ledger(tmp_path / "l.jsonl")
    out, saved = _run(opend, [_t(1, "US.AAA")], [_t(2, "US.R", status="reserve")], ledger)
    assert saved == {"US.AAA": 3} and ledger.substitutions() == {}


def test_persistent_error_stops_the_run(tmp_path):
    class Down(FakeOpenD):
        def fetch(self, symbol):
            raise RuntimeError("connection reset")
    ledger = Ledger(tmp_path / "l.jsonl")
    with pytest.raises(RuntimeError, match="giving up"):
        _run(Down(), [_t(1, "US.AAA"), _t(2, "US.BBB")], [], ledger)
    assert ledger.done() == set()


def test_unexpected_quota_spend_halts(tmp_path):
    opend = FakeOpenD(overspend={"US.AAA"})
    ledger = Ledger(tmp_path / "l.jsonl")
    with pytest.raises(QuotaAnomaly):
        _run(opend, [_t(1, "US.AAA"), _t(2, "US.BBB")], [], ledger)
    assert "US.BBB" not in opend.calls


def test_margin_is_enforced(tmp_path):
    opend = FakeOpenD(total=5)
    ledger = Ledger(tmp_path / "l.jsonl")
    with pytest.raises(QuotaRefused):
        _run(opend, [_t(i, f"US.S{i}") for i in range(3)], [], ledger, margin=3)


def test_real_universe_file_loads():
    path = Path("docs/wide_scan_universe.csv")
    primaries, reserves = load_universe(path)
    assert (len(primaries), len(reserves)) == (85, 12)
    assert primaries[0].symbol == "US.SPY"
