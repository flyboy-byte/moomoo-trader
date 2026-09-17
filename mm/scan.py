"""Wide-scan machinery (PLAN.md Steps 5, 10, 11) — engines, per-trade rows, statistics.

Everything a lane's verdict depends on lives here so the Step 5 cross-validation and
the Step 11 scan run the *same* engine calls. The frozen rules (thresholds, windows,
finalist cap) are the ones in docs/evaluation_criteria.md, "Wide-scan configuration,
split, and selection rule" — change them there first, never here alone.

`pin_config()` must run before anything imports mm.config in the process.
"""
from __future__ import annotations

import os
from datetime import time as dtime
from pathlib import Path

STRATEGIES = ("bb_kdj", "orb", "vwap_pb", "gap_fade")

DEV_START, DEV_END = "2022-01-03", "2026-08-31"
HOLDOUT_START, HOLDOUT_END = "2019-01-02", "2021-12-31"
WARMUP_DAYS = 45               # indicator warmup before a window; its trades are dropped
MIN_DEV_TRADES = 40
MIN_HOLDOUT_TRADES = 20
BH_Q = 0.10
FINALIST_CAP = 10
POOLED_ALPHA = 0.05 / len(STRATEGIES)
FINALIST_ALPHA = 0.05          # divided by the number of finalists
SLIPPAGE_STRESS_BPS = 3.5


def pin_config(path: Path) -> None:
    """Load ONLY `path` into the environment; never the local .env. No paid API calls."""
    import dotenv
    dotenv.load_dotenv = lambda *a, **k: False
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()
    os.environ["ANTHROPIC_API_KEY"] = ""
    os.environ["DISCORD_WEBHOOK_URL"] = ""


def run_engines(sym: str, df) -> dict[str, list]:
    """Run every fast engine on one symbol with the live runner's per-symbol settings."""
    from . import config as _config
    from .backtest import run_backtest
    from .gap_fade import run_gap_fade
    from .orb_strategy import run_orb_signals
    from .vwap_pullback import run_vwap_pullback

    cfg = _config.cfg
    latest = (dtime(*map(int, cfg.orb_latest_entry.split(":")))
              if cfg.orb_latest_entry else None)
    runs: dict[str, list] = {}

    base_window = cfg.kdj_window_bars
    cfg.kdj_window_bars = cfg.kdj_window_overrides.get(sym, base_window)
    try:
        runs["bb_kdj"], _ = run_backtest(df.copy())
    finally:
        cfg.kdj_window_bars = base_window

    runs["orb"], _ = run_orb_signals(
        df.copy(),
        vol_mult=cfg.orb_vol_mult_overrides.get(sym, cfg.orb_vol_mult),
        orb_minutes=cfg.orb_minutes_overrides.get(sym, cfg.orb_minutes),
        target_mult=cfg.orb_target_mult_overrides.get(sym, cfg.orb_target_mult),
        latest_entry=latest,
        shorts_allowed=cfg.orb_shorts_enabled
        and (not cfg.orb_short_symbols or sym in cfg.orb_short_symbols),
    )
    if not cfg.vwap_pb_symbols or sym in cfg.vwap_pb_symbols:
        runs["vwap_pb"] = run_vwap_pullback(
            df.copy(),
            stop_mult=cfg.vwap_pb_stop_mult,
            max_crosses=cfg.vwap_pb_max_crosses,
            min_entry_time=dtime(*cfg.vwap_pb_min_entry_time),
        )
    runs["gap_fade"] = run_gap_fade(df.copy())
    for trades in runs.values():
        for t in trades:
            t.symbol = sym
    return runs


def trade_rows(sym: str, strategy: str, trades, start: str, end: str) -> list[dict]:
    """One-share rows for trades ENTERED inside [start, end]; warmup trades are dropped."""
    from . import costs
    rows = []
    for t in trades:
        day = str(t.entry_time)[:10]
        if not (start <= day <= end) or float(t.entry_price) <= 0:
            continue
        entry = float(t.entry_price)
        pnl = float(t.pnl)
        rows.append({
            "symbol": sym, "strategy": strategy, "date": day,
            "direction": getattr(t, "direction", "long"),
            "entry": entry, "gross_pnl": pnl,
            "net_pnl": costs.net_pnl(pnl, sym, entry, 1.0),
            "gross_bps": pnl / entry * 10_000,
            "net_bps": costs.net_bps(pnl, sym, entry, 1.0),
            "cost_bps": costs.round_trip_bps(sym),
        })
    return rows


def buy_and_hold(df, start: str, end: str) -> dict:
    """The symbol's own passive null over the same window (PLAN.md Step 10)."""
    days = df["time_key"].astype(str).str[:10]
    w = df[(days >= start) & (days <= end)]
    if w.empty:
        return {"return_pct": None, "days": 0}
    first, last = float(w["open"].iloc[0]), float(w["close"].iloc[-1])
    n_days = w["time_key"].astype(str).str[:10].nunique()
    return {"return_pct": (last / first - 1) * 100, "days": int(n_days),
            "first": str(w["time_key"].iloc[0]), "last": str(w["time_key"].iloc[-1])}


def lane_stats(rows: list[dict], stress_bps: float = 0.0) -> dict:
    """Statistics for one set of trades, bootstrapped by trading day."""
    import numpy as np

    from . import stats
    from .backtest import profit_factor

    if not rows:
        return {"n": 0, "p_one_sided": 1.0}
    days = [r["date"] for r in rows]
    net_bps = [r["net_bps"] - stress_bps for r in rows]
    lo, hi = stats.bootstrap_mean_ci(net_bps, block_keys=days)
    pp = stats.prob_positive(net_bps, block_keys=days)
    longs = [r["net_bps"] for r in rows if r["direction"] == "long"]
    shorts = [r["net_bps"] for r in rows if r["direction"] == "short"]
    return {
        "n": len(rows),
        "days": len(set(days)),
        "gross_pf": profit_factor([r["gross_pnl"] for r in rows]),
        "net_pf": profit_factor([r["net_pnl"] for r in rows]),
        "mean_gross_bps": float(np.mean([r["gross_bps"] for r in rows])),
        "mean_cost_bps": float(np.mean([r["cost_bps"] for r in rows])),
        "mean_net_bps": float(np.mean(net_bps)),
        "net_bps_ci": (lo, hi),
        "p_one_sided": 1.0 if pp != pp else 1.0 - pp,
        "long": {"n": len(longs), "mean_net_bps": float(np.mean(longs)) if longs else None},
        "short": {"n": len(shorts), "mean_net_bps": float(np.mean(shorts)) if shorts else None},
    }


def benjamini_hochberg(pvalues: dict[str, float], q: float = BH_Q) -> set[str]:
    """Keys rejected at FDR q (step-up)."""
    ranked = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(ranked)
    k_max = 0
    for k, (_, p) in enumerate(ranked, start=1):
        if p <= q * k / m:
            k_max = k
    return {key for key, _ in ranked[:k_max]}


def select_finalists(lanes: dict[str, dict], q: float = BH_Q, cap: int = FINALIST_CAP,
                     min_n: int = MIN_DEV_TRADES) -> list[str]:
    """Step 6c: BH over every lane (ineligible = p 1), rank by CI lower bound, cap."""
    pvals = {k: (v["p_one_sided"] if v.get("n", 0) >= min_n else 1.0) for k, v in lanes.items()}
    survivors = benjamini_hochberg(pvals, q)
    ranked = sorted(survivors, key=lambda k: lanes[k]["net_bps_ci"][0], reverse=True)
    return ranked[:cap]


def holdout_verdict(stats_plain: dict, stats_stressed: dict, alpha: float,
                    min_n: int = MIN_HOLDOUT_TRADES) -> str:
    if stats_plain.get("n", 0) < min_n:
        return "not_testable"
    ok = (stats_plain["p_one_sided"] < alpha and stats_plain["mean_net_bps"] > 0
          and stats_stressed["mean_net_bps"] > 0)
    return "replicated" if ok else "not_replicated"
