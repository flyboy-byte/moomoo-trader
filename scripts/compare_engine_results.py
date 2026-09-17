#!/usr/bin/env python3
"""Compare fast-engine metrics with a completed paper-runner replay.

The fast research engines model one share per trade.  The replay uses the live
position-sizing path, so its dollar P&L must be divided by quantity before profit
factor is comparable.  This script applies that normalization and then charges the
same frozen per-symbol round-trip cost on both sides.

Example:
    python scripts/compare_engine_results.py \
      --fast-json /tmp/moomoo_fast_results.json \
      --replay-dir /tmp/moomoo_cross_replay \
      --output docs/engine_cross_validation_2026-09-16.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm import costs
from mm.backtest import profit_factor
from mm.trades import load_trades


def summarize_one_share(trades: list[dict]) -> dict:
    """Summarize closed replay trades after removing live quantity sizing."""
    gross: list[float] = []
    net: list[float] = []
    gross_bps: list[float] = []
    net_bps: list[float] = []

    for trade in trades:
        if not trade.get("closed") or trade.get("pnl") is None:
            continue
        qty = float(trade.get("qty") or 0)
        entry = float(trade.get("entry") or 0)
        if qty <= 0 or entry <= 0:
            continue
        symbol = str(trade.get("symbol") or "")
        gross_per_share = float(trade["pnl"]) / qty
        net_per_share = costs.net_pnl(gross_per_share, symbol, entry, 1.0)
        gross.append(gross_per_share)
        net.append(net_per_share)
        gross_bps.append(gross_per_share / entry * 10_000)
        net_bps.append(net_per_share / entry * 10_000)

    return {
        "trades": len(gross),
        "gross_pnl": sum(gross),
        "net_pnl": sum(net),
        "gross_pf": profit_factor(gross),
        "net_pf": profit_factor(net),
        "avg_bps": sum(gross_bps) / len(gross_bps) if gross_bps else None,
        "avg_bps_net": sum(net_bps) / len(net_bps) if net_bps else None,
    }


def replay_metrics(trades: list[dict]) -> dict:
    """Return aggregate and per-symbol replay metrics by strategy."""
    aggregate: dict[str, list[dict]] = defaultdict(list)
    per_symbol: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for trade in trades:
        strategy = str(trade.get("strategy") or "unknown")
        symbol = str(trade.get("symbol") or "unknown")
        aggregate[strategy].append(trade)
        per_symbol[symbol][strategy].append(trade)
    return {
        "aggregate": {strategy: summarize_one_share(rows)
                      for strategy, rows in sorted(aggregate.items())},
        "per_symbol": {
            symbol: {strategy: summarize_one_share(rows)
                     for strategy, rows in sorted(by_strategy.items())}
            for symbol, by_strategy in sorted(per_symbol.items())
        },
    }


def _count_diff_pct(fast_count: int, replay_count: int) -> float:
    if fast_count == 0:
        return 0.0 if replay_count == 0 else math.inf
    return abs(replay_count - fast_count) / fast_count * 100


def compare(
    fast: dict,
    replay: dict,
    strategies: list[str],
    *,
    count_tolerance_pct: float = 2.0,
    pf_tolerance: float = 0.05,
) -> dict:
    """Apply the preregistered aggregate count/PF gates."""
    rows: dict[str, dict] = {}
    for strategy in strategies:
        fast_row = fast.get("aggregate", {}).get(strategy, {})
        replay_row = replay.get("aggregate", {}).get(strategy, {})
        fast_count = int(fast_row.get("trades", 0))
        replay_count = int(replay_row.get("trades", 0))
        count_diff = _count_diff_pct(fast_count, replay_count)
        fast_pf = float(fast_row.get("net_pf", math.inf))
        replay_pf = float(replay_row.get("net_pf", math.inf))
        pf_diff = abs(replay_pf - fast_pf) if math.isfinite(fast_pf) and math.isfinite(replay_pf) \
            else (0.0 if fast_pf == replay_pf else math.inf)
        count_pass = count_diff <= count_tolerance_pct or math.isclose(
            count_diff, count_tolerance_pct, rel_tol=0.0, abs_tol=1e-12
        )
        pf_pass = pf_diff <= pf_tolerance or math.isclose(
            pf_diff, pf_tolerance, rel_tol=0.0, abs_tol=1e-12
        )
        rows[strategy] = {
            "fast": fast_row,
            "replay": replay_row,
            "trade_count_difference_pct": count_diff,
            "absolute_net_pf_difference": pf_diff,
            "trade_count_pass": count_pass,
            "net_pf_pass": pf_pass,
            "pass": count_pass and pf_pass,
        }

    return {
        "gate": {
            "trade_count_difference_pct_max": count_tolerance_pct,
            "absolute_net_pf_difference_max": pf_tolerance,
            "replay_normalization": "one share per trade before costs",
        },
        "strategies": rows,
        "pass": all(row["pass"] for row in rows.values()),
    }


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast-json", type=Path, required=True)
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--strategies",
        default="bb_kdj,orb,vwap_pb,gap_fade",
        help="comma-separated preregistered strategy names",
    )
    args = parser.parse_args()

    fast = json.loads(args.fast_json.read_text())
    trades = load_trades(args.replay_dir, default_start=None)
    replay = replay_metrics(trades)
    strategies = [name.strip() for name in args.strategies.split(",") if name.strip()]
    result = {
        "fast": fast,
        "replay": replay,
        "comparison": compare(fast, replay, strategies),
    }
    rendered = json.dumps(_json_safe(result), indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
