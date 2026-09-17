#!/usr/bin/env python3
"""Crypto pilot (docs/evaluation_criteria.md § "Crypto pilot (C)", frozen 2026-09-17).

    python scripts/crypto_scan.py fetch      # Binance archive → logs/crypto/ (no key needed)
    python scripts/crypto_scan.py dev        # 2018–2022 → docs/crypto/dev_results.json
    python scripts/crypto_scan.py holdout    # 2023–2026-08; refuses unless finalists committed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from mm import crypto as cx  # noqa: E402
from mm import daily_scan as ds  # noqa: E402
from mm import scan  # noqa: E402
from wide_scan import _clean, _git_committed_clean  # noqa: E402

DATA = ROOT / "logs" / "crypto"
OUT = ROOT / "docs" / "crypto"
FINALISTS = OUT / "finalists.json"


def _daily_path(coin):
    return DATA / "daily" / f"{coin['binance']}_1d.csv"


def cmd_fetch(_):
    coins = cx.load_universe()
    for i, (name, c) in enumerate(coins.items(), 1):
        cx.fetch_klines(c["binance"], "1d", c["binance_first_month"], "2026-08", _daily_path(c))
        print(f"[{i}/{len(coins)}] {name}", file=sys.stderr)
    for sym in ("BTCUSDT", "ETHUSDT"):
        cx.fetch_klines(sym, "1h", "2018-01", "2022-12", DATA / "hourly" / f"{sym}_1h.csv")
        print(f"hourly {sym}", file=sys.stderr)


def _panel():
    coins = cx.load_universe()
    return coins, {n: cx.daily_frame(_daily_path(c)) for n, c in coins.items()}


def run(start, end, fee_bps, lanes_wanted=None):
    coins, panel = _panel()
    costs = {n: 2 * fee_bps + c["alpaca_spread_bps"] for n, c in coins.items()}
    frames, lanes, sharpe = [], {}, {}
    for n, d in panel.items():
        rows = cx.trend_rows(d, costs[n], start, end)
        if rows.empty:
            continue
        frames.append(rows.assign(coin=n))
        if lanes_wanted is None or n in lanes_wanted:
            lanes[n] = {**ds.stat(rows["net_bps"], rows["date"].tolist()),
                        "mean_gross_bps": float(rows["gross_bps"].mean()),
                        "exposure": float(rows["w"].mean())}
        strat = rows["w"] * rows["r"] * 1e4 - rows["turnover"] * costs[n] / 2
        sharpe[n] = {"trend": ds.sharpe_and_dd(strat), "hold": ds.sharpe_and_dd(rows["r"] * 1e4)}
    allr = pd.concat(frames, ignore_index=True)
    c1 = {**ds.stat(allr["net_bps"], allr["date"].tolist()),
          "mean_gross_bps": float(allr["gross_bps"].mean()), "coins": int(allr["coin"].nunique())}
    xr = cx.xmom_rows(panel, costs, start, end)
    c2 = {**ds.stat(xr["net_bps"], ds.week_keys(xr["date"])),
          "mean_gross_bps": float(xr["gross_bps"].mean()), "first_day": xr["date"].iloc[0],
          "portfolio": ds.sharpe_and_dd(xr["port_bps"]),
          "equal_weight": ds.sharpe_and_dd(xr["bench_bps"])}
    return {"C1-TREND": c1, "C2-XMOM": c2}, lanes, sharpe, panel


def cmd_dev(_):
    pooled, lanes, sharpe, panel = run(cx.DEV_START, cx.DEV_END, cx.TAKER_BPS)
    maker, _, _, _ = run(cx.DEV_START, cx.DEV_END, cx.MAKER_BPS, lanes_wanted=set())
    for st in pooled.values():
        st["passes_dev"] = st["p_one_sided"] < cx.PRIMARY_ALPHA and st["mean_bps"] > 0
    pvals = {k: (v["p_one_sided"] if v["n"] >= cx.MIN_DEV_DAYS else 1.0) for k, v in lanes.items()}
    surv = scan.benjamini_hochberg(pvals, scan.BH_Q)
    finalists = sorted(surv, key=lambda k: lanes[k]["ci"][0], reverse=True)[:cx.FINALIST_CAP]
    diag = {"open_close_gap_bps_median": {n: round(cx.open_close_gap_bps(d), 3)
                                          for n, d in panel.items() if len(d)},
            "maker_fee_mean_bps": {k: v["mean_bps"] for k, v in maker.items()},
            "seasonality": {s: cx.seasonality(DATA / "hourly" / f"{s}_1h.csv",
                                              cx.DEV_START, cx.DEV_END)
                            for s in ("BTCUSDT", "ETHUSDT")},
            "per_coin_sharpe_dd": sharpe}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dev_results.json").write_text(json.dumps(_clean({
        "window": [cx.DEV_START, cx.DEV_END], "pooled": pooled, "bh_survivors": sorted(surv),
        "finalists": finalists, "lanes": lanes, "diagnostics": diag}), indent=1) + "\n")
    FINALISTS.write_text(json.dumps({
        "rule": "evaluation_criteria.md Crypto pilot (C), 2026-09-17",
        "pooled_passing_dev": [k for k, v in pooled.items() if v["passes_dev"]],
        "finalists": finalists}, indent=1) + "\n")
    print(json.dumps(_clean({"pooled": pooled, "maker": diag["maker_fee_mean_bps"],
                             "bh_survivors": sorted(surv), "finalists": finalists,
                             "lanes": {k: (round(v["mean_bps"], 2), round(v["p_one_sided"], 4),
                                           v["n"]) for k, v in lanes.items()}}), indent=1))


def cmd_holdout(_):
    if not FINALISTS.exists() or not _git_committed_clean(FINALISTS):
        raise SystemExit(f"refusing: {FINALISTS} must be committed unmodified first")
    spec = json.loads(FINALISTS.read_text())
    if not spec["pooled_passing_dev"] and not spec["finalists"]:
        print("nothing passed dev — holdout stays unspent (a null result).")
        return
    pooled, lanes, sharpe, _ = run(cx.HOLDOUT_START, cx.HOLDOUT_END, cx.TAKER_BPS,
                                   lanes_wanted=set(spec["finalists"]))
    k = max(len(spec["finalists"]), 1)
    verdicts = {}
    for name in spec["pooled_passing_dev"]:
        st = pooled[name]
        verdicts[name] = ("replicated" if st["p_one_sided"] < cx.PRIMARY_ALPHA
                          and st["mean_bps"] > 0 else "not_replicated")
    for name in spec["finalists"]:
        st = lanes.get(name, {"n": 0})
        if st["n"] < cx.MIN_HOLDOUT_DAYS:
            verdicts[name] = "not_testable"
        else:
            verdicts[name] = ("replicated" if st["p_one_sided"] < 0.05 / k
                              and st["mean_bps"] > 0 else "not_replicated")
    (OUT / "holdout_results.json").write_text(json.dumps(_clean({
        "window": [cx.HOLDOUT_START, cx.HOLDOUT_END], "verdicts": verdicts, "pooled": pooled,
        "lanes": lanes, "per_coin_sharpe_dd": sharpe}), indent=1) + "\n")
    print(json.dumps(_clean({"verdicts": verdicts, "pooled": pooled, "lanes": lanes}), indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["fetch", "dev", "holdout"])
    args = ap.parse_args()
    {"fetch": cmd_fetch, "dev": cmd_dev, "holdout": cmd_holdout}[args.phase](args)


if __name__ == "__main__":
    main()
