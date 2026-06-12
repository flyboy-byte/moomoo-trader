"""Replay historic candles through the REAL paper runner with a fake broker.

This is end-to-end pipeline testing: signal eval, order placement, fill
confirmation, position persistence, daily limits, ORB once-per-day, reconcile —
the exact live code path, compressed from weeks of sessions into minutes.

  python scripts/replay_paper.py --latest --start 2026-01-01 --end 2026-06-09
  python scripts/replay_paper.py logs/US_SPY_K_5M_combined.csv --fill instant
  python scripts/replay_paper.py --latest --fill never        # adversarial: nothing fills
  python scripts/replay_paper.py --latest --strategies orb,vwap_pb

Fill modes: touch (default — fills only if the next bar trades the limit),
instant (backtest-like), never (exercises every unfilled-order path).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mm.config import cfg  # noqa: E402
from mm.replay import replay, print_summary  # noqa: E402

DEFAULT_CSVS = [
    "logs/US_SPY_K_5M_combined.csv",
    "logs/US_QQQ_K_5M_combined.csv",
    "logs/US_IWM_K_5M_combined.csv",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csvs", nargs="*", help="candle CSVs (default: --latest set)")
    ap.add_argument("--latest", action="store_true", help="use the combined SPY/QQQ/IWM CSVs")
    ap.add_argument("--start", help="YYYY-MM-DD")
    ap.add_argument("--end", help="YYYY-MM-DD")
    ap.add_argument("--fill", default="touch", choices=["touch", "instant", "never", "entry_only"])
    ap.add_argument("--strategies", default=None,
                    help="comma list (default: STRATEGIES from .env)")
    ap.add_argument("--out", default="replay_out", help="output dir for JSONL events")
    ap.add_argument("--verbose", action="store_true", help="keep paper runner INFO logging")
    args = ap.parse_args()

    csvs = [Path(c) for c in args.csvs] or [Path(c) for c in DEFAULT_CSVS]
    for c in csvs:
        if not c.exists():
            sys.exit(f"Missing CSV: {c}")

    strategies = (args.strategies.split(",") if args.strategies
                  else cfg.active_strategies)

    print(f"Replaying {[c.name for c in csvs]}")
    print(f"  strategies={strategies}  fill={args.fill}  "
          f"window={args.start or 'begin'} → {args.end or 'end'}")

    summary = replay(
        csvs, strategies, start=args.start, end=args.end,
        fill_mode=args.fill, out_dir=Path(args.out), quiet=not args.verbose,
    )
    print_summary(summary)


if __name__ == "__main__":
    main()
