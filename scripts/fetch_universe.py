#!/usr/bin/env python3
"""PLAN.md Step 9: pull the frozen wide-scan universe, quota-safely. Runs where OpenD is (VPS).

Writes RTH five-minute QFQ candles to logs/wide_scan/<SYM>_K_5M_combined.csv, one full
pull per symbol so every file has a single price basis (Step 7), and records every
attempt in logs/wide_scan/quota_ledger.jsonl. Re-running resumes; finished symbols
cost nothing and are not re-requested. See mm/bulk_fetch.py for the safety rules.

Usage (on the VPS):
    python scripts/fetch_universe.py --dry-run        # quota + plan + code check, no history requests
    python scripts/fetch_universe.py --limit 1        # spend at most one new slot, then stop
    python scripts/fetch_universe.py                  # everything still to do
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from moomoo import RET_OK, Market, SecurityType  # noqa: E402

from mm import config as _config  # noqa: E402
from mm.bulk_fetch import (Ledger, Quota, Throttle, load_universe, plan_fetch,  # noqa: E402
                           resolve_targets, run_fetch)
from mm.connection import quote_context  # noqa: E402
from mm.data import fetch_candles, update_combined_csv  # noqa: E402

UNIVERSE = ROOT / "docs" / "wide_scan_universe.csv"
OUT_DIR = ROOT / "logs" / "wide_scan"
START, END = "2019-01-02", "2026-08-31"   # docs/evaluation_criteria.md, Step 6b


def read_quota() -> Quota:
    with quote_context() as ctx:
        ret, data = ctx.get_history_kl_quota(get_detail=True)
    if ret != RET_OK:
        raise RuntimeError(f"quota query failed: {data}")
    used, remaining, detail = data
    return Quota(int(used), int(remaining), {d["code"] for d in detail})


def unknown_codes(symbols: list[str]) -> list[str]:
    """Codes OpenD's static data does not recognise (no history quota used)."""
    known: set[str] = set()
    with quote_context() as ctx:
        for stype in (SecurityType.STOCK, SecurityType.ETF):
            ret, data = ctx.get_stock_basicinfo(Market.US, stype, code_list=symbols)
            if ret == RET_OK and len(data):
                known |= set(data["code"])
    return [s for s in symbols if s not in known]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, help="stop after this many symbols")
    args = ap.parse_args()

    _config.cfg.logs_dir = OUT_DIR       # update_combined_csv writes here, not logs/
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(OUT_DIR / "quota_ledger.jsonl")
    primaries, reserves = load_universe(UNIVERSE)
    targets = resolve_targets(primaries, reserves, ledger)

    q = read_quota()
    print(f"quota: {q.used} used, {q.remaining} free; held: {sorted(q.used_codes)}")
    if args.dry_run:
        todo, cost = plan_fetch(targets, ledger, q)
        print(f"plan: {len(todo)} to fetch, {cost} new slots, {q.remaining - cost} left after")
        bad = unknown_codes([t.symbol for t in primaries + reserves])
        print(f"codes OpenD does not recognise: {bad or 'none'}")
        return

    throttle = Throttle()

    def fetch(symbol: str):
        return fetch_candles(symbol, ktype="K_5M", start=START, end=END,
                             strict=True, before_request=throttle)

    def save(symbol: str, df) -> int:
        path = update_combined_csv(df, symbol, "K_5M")
        return sum(1 for _ in open(path)) - 1

    summary = run_fetch(targets, reserves, ledger, fetch=fetch, save=save,
                        quota=read_quota, limit=args.limit)
    print(f"summary: {summary}")


if __name__ == "__main__":
    main()
