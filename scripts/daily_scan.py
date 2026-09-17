#!/usr/bin/env python3
"""Route 3 daily-horizon scan (docs/evaluation_criteria.md, "Route 3", frozen 2026-09-17).

    python scripts/daily_scan.py dev        # 2022-01-03 → 2026-08-31, writes docs/route3/
    python scripts/daily_scan.py holdout    # 2019–2021; refuses unless finalists.json is committed

Daily bars are cached in logs/route3/daily.pkl (built once from logs/wide_scan/).
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from mm import daily_scan as ds  # noqa: E402
from mm import scan  # noqa: E402
from mm.costs import round_trip_bps  # noqa: E402
from wide_scan import _clean, _git_committed_clean, _symbols  # noqa: E402

OUT = ROOT / "docs" / "route3"
FINALISTS = OUT / "finalists.json"
CACHE = ROOT / "logs" / "route3" / "daily.pkl"
STRESS_BPS = scan.SLIPPAGE_STRESS_BPS


def load_panel(data_dir: Path) -> dict:
    if CACHE.exists():
        return pickle.loads(CACHE.read_bytes())
    syms = _symbols(data_dir, None)
    panel = {}
    for i, (s, v) in enumerate(syms.items(), 1):
        if v["exists"]:
            panel[s] = {"daily": ds.build_daily(v["path"]), "asset_class": v["asset_class"]}
            print(f"[{i}/{len(syms)}] {s}: {len(panel[s]['daily'])} sessions", file=sys.stderr)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(pickle.dumps(panel))
    return panel


def per_symbol_rows(d, sym, strat):
    cost = round_trip_bps(sym)
    if strat == "R3-ON":
        return ds.overnight_rows(d, cost)
    w = ds.trend_exposure(d) if strat == "R3-TREND" else ds.vol_exposure(d)
    return ds.timing_rows(d, w, cost)


def run_window(panel, start, end, only=None, lanes_wanted=None):
    """Return pooled + per-lane results for one window."""
    pooled, lanes, desc = {}, {}, {}
    wins = {s: ds.window(v["daily"], start, end) for s, v in panel.items()}
    for strat in ds.PER_SYMBOL:
        if only is not None and strat not in only and not any(
                k.endswith("|" + strat) for k in (lanes_wanted or [])):
            continue
        frames, sharpe_s, sharpe_b, dd_s, dd_b, expo = [], [], [], [], [], []
        for sym, d in wins.items():
            rows = per_symbol_rows(d, sym, strat)
            if rows.empty:
                continue
            rows = rows.assign(symbol=sym)
            frames.append(rows)
            key = f"{sym}|{strat}"
            if lanes_wanted is None or key in lanes_wanted:
                keys = rows["date"].tolist()
                lanes[key] = {**ds.stat(rows["net_bps"], keys),
                              "stressed": ds.stat(rows["net_bps"], keys,
                                                  rows["turnover"] * STRESS_BPS / 2
                                                  if strat != "R3-ON" else
                                                  [STRESS_BPS] * len(rows)),
                              "mean_gross_bps": float(rows["gross_bps"].mean()),
                              "asset_class": panel[sym]["asset_class"]}
            if strat != "R3-ON":
                strat_bps = (rows["w"] * rows["r"] * 1e4
                             - rows["turnover"] * round_trip_bps(sym) / 2)
                a, b = ds.sharpe_and_dd(strat_bps), ds.sharpe_and_dd(rows["r"] * 1e4)
                sharpe_s.append(a["sharpe"]), sharpe_b.append(b["sharpe"])
                dd_s.append(a["max_dd_pct"]), dd_b.append(b["max_dd_pct"])
                expo.append(float(rows["w"].mean()))
        if only is not None and strat not in only:
            continue
        allr = __import__("pandas").concat(frames, ignore_index=True)
        keys = allr["date"].tolist()
        extra = (allr["turnover"] * STRESS_BPS / 2 if strat != "R3-ON"
                 else [STRESS_BPS] * len(allr))
        pooled[strat] = {**ds.stat(allr["net_bps"], keys),
                         "stressed": ds.stat(allr["net_bps"], keys, extra),
                         "mean_gross_bps": float(allr["gross_bps"].mean()),
                         "symbols": int(allr["symbol"].nunique())}
        if strat != "R3-ON":
            med = lambda xs: sorted(x for x in xs if x is not None)[len(xs) // 2]  # noqa: E731
            desc[strat] = {"median_sharpe": med(sharpe_s), "median_bh_sharpe": med(sharpe_b),
                           "median_max_dd_pct": med(dd_s), "median_bh_max_dd_pct": med(dd_b),
                           "median_exposure": med(expo)}

    dailies = {s: d for s, d in wins.items() if len(d)}
    costs = {s: round_trip_bps(s) for s in dailies}
    for strat, look, high in (("R3-MOM", ds.MOM_LOOKBACK, True),
                              ("R3-REV", ds.REV_LOOKBACK, False)):
        if only is not None and strat not in only:
            continue
        rows = ds.xsec_rows(dailies, costs, look, high)
        keys = ds.week_keys(rows["date"])
        extra = rows["turnover"] * STRESS_BPS  # a full rebalance is ~one round trip
        pooled[strat] = {**ds.stat(rows["net_bps"], keys),
                         "stressed": ds.stat(rows["net_bps"], keys, extra),
                         "mean_gross_bps": float(rows["gross_bps"].mean()),
                         "first_day": str(rows["date"].iloc[0])}
        desc[strat] = {"portfolio": ds.sharpe_and_dd(rows["port_bps"]),
                       "equal_weight": ds.sharpe_and_dd(rows["bench_bps"])}
    return pooled, lanes, desc


def cmd_dev(args):
    panel = load_panel(args.data_dir)
    pooled, lanes, desc = run_window(panel, scan.DEV_START, scan.DEV_END)
    for st in pooled.values():
        st["passes_dev"] = st["p_one_sided"] < ds.PRIMARY_ALPHA and st["mean_bps"] > 0
    pvals = {k: (v["p_one_sided"] if v["n"] >= ds.MIN_LANE_OBS else 1.0)
             for k, v in lanes.items()}
    survivors = scan.benjamini_hochberg(pvals, scan.BH_Q)
    finalists = sorted(survivors, key=lambda k: lanes[k]["ci"][0], reverse=True)[:10]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dev_results.json").write_text(json.dumps(_clean({
        "window": [scan.DEV_START, scan.DEV_END], "symbols": len(panel),
        "pooled": pooled, "descriptive": desc, "bh_survivors": sorted(survivors),
        "finalists": finalists, "lanes": lanes}), indent=1) + "\n")
    FINALISTS.write_text(json.dumps({
        "rule": "evaluation_criteria.md Route 3 (2026-09-17)",
        "pooled_passing_dev": [s for s, v in pooled.items() if v["passes_dev"]],
        "finalists": finalists}, indent=1) + "\n")
    summary = {s: {k: v[k] for k in ("n", "mean_bps", "ci", "p_one_sided", "passes_dev",
                                     "mean_gross_bps")} for s, v in pooled.items()}
    print(json.dumps(_clean({"pooled": summary, "descriptive": desc,
                             "bh_survivors": len(survivors), "finalists": finalists}), indent=1))


def cmd_holdout(args):
    if not FINALISTS.exists() or not _git_committed_clean(FINALISTS):
        raise SystemExit(f"refusing: {FINALISTS} must be committed unmodified first")
    spec = json.loads(FINALISTS.read_text())
    only = set(spec["pooled_passing_dev"])
    if not only and not spec["finalists"]:
        print("nothing passed dev — holdout stays unspent (a null result).")
        return
    panel = load_panel(args.data_dir)
    pooled, lanes, desc = run_window(panel, scan.HOLDOUT_START, scan.HOLDOUT_END,
                                     only=only, lanes_wanted=set(spec["finalists"]))
    k = max(len(spec["finalists"]), 1)
    verdict = {}
    for name, st, alpha in ([(s, pooled[s], ds.PRIMARY_ALPHA) for s in only]
                            + [(f, lanes.get(f, {"n": 0}), 0.05 / k)
                               for f in spec["finalists"]]):
        if st.get("n", 0) < 20:
            verdict[name] = "not_testable"
        else:
            ok = (st["p_one_sided"] < alpha and st["mean_bps"] > 0
                  and st["stressed"]["mean_bps"] > 0)
            verdict[name] = "replicated" if ok else "not_replicated"
    (OUT / "holdout_results.json").write_text(json.dumps(_clean({
        "window": [scan.HOLDOUT_START, scan.HOLDOUT_END], "verdicts": verdict,
        "pooled": pooled, "lanes": lanes, "descriptive": desc}), indent=1) + "\n")
    print(json.dumps(_clean({"verdicts": verdict, "pooled": pooled, "descriptive": desc}),
                     indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["dev", "holdout"])
    ap.add_argument("--data-dir", type=Path, default=ROOT / "logs" / "wide_scan")
    args = ap.parse_args()
    (cmd_dev if args.phase == "dev" else cmd_holdout)(args)


if __name__ == "__main__":
    main()
