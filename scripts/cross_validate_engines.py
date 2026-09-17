#!/usr/bin/env python3
"""PLAN.md Step 5: fast research engines vs the real runner (mm.replay), net of costs.

Runs both sides under ONE configuration, the frozen VPS settings in
docs/frozen_config_2026-09-17.env. The local .env is never read: it has drifted
from the VPS (different ORB scorer threshold, no ORB_LATEST_ENTRY, no short
allowlist), which silently invalidated the first, abandoned attempt.

Alignment choices (see docs/evaluation_criteria.md, 2026-09-17 amendment):
  * Per-symbol overrides the live runner applies are passed to the fast engines
    (KDJ window, ORB minutes/vol/target, ORB cutoff and short allowlist).
  * ANTHROPIC_API_KEY is blanked. The ORB scorer's live threshold is 0.0, so it
    never blocks; skipping it changes no decision and makes no paid API calls.
  * Neither side has VIX or regime context for this window (logs/vix_daily.jsonl
    starts 2026-06-17; replay reads its own empty output dir), so the VIX and
    regime gates are open on both sides.
  * Replay P&L is normalized to one share before costs (compare_engine_results).

Usage:
    python scripts/cross_validate_engines.py --fast-only        # seconds
    python scripts/cross_validate_engines.py                    # ~1h, real runner
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import time as dtime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FROZEN_ENV = ROOT / "docs" / "frozen_config_2026-09-17.env"
STRATEGIES = ["bb_kdj", "orb", "vwap_pb", "gap_fade"]
SYMBOLS = ["US.SPY", "US.QQQ", "US.IWM"]


def pin_config(path: Path) -> None:
    """Load ONLY `path` into the environment. Must run before any mm import."""
    import dotenv
    dotenv.load_dotenv = lambda *a, **k: False  # mm/config.py must not read .env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()
    os.environ["ANTHROPIC_API_KEY"] = ""
    os.environ["DISCORD_WEBHOOK_URL"] = ""


def load_window(symbols: list[str], start: str, end: str) -> dict:
    from mm.replay import _load_csv
    return {s: _load_csv(ROOT / "logs" / f"{s.replace('.', '_')}_K_5M_combined.csv", start, end)
            for s in symbols}


def fast_pass(dfs: dict) -> dict:
    from mm import config as _config
    from mm.backtest import run_backtest, summarize_trades
    from mm.gap_fade import run_gap_fade
    from mm.orb_strategy import run_orb_signals
    from mm.vwap_pullback import run_vwap_pullback

    cfg = _config.cfg
    latest = (dtime(*map(int, cfg.orb_latest_entry.split(":")))
              if cfg.orb_latest_entry else None)
    result: dict = {}
    pooled: dict[str, list] = defaultdict(list)

    for sym, df in dfs.items():
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

        result[sym] = {}
        for strat, trades in runs.items():
            for t in trades:
                t.symbol = sym
            pooled[strat].extend(trades)
            result[sym][strat] = summarize_trades(trades, symbol=sym)

    result["aggregate"] = {s: summarize_trades(pooled[s]) for s in STRATEGIES}
    return result


def replay_pass(dfs: dict, out_dir: Path, fill_mode: str) -> dict:
    from compare_engine_results import replay_metrics
    from mm.replay import replay
    from mm.trades import load_trades

    replay(None, STRATEGIES,
           dfs={s: df.copy() for s, df in dfs.items()},
           fill_mode=fill_mode, out_dir=out_dir, quiet=True)
    return replay_metrics(load_trades(out_dir, default_start=None))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2026-01-02")
    ap.add_argument("--end", default="2026-06-09")
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--fast-only", action="store_true")
    ap.add_argument("--replay-dir", type=Path, default=Path("/tmp/moomoo_cross_replay"))
    ap.add_argument("--output", type=Path)
    ap.add_argument("--fill", default="instant", choices=["instant", "close", "touch"],
                    help="replay fill model; instant is the preregistered one")
    args = ap.parse_args()

    pin_config(FROZEN_ENV)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    from compare_engine_results import _json_safe, compare

    dfs = load_window([s.strip() for s in args.symbols.split(",")], args.start, args.end)
    t0 = time.time()
    fast = fast_pass(dfs)
    print(f"fast pass: {time.time() - t0:.1f}s", file=sys.stderr)
    result: dict = {"config": str(FROZEN_ENV.relative_to(ROOT)),
                    "window": [args.start, args.end],
                    "fill": None if args.fast_only else args.fill, "fast": fast}

    if not args.fast_only:
        t0 = time.time()
        replay = replay_pass(dfs, args.replay_dir, args.fill)
        print(f"replay pass: {time.time() - t0:.0f}s", file=sys.stderr)
        result["replay"] = replay
        result["comparison"] = compare(fast, replay, STRATEGIES)

    rendered = json.dumps(_json_safe(result), indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
