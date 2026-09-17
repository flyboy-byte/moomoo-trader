#!/usr/bin/env python3
"""PLAN.md Step 11: the wide scan, under the rules frozen in evaluation_criteria.md (Step 6).

Two phases, deliberately separate commands:

  dev      Development window 2022-01-03 → 2026-08-31. Every lane, the four pooled
           strategy tests, BH selection, finalists. Writes docs/wide_scan/dev_*.
  holdout  Sealed window 2019-01-02 → 2021-12-31. REFUSES to run unless
           docs/wide_scan/finalists.json is committed and unmodified in git, and
           then evaluates only the pooled strategies that passed dev and the
           committed finalists.

Parameters come only from docs/wide_scan_params_2026-09-17.env (never the local .env).
Candles come from the Step 9 pull (default logs/wide_scan/, synced from the VPS).

Usage:
    python scripts/wide_scan.py dev [--workers 10] [--symbols US.SPY,US.QQQ]
    python scripts/wide_scan.py holdout
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mm import scan  # noqa: E402  (mm.scan does not import mm.config at module load)

PARAMS = ROOT / "docs" / "wide_scan_params_2026-09-17.env"
OUT = ROOT / "docs" / "wide_scan"
FINALISTS = OUT / "finalists.json"


def _worker_init() -> None:
    scan.pin_config(PARAMS)
    import logging
    logging.disable(logging.INFO)


def _scan_symbol(args: tuple[str, str, str, str, list[str] | None]) -> tuple[str, list[dict], dict]:
    sym, csv_path, start, end, only = args
    import pandas as pd
    warm = (datetime.fromisoformat(start) - timedelta(days=scan.WARMUP_DAYS)).strftime("%Y-%m-%d")
    df = pd.read_csv(csv_path, usecols=["time_key", "open", "high", "low", "close", "volume"])
    days = df["time_key"].str[:10]
    df = df[(days >= warm) & (days <= end)].reset_index(drop=True)
    df["time_key"] = pd.to_datetime(df["time_key"])
    if df.empty:
        return sym, [], {"return_pct": None, "days": 0}
    rows: list[dict] = []
    for strat, trades in scan.run_engines(sym, df).items():
        if only is None or strat in only:
            rows += scan.trade_rows(sym, strat, trades, start, end)
    return sym, rows, scan.buy_and_hold(df, start, end)


def _symbols(data_dir: Path, wanted: list[str] | None) -> dict[str, dict]:
    from mm.bulk_fetch import Ledger, load_universe, resolve_targets
    primaries, reserves = load_universe(ROOT / "docs" / "wide_scan_universe.csv")
    targets = resolve_targets(primaries, reserves, Ledger(data_dir / "quota_ledger.jsonl"))
    out = {}
    for t in targets:
        if wanted and t.symbol not in wanted:
            continue
        path = data_dir / f"{t.symbol.replace('.', '_')}_K_5M_combined.csv"
        out[t.symbol] = {"path": path, "asset_class": t.asset_class, "exists": path.exists()}
    return out


def _run(jobs, workers):
    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init) as ex:
        yield from ex.map(_scan_symbol, jobs)


def _clean(obj):
    if isinstance(obj, float) and not math.isfinite(obj):
        return None if obj != obj else ("Infinity" if obj > 0 else "-Infinity")
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _git_committed_clean(path: Path) -> bool:
    rel = str(path.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT,
                             capture_output=True).returncode == 0
    dirty = subprocess.run(["git", "status", "--porcelain", rel], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    return tracked and not dirty


def cmd_dev(args) -> None:
    syms = _symbols(args.data_dir, args.symbols)
    missing = [s for s, v in syms.items() if not v["exists"]]
    if missing and not args.allow_missing:
        raise SystemExit(f"missing candle files for {len(missing)} symbols: {missing[:8]}…")
    present = {s: v for s, v in syms.items() if v["exists"]}
    # Partial runs are trials: they never write the committed results or finalist file.
    trial = bool(args.symbols or missing)
    out = args.data_dir / "trial" if trial else OUT
    fin = out / "finalists.json"
    jobs = [(s, str(v["path"]), scan.DEV_START, scan.DEV_END, None) for s, v in present.items()]

    all_rows: list[dict] = []
    bnh: dict[str, dict] = {}
    for i, (sym, rows, bh) in enumerate(_run(jobs, args.workers), 1):
        all_rows += rows
        bnh[sym] = bh
        print(f"[{i}/{len(jobs)}] {sym}: {len(rows)} trades", file=sys.stderr)

    lanes: dict[str, dict] = {}
    for sym in present:
        for strat in scan.STRATEGIES:
            rows = [r for r in all_rows if r["symbol"] == sym and r["strategy"] == strat]
            lanes[f"{sym}|{strat}"] = {**scan.lane_stats(rows),
                                      "asset_class": present[sym]["asset_class"]}

    pooled = {}
    for strat in scan.STRATEGIES:
        st = scan.lane_stats([r for r in all_rows if r["strategy"] == strat])
        st["passes_dev"] = st["n"] > 0 and st["p_one_sided"] < scan.POOLED_ALPHA \
            and st["mean_net_bps"] > 0
        by_class = {}
        for cls in ("etf", "stock"):
            vals = [v for k, v in lanes.items()
                    if k.endswith("|" + strat) and v["asset_class"] == cls and v["n"]]
            if vals:
                med = lambda key: sorted(x[key] for x in vals)[len(vals) // 2]  # noqa: E731
                by_class[cls] = {"lanes": len(vals), "median_gross_bps": med("mean_gross_bps"),
                                 "median_cost_bps": med("mean_cost_bps"),
                                 "median_net_bps": med("mean_net_bps")}
        st["by_asset_class"] = by_class
        pooled[strat] = st

    finalists = scan.select_finalists(lanes)
    pvals = {k: (v["p_one_sided"] if v["n"] >= scan.MIN_DEV_TRADES else 1.0)
             for k, v in lanes.items()}
    bh_survivors = sorted(scan.benjamini_hochberg(pvals))
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out.mkdir(parents=True, exist_ok=True)
    (out / "dev_results.json").write_text(json.dumps(_clean({
        "generated": stamp, "window": [scan.DEV_START, scan.DEV_END],
        "params": str(PARAMS.relative_to(ROOT)), "symbols": len(present),
        "missing": missing, "trades": len(all_rows), "pooled": pooled,
        "bh_survivors": bh_survivors, "finalists": finalists,
        "lanes": lanes, "buy_and_hold": bnh}), indent=1) + "\n")
    fin.write_text(json.dumps({
        "generated": stamp, "trial": trial, "rule": "evaluation_criteria.md 2026-09-17 Step 6c",
        "pooled_passing_dev": [s for s, v in pooled.items() if v["passes_dev"]],
        "finalists": finalists}, indent=1) + "\n")
    print(json.dumps(_clean({"pooled": {s: {k: v[k] for k in
          ("n", "net_pf", "mean_net_bps", "net_bps_ci", "p_one_sided", "passes_dev")}
          for s, v in pooled.items()}, "bh_survivors": len(bh_survivors),
          "finalists": finalists}), indent=1))
    print(f"\nwrote {out / 'dev_results.json'} and {fin}"
          + (" (TRIAL — not the preregistered run)" if trial
             else f". Commit {fin.name} before running the holdout."), file=sys.stderr)


def cmd_holdout(args) -> None:
    if not FINALISTS.exists() or not _git_committed_clean(FINALISTS):
        raise SystemExit(f"refusing: {FINALISTS} must exist and be committed unmodified "
                         "before the sealed holdout is computed")
    spec = json.loads(FINALISTS.read_text())
    pooled_names = spec["pooled_passing_dev"]
    finalists = spec["finalists"]
    wanted = sorted({k.split("|")[0] for k in finalists}) if not pooled_names else None
    syms = _symbols(args.data_dir, wanted)
    only = sorted(set(pooled_names) | {k.split("|")[1] for k in finalists})
    if not only:
        print("nothing passed dev — holdout has nothing to test (a null result).")
        return
    jobs = [(s, str(v["path"]), scan.HOLDOUT_START, scan.HOLDOUT_END, only)
            for s, v in syms.items() if v["exists"]]
    all_rows: list[dict] = []
    for sym, rows, _ in _run(jobs, args.workers):
        all_rows += rows

    results = {"pooled": {}, "finalists": {}}
    for strat in pooled_names:
        rows = [r for r in all_rows if r["strategy"] == strat]
        plain, stressed = scan.lane_stats(rows), scan.lane_stats(rows, scan.SLIPPAGE_STRESS_BPS)
        results["pooled"][strat] = {"plain": plain, "stressed": stressed,
                                    "verdict": scan.holdout_verdict(plain, stressed,
                                                                    scan.POOLED_ALPHA)}
    alpha = scan.FINALIST_ALPHA / max(len(finalists), 1)
    for key in finalists:
        sym, strat = key.split("|")
        rows = [r for r in all_rows if r["symbol"] == sym and r["strategy"] == strat]
        plain, stressed = scan.lane_stats(rows), scan.lane_stats(rows, scan.SLIPPAGE_STRESS_BPS)
        results["finalists"][key] = {"plain": plain, "stressed": stressed,
                                     "verdict": scan.holdout_verdict(plain, stressed, alpha)}
    (OUT / "holdout_results.json").write_text(json.dumps(_clean({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": [scan.HOLDOUT_START, scan.HOLDOUT_END], **results}), indent=1) + "\n")
    for group in ("pooled", "finalists"):
        for k, v in results[group].items():
            print(f"{group:9s} {k:28s} n={v['plain']['n']:5d} "
                  f"net_bps={v['plain'].get('mean_net_bps', float('nan')):+.2f} -> {v['verdict']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["dev", "holdout"])
    ap.add_argument("--data-dir", type=Path, default=ROOT / "logs" / "wide_scan")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--symbols", type=lambda s: [x.strip() for x in s.split(",")])
    ap.add_argument("--allow-missing", action="store_true",
                    help="scan whatever symbols are on disk (for trial runs only)")
    args = ap.parse_args()
    (cmd_dev if args.phase == "dev" else cmd_holdout)(args)


if __name__ == "__main__":
    main()
