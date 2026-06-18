"""ORB entry-hour analysis — does the late-day ORB edge hold?

Slices ORB trades by ET entry hour: count, win rate, PnL, PF, and exit
reason mix per hour. Works on any JSONL event dir (replay output or live
logs). Research only — answers CLAUDE.md priority #4 (ORB_CUTOFF_HOUR?).

  python scripts/analyze_orb_hours.py replay_ytd_v2/
  python scripts/analyze_orb_hours.py logs/            # live sessions
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from mm.backtest import profit_factor  # noqa: E402


def _load(dir_: Path) -> list[dict]:
    events = []
    for f in sorted(dir_.glob("paper_US_*_20*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _offset_h(events: list[dict]) -> int:
    """Writer clock offset from ET (VPS logs are UTC, replay logs are ET)."""
    for e in events:
        if e.get("event") == "bar_eval" and e.get("ts") and e.get("eval_ts"):
            gap = (datetime.fromisoformat(e["ts"]) - datetime.fromisoformat(e["eval_ts"]))
            return round(gap.total_seconds() / 3600)
    return 0


def main() -> None:
    dir_ = Path(sys.argv[1] if len(sys.argv) > 1 else "replay_ytd_v2")
    events = _load(dir_)
    off = _offset_h(events)

    # pair each orb close with its open (per symbol, chronological)
    opens: dict[str, list[dict]] = defaultdict(list)
    trades = []
    for e in events:
        if e.get("strategy") != "orb":
            continue
        sym = e.get("symbol")
        if e.get("event") == "position_open":
            opens[sym].append(e)
        elif e.get("event") == "position_close" and opens.get(sym):
            o = opens[sym].pop(0)
            hour = (datetime.fromisoformat(o["ts"]) - timedelta(hours=off)).hour
            trades.append({"hour": hour, "pnl": float(e.get("pnl", 0)),
                           "reason": e.get("reason"), "symbol": sym})

    if not trades:
        sys.exit(f"No ORB trades found in {dir_}")

    by_hour: dict[int, list[dict]] = defaultdict(list)
    for t in trades:
        by_hour[t["hour"]].append(t)

    print(f"ORB trades by ET entry hour — {dir_}  ({len(trades)} trades)\n")
    print(f"{'hour':>4} {'n':>4} {'win%':>6} {'pnl':>9} {'PF':>6}  exit mix")
    cum_keep_pnl = 0.0
    for h in sorted(by_hour):
        ts = by_hour[h]
        n = len(ts)
        wins = sum(1 for t in ts if t["pnl"] > 0)
        pnl = sum(t["pnl"] for t in ts)
        pf = profit_factor([t["pnl"] for t in ts])
        reasons = defaultdict(int)
        for t in ts:
            reasons[t["reason"]] += 1
        mix = " ".join(f"{r}:{c}" for r, c in sorted(reasons.items()))
        print(f"{h:>4} {n:>4} {wins / n * 100:>5.1f}% {pnl:>+9.2f} {pf:>6.2f}  {mix}")

    print("\nCumulative PnL if entries were cut off AFTER each hour:")
    total = sum(t["pnl"] for t in trades)
    for h in sorted(by_hour):
        cum_keep_pnl += sum(t["pnl"] for t in by_hour[h])
        cut = total - cum_keep_pnl
        print(f"  cutoff after {h:02d}:xx → keep {cum_keep_pnl:+9.2f}  (drops {cut:+9.2f} from later hours)")


if __name__ == "__main__":
    main()
