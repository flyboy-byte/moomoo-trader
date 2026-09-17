"""Quota-safe bulk history fetch for the wide scan (PLAN.md Step 9).

OpenD's history quota is 100 distinct symbols per rolling 30 days, so a symbol
pulled today holds its slot for a month. This module keeps the fetch from ever
spending a slot it did not mean to:

  * Throttle      — spaces page requests (Futu documents ~30 requests / 30 s).
  * Ledger        — append-only JSONL record of every attempt, success, and
                    reserve substitution; the resume point after any crash.
  * plan_fetch    — refuses to start if the remaining slots (minus a margin)
                    cannot cover every symbol that still needs a paid pull.
  * run_fetch     — fetches one symbol at a time, all-or-nothing, checks after
                    each paid pull that exactly one slot was spent, and swaps in
                    an ordered reserve only when a symbol is genuinely unavailable.

Nothing here talks to OpenD directly: the caller passes `fetch`, `save`, and
`quota` callables, which is what makes it testable without spending anything.
"""
from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

QUOTA_MARGIN = 3              # never plan to leave fewer free slots than this
MIN_REQUEST_INTERVAL_S = 1.1  # ≤ ~27 page requests per 30 s
TRANSIENT_RETRIES = 3
UNAVAILABLE_MARKERS = ("unknown stock", "not found", "no data", "does not exist", "invalid")


class QuotaRefused(RuntimeError):
    """The run would spend more slots than are safely available."""


class QuotaAnomaly(RuntimeError):
    """A pull spent a different number of slots than expected."""


class Throttle:
    def __init__(self, min_interval: float = MIN_REQUEST_INTERVAL_S,
                 sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.min_interval = min_interval
        self._sleep = sleep
        self._monotonic = monotonic
        self._last: float | None = None

    def __call__(self) -> None:
        now = self._monotonic()
        if self._last is not None:
            wait = self._last + self.min_interval - now
            if wait > 0:
                self._sleep(wait)
        self._last = self._monotonic()


@dataclass
class Quota:
    used: int
    remaining: int
    used_codes: set[str] = field(default_factory=set)


@dataclass
class Target:
    slot: int
    symbol: str
    asset_class: str
    status: str  # primary | reserve


def load_universe(path: Path) -> tuple[list[Target], list[Target]]:
    with open(path, newline="") as f:
        rows = [Target(int(r["slot"]), r["symbol"], r["asset_class"], r["status"])
                for r in csv.DictReader(f)]
    rows.sort(key=lambda t: t.slot)
    return ([t for t in rows if t.status == "primary"],
            [t for t in rows if t.status == "reserve"])


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def append(self, **record) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **record}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def done(self) -> set[str]:
        return {r["symbol"] for r in self.records() if r.get("event") == "done"}

    def unavailable(self) -> set[str]:
        return {r["symbol"] for r in self.records() if r.get("event") == "unavailable"}

    def substitutions(self) -> dict[str, str]:
        return {r["primary"]: r["symbol"] for r in self.records()
                if r.get("event") == "substitute"}


def resolve_targets(primaries: list[Target], reserves: list[Target],
                    ledger: Ledger) -> list[Target]:
    """Primaries, with any substitution already recorded in the ledger applied."""
    subs = ledger.substitutions()
    by_symbol = {t.symbol: t for t in reserves}
    return [by_symbol[subs[t.symbol]] if t.symbol in subs else t for t in primaries]


def plan_fetch(targets: list[Target], ledger: Ledger, quota: Quota,
               margin: int = QUOTA_MARGIN) -> tuple[list[Target], int]:
    """Return (still-to-fetch, slots that will be spent). Raise if unsafe."""
    done = ledger.done()
    todo = [t for t in targets if t.symbol not in done]
    cost = sum(1 for t in todo if t.symbol not in quota.used_codes)
    if cost > quota.remaining - margin:
        raise QuotaRefused(
            f"needs {cost} new slots but only {quota.remaining} remain "
            f"(keeping {margin} spare) — refusing to start")
    return todo, cost


def _is_unavailable(err: Exception) -> bool:
    return any(m in str(err).lower() for m in UNAVAILABLE_MARKERS)


def run_fetch(
    targets: list[Target],
    reserves: list[Target],
    ledger: Ledger,
    fetch: Callable[[str], "object"],
    save: Callable[[str, "object"], int],
    quota: Callable[[], Quota],
    margin: int = QUOTA_MARGIN,
    limit: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> dict:
    """Fetch every target not already done. Returns a summary dict.

    fetch(symbol) returns a DataFrame-like object with len(); raises on error.
    save(symbol, df) persists it and returns the row count on disk.
    """
    q = quota()
    todo, cost = plan_fetch(targets, ledger, q, margin)
    log(f"plan: {len(todo)} symbols to fetch, {cost} new slots, {q.remaining} free")
    used_reserves = set(ledger.substitutions().values()) | ledger.unavailable()
    queue = list(todo)
    fetched = paid = 0

    while queue:
        if limit is not None and fetched >= limit:
            break
        t = queue.pop(0)
        before = quota()
        paying = t.symbol not in before.used_codes
        if paying and before.remaining - 1 < margin:
            raise QuotaRefused(f"{t.symbol}: would leave fewer than {margin} free slots")

        df, err = None, None
        for attempt in range(TRANSIENT_RETRIES):
            try:
                df = fetch(t.symbol)
                err = None
                break
            except Exception as e:  # noqa: BLE001 — classified below
                err = e
                if _is_unavailable(e):
                    break
                sleep(30 * (attempt + 1))

        after = quota()
        spent = after.used - before.used
        if not paying:
            expected = 0          # a slot this symbol already holds must stay free
        elif df is not None and len(df):
            expected = 1
        else:
            expected = None       # unavailable: spending 0 or 1 is both plausible
        if expected is not None and spent != expected:
            ledger.append(event="quota_anomaly", symbol=t.symbol, spent=spent,
                          before=before.used, after=after.used)
            raise QuotaAnomaly(f"{t.symbol}: spent {spent} slots, expected {expected}")

        if err is not None and not _is_unavailable(err):
            ledger.append(event="error", symbol=t.symbol, error=str(err), spent=spent)
            raise RuntimeError(f"{t.symbol}: giving up after {TRANSIENT_RETRIES} tries: {err}")

        if err is not None or df is None or not len(df):
            ledger.append(event="unavailable", symbol=t.symbol,
                          error=str(err) if err else "empty", spent=spent)
            # a reserve can itself be unavailable: record against the original primary
            origin = {v: k for k, v in ledger.substitutions().items()}.get(t.symbol, t.symbol)
            reserve = next((r for r in reserves if r.asset_class == t.asset_class
                            and r.symbol not in used_reserves), None)
            if reserve is None:
                log(f"{t.symbol}: unavailable, no {t.asset_class} reserve left")
                continue
            used_reserves.add(reserve.symbol)
            ledger.append(event="substitute", primary=origin, symbol=reserve.symbol)
            log(f"{t.symbol}: unavailable -> substituting reserve {reserve.symbol}")
            queue.insert(0, reserve)
            continue

        rows = save(t.symbol, df)
        paid += spent
        fetched += 1
        ledger.append(event="done", symbol=t.symbol, rows=rows, spent=spent,
                      quota_used=after.used)
        log(f"{t.symbol}: {rows} rows, spent {spent} slot(s), {after.remaining} free")

    return {"fetched": fetched, "slots_spent": paid, "remaining": len(queue)}
