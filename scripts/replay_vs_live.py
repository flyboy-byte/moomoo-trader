"""Replay a live session's candles through the harness and diff against
what the live runner actually did.

The invariant: same candles in → same first DECISIONS out. The bar on which
each (strategy, symbol) first attempts an entry must match exactly between
the live runner and a replay of the same day — divergence there means the
deployed machine and the tested machine have drifted apart.

Everything after the first entry attempt is path-dependent on fill outcomes
(the touch fill model vs moomoo's SIMULATE matching engine can differ), so
retries, exit bars on divergent positions, and fill prices are reported as
variance, not failures. Exits ARE strict when the entry fill matched.

  python scripts/replay_vs_live.py                 # latest live session
  python scripts/replay_vs_live.py --date 2026-06-11

Needs OpenD running locally to fetch warmup candles. Exits 0 with SKIP if
OpenD is unreachable (so verify.sh still passes offline).
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd  # noqa: E402

from mm.config import cfg  # noqa: E402

WARMUP_DAYS = 14  # calendar days of candles before the target date (indicator warmup)

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def _latest_live_date(logs_dir: Path) -> str | None:
    dates = sorted({f.stem.rsplit("_", 1)[-1] for f in logs_dir.glob("paper_US_*_20*.jsonl")})
    return dates[-1] if dates else None


def _load_events(paths: list[Path]) -> list[dict]:
    events = []
    for p in paths:
        if not p.exists():
            continue
        # paper_US_QQQ_2026-06-11.jsonl -> US.QQQ (bar_eval events carry no symbol field)
        sym = p.stem.rsplit("_", 1)[0].replace("paper_", "").replace("_", ".", 1)
        for line in p.read_text().splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            e.setdefault("symbol", sym)
            events.append(e)
    return events


def _clock_offset_hours(events: list[dict]) -> int:
    """Event `ts` uses the writer's local clock (VPS=UTC, replay=ET), while
    bar_eval's eval_ts is always ET (the runner converts before logging).
    The rounded ts−eval_ts gap is therefore the writer's offset from ET."""
    for e in events:
        if e.get("event") == "bar_eval" and e.get("ts") and e.get("eval_ts"):
            gap = (datetime.fromisoformat(e["ts"])
                   - datetime.fromisoformat(e["eval_ts"]))
            return round(gap.total_seconds() / 3600)
    return 0


def _bar_of(ts: str, offset_h: int) -> str:
    """Map an event timestamp to the ET 5-min bar being evaluated (the bar
    closed just before the eval; events fire seconds after the close)."""
    t = datetime.fromisoformat(ts) - timedelta(hours=offset_h)
    floored = t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)
    return (floored - timedelta(minutes=5)).strftime("%H:%M")


def _decisions(events: list[dict], date_str: str) -> dict:
    """Extract per-(strategy,symbol): first entry attempt bar, entered bar,
    exit decision bars, and close records."""
    offset_h = _clock_offset_hours(events)
    first_entry: dict[tuple, str] = {}
    entered: dict[tuple, str] = {}
    exit_bars: dict[tuple, set] = {}
    closes: dict[tuple, list] = {}
    bar_signals: dict[tuple, dict] = {}
    for e in events:
        ts = str(e.get("ts", ""))
        if not ts:
            continue
        # date check in the writer's own clock — sessions never straddle midnight in ET or UTC
        if not ts.startswith(date_str):
            continue
        key = (e.get("strategy"), e.get("symbol"))
        ev = e.get("event")
        if ev == "bar_eval":
            bar = str(e.get("candle_ts", ""))[11:16]
            bar_signals.setdefault((e.get("strategy"), e.get("symbol"), bar),
                                   e.get("signals", {}))
        elif ev == "order_attempt":
            bar = _bar_of(ts, offset_h)
            if e.get("side") in ("BUY", "SELL_SHORT"):
                k = key + (e.get("side"),)
                if k not in first_entry or bar < first_entry[k]:
                    first_entry[k] = bar
            else:
                exit_bars.setdefault(key, set()).add(bar)
        elif ev == "position_open":
            entered.setdefault(key, _bar_of(ts, offset_h))
        elif ev == "position_close":
            closes.setdefault(key, []).append(
                (_bar_of(ts, offset_h), e.get("reason"), e.get("exit"), e.get("pnl")))
    return {"first_entry": first_entry, "entered": entered,
            "exit_bars": exit_bars, "closes": closes, "bar_signals": bar_signals}


def _inputs_differ(live: dict, rep: dict, strategy: str, symbol: str,
                   bars: list[str | None]) -> str | None:
    """If the logged signal payloads differ on any disputed bar, the two runs
    saw different DATA (candle revisions) — not different logic. Compares only
    keys present on both sides (telemetry fields may be added over time)."""
    for bar in bars:
        if bar is None:
            continue
        ls = live["bar_signals"].get((strategy, symbol, bar))
        rs = rep["bar_signals"].get((strategy, symbol, bar))
        if ls is None or rs is None:
            continue
        common = set(ls) & set(rs)
        diffs = {k: (ls[k], rs[k]) for k in common if ls[k] != rs[k]}
        if diffs:
            return f"bar {bar}: " + ", ".join(
                f"{k} live={a} replay={b}" for k, (a, b) in sorted(diffs.items()))
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: latest live session)")
    args = ap.parse_args()

    date_str = args.date or _latest_live_date(cfg.logs_dir)
    if not date_str:
        sys.exit("No live JSONL logs found.")

    live_files = sorted(cfg.logs_dir.glob(f"paper_US_*_{date_str}.jsonl"))
    if not live_files:
        sys.exit(f"No live logs for {date_str}")
    symbols = sorted({f.stem.replace(f"_{date_str}", "").replace("paper_", "").replace("_", ".", 1)
                      for f in live_files})

    print(f"Replay-vs-live diff for {date_str}  symbols={symbols}")

    # --- fetch candles (warmup + target day) from OpenD ---
    # Pre-check the socket: the SDK retries ECONNREFUSED forever instead of raising.
    import socket
    try:
        with socket.create_connection((cfg.host, cfg.port), timeout=3):
            pass
    except OSError as e:
        print(f"{YELLOW}SKIP: OpenD not reachable at {cfg.host}:{cfg.port} ({e}){RESET}")
        sys.exit(0)

    try:
        from mm.data import fetch_candles
        start = (datetime.fromisoformat(date_str) - timedelta(days=WARMUP_DAYS)).strftime("%Y-%m-%d")
        dfs = {}
        for sym in symbols:
            df = fetch_candles(symbol=sym, ktype=cfg.candle_ktype, start=start, end=date_str)
            df = df[df["time_key"] <= f"{date_str} 23:59:59"].reset_index(drop=True)
            df["time_key"] = pd.to_datetime(df["time_key"])
            dfs[sym] = df
    except Exception as e:
        print(f"{YELLOW}SKIP: candle fetch failed ({e}){RESET}")
        sys.exit(0)

    # --- replay through the real runner ---
    from mm.replay import replay
    out_dir = Path("replay_diff") / date_str
    replay(None, cfg.active_strategies, fill_mode="touch", out_dir=out_dir, dfs=dfs)

    live = _decisions(_load_events(live_files), date_str)
    rep = _decisions(_load_events(sorted(out_dir.glob(f"paper_US_*_{date_str}.jsonl"))), date_str)

    failures, variance = [], []

    # 1) First entry attempts must match — UNLESS the disputed bars saw
    #    different candle data (vendor revisions), which is data variance.
    for k in sorted(set(live["first_entry"]) | set(rep["first_entry"])):
        lv, rv = live["first_entry"].get(k), rep["first_entry"].get(k)
        if lv == rv:
            continue
        strategy, symbol, _side = k
        data_diff = _inputs_differ(live, rep, strategy, symbol, [lv, rv])
        if data_diff:
            variance.append(f"entry {k}: live={lv} replay={rv} — candle data was "
                            f"revised after live eval ({data_diff})")
        else:
            failures.append(f"first entry attempt {k}: live={lv} replay={rv} "
                            f"(identical inputs, different decision — CODE DRIFT)")

    # 2) Exits: strict only where the entry fill path matched.
    for key in sorted(set(live["exit_bars"]) | set(rep["exit_bars"])):
        lv, rv = live["exit_bars"].get(key, set()), rep["exit_bars"].get(key, set())
        if lv == rv:
            continue
        if live["entered"].get(key) == rep["entered"].get(key):
            strategy, symbol = key
            disputed = sorted(lv.symmetric_difference(rv))
            data_diff = _inputs_differ(live, rep, strategy, symbol, disputed)
            if data_diff:
                variance.append(f"exit {key}: live={sorted(lv)} replay={sorted(rv)} — "
                                f"candle data revised ({data_diff})")
            else:
                failures.append(f"exit decisions {key}: live={sorted(lv)} replay={sorted(rv)}")
        else:
            variance.append(f"exit path {key}: live={sorted(lv)} replay={sorted(rv)} "
                            f"(entry fills diverged: live entered {live['entered'].get(key)}, "
                            f"replay {rep['entered'].get(key)})")

    # 3) Close records: informational.
    for key in sorted(set(live["closes"]) & set(rep["closes"])):
        if live["closes"][key] != rep["closes"][key]:
            variance.append(f"close records {key}: live={live['closes'][key]} "
                            f"replay={rep['closes'][key]}")

    for v in variance:
        print(f"  {YELLOW}variance{RESET} {v}")
    if failures:
        print(f"{RED}✗ DECISION MISMATCH ({len(failures)}):{RESET}")
        for f in failures:
            print(f"    {f}")
        sys.exit(1)
    print(f"{GREEN}✓ Decisions match{RESET}: {len(live['first_entry'])} first-entry "
          f"decisions and {sum(len(v) for v in live['exit_bars'].values())} exit decisions "
          f"agree between live and replay for {date_str} "
          f"({len(variance)} fill-path variance notes)")


if __name__ == "__main__":
    main()
