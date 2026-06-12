"""Replay harness — drive the REAL paper runner with historic candles.

Feeds historic 5-min candles bar-by-bar through `_eval_symbol_all_strategies`
(the exact code path the live runner uses: signal eval, order placement, fill
confirmation, position persistence, reconcile) against a fake broker whose fill
behavior is programmable. This tests the whole machine, not just the signals:

  - instant : every limit fills at its price (optimistic, backtest-like)
  - touch   : an order fills only if the NEXT bar trades through the limit;
              gaps fill at the open (models live SIMULATE limit-or-better)
  - never   : nothing ever fills (exercises entry_unfilled / exit retry paths)

Wall-clock is simulated: the runner sees datetime.now() as the replayed bar's
close time, so day boundaries (DailyTracker reset, ORB one-trade-per-day,
session filters, reconcile grace ages) behave exactly as they would live.

JSONL event logs land in the output dir, one file per symbol per replayed
session day — the same format the live runner writes, so diagnose/analyze
scripts work on replay output unchanged.
"""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import mm.paper as paper
import mm.risk as risk
from .logger import get_logger

log = get_logger("replay")

LOOKBACK_BARS = 600  # ~7.7 sessions of 5-min bars — covers all indicator warmups


# ---------------------------------------------------------------------------
# Simulated clock — patched into mm.paper / mm.risk in place of datetime/date/time
# ---------------------------------------------------------------------------

class SimClock:
    now: datetime = datetime(2022, 1, 1)
    _monotonic: float = 0.0


class FakeDateTime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ARG003 — runner always strips tzinfo right after
        n = SimClock.now
        return cls(n.year, n.month, n.day, n.hour, n.minute, n.second)


class FakeDate(date):
    @classmethod
    def today(cls):
        n = SimClock.now
        return date(n.year, n.month, n.day)


class SimTime:
    """Stands in for the `time` module inside mm.paper: sleeps advance a counter
    instead of wall time, so fill-confirmation timeouts resolve instantly."""

    @staticmethod
    def monotonic() -> float:
        return SimClock._monotonic

    @staticmethod
    def sleep(seconds: float) -> None:
        SimClock._monotonic += seconds


# ---------------------------------------------------------------------------
# Fake broker — same call surface as OpenSecTradeContext
# ---------------------------------------------------------------------------

RET_OK = 0


class FakeBroker:
    """Programmable broker. Fill resolution happens at place_order time using
    the bar AFTER the signal bar (live orders rest during the next 5 minutes)."""

    def __init__(self, dfs: dict[str, pd.DataFrame], fill_mode: str = "touch") -> None:
        assert fill_mode in ("instant", "touch", "never", "entry_only")
        self.dfs = dfs
        self.fill_mode = fill_mode
        self.idx: dict[str, int] = {}          # symbol -> index of bar just evaluated
        self.orders: dict[str, dict] = {}      # order_id -> state
        self.positions: dict[str, float] = {}  # symbol -> net qty
        self._next_id = 1000

    def set_index(self, symbol: str, i: int) -> None:
        self.idx[symbol] = i

    # -- order placement -----------------------------------------------------
    def place_order(self, price: float, qty: float, code: str, trd_side,
                    order_type=None, trd_env=None, acc_id=None):
        oid = str(self._next_id)
        self._next_id += 1
        side = str(trd_side)
        order = {"code": code, "qty": float(qty), "limit": float(price), "side": side,
                 "order_status": "SUBMITTED", "dealt_qty": 0.0, "dealt_avg_price": 0.0}
        self.orders[oid] = order

        fill = self._resolve_fill(code, float(price), side)
        if fill is not None:
            order["order_status"] = "FILLED_ALL"
            order["dealt_qty"] = float(qty)
            order["dealt_avg_price"] = fill
            is_buy = side in ("BUY", "BUY_BACK")
            self.positions[code] = self.positions.get(code, 0.0) + (qty if is_buy else -qty)
        return RET_OK, pd.DataFrame({"order_id": [oid]})

    def _resolve_fill(self, code: str, limit: float, side: str) -> float | None:
        if self.fill_mode == "never":
            return None
        if self.fill_mode == "entry_only":
            # the June 4 failure shape: entries fill, exits silently never do.
            # An exit here is any order that reduces the current net position.
            net = self.positions.get(code, 0.0)
            is_buy = side in ("BUY", "BUY_BACK")
            reducing = (net > 0 and not is_buy) or (net < 0 and is_buy)
            if reducing:
                return None
            return limit
        if self.fill_mode == "instant":
            return limit
        # touch: does the NEXT bar trade through the limit?
        df = self.dfs[code]
        i = self.idx.get(code, -1)
        if i + 1 >= len(df):
            return None
        nxt = df.iloc[i + 1]
        o, hi, lo = float(nxt["open"]), float(nxt["high"]), float(nxt["low"])
        if side in ("BUY", "BUY_BACK"):
            if o <= limit:
                return o          # gap in our favor — fill at open
            if lo <= limit:
                return limit
        else:  # SELL / SELL_SHORT
            if o >= limit:
                return o
            if hi >= limit:
                return limit
        return None

    # -- queries ---------------------------------------------------------------
    def order_list_query(self, order_id: str = "", trd_env=None, acc_id=None):
        order = self.orders.get(str(order_id))
        if order is None:
            return RET_OK, pd.DataFrame()
        return RET_OK, pd.DataFrame([{"order_id": order_id, **order}])

    def modify_order(self, op, order_id, _qty, _price, trd_env=None, acc_id=None):
        order = self.orders.get(str(order_id))
        if order is not None and order["order_status"] == "SUBMITTED":
            order["order_status"] = "CANCELLED_ALL"
        return RET_OK, None

    def position_list_query(self, trd_env=None, acc_id=None):
        rows = [{"code": sym, "qty": q, "can_sell_qty": q, "cost_price": 0.0,
                 "nominal_price": 0.0}
                for sym, q in self.positions.items() if q != 0]
        return RET_OK, pd.DataFrame(rows)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Replay driver
# ---------------------------------------------------------------------------

def symbol_from_csv(path: Path) -> str:
    """logs/US_SPY_K_5M_combined.csv -> US.SPY"""
    parts = path.stem.split("_")
    return f"{parts[0]}.{parts[1]}"


def _load_csv(path: Path, start: str | None, end: str | None) -> pd.DataFrame:
    df = pd.read_csv(path)
    if start:
        df = df[df["time_key"] >= start]
    if end:
        df = df[df["time_key"] <= f"{end} 23:59:59"]
    df = df.reset_index(drop=True)
    df["time_key"] = pd.to_datetime(df["time_key"])  # live fetch returns datetimes
    return df


def replay(
    csvs: list[Path],
    strategies: list[str],
    start: str | None = None,
    end: str | None = None,
    fill_mode: str = "touch",
    out_dir: Path | None = None,
    reconcile_every: int = 15,
    quiet: bool = True,
) -> dict:
    """Run the real paper runner over historic candles. Returns a summary dict.

    Patches mm.paper's clock, broker-independent guards, and cfg.logs_dir for
    the duration of the run, restoring everything afterwards.

    cfg is taken from the mm.paper module namespace (paper.cfg), NOT imported
    here: tests reload mm.paper/mm.config, and a stale import-time cfg binding
    would redirect logs_dir on the wrong object — the runner would then write
    replay events and position files into the REAL logs/ directory.
    """
    pcfg = paper.cfg
    out_dir = out_dir or (pcfg.logs_dir.parent / "replay_out")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    dfs = {symbol_from_csv(p): _load_csv(p, start, end) for p in csvs}
    dfs = {s: df for s, df in dfs.items() if not df.empty}
    if not dfs:
        raise SystemExit("No candles in the requested window.")
    broker = FakeBroker(dfs, fill_mode=fill_mode)

    # index maps: time_key -> row index, plus the global bar timeline
    tk_index = {s: {tk: i for i, tk in enumerate(df["time_key"])} for s, df in dfs.items()}
    timeline = sorted(set().union(*[set(df["time_key"]) for df in dfs.values()]))

    saved = {
        "logs_dir": pcfg.logs_dir,
        "market_open": paper.market_open,
        "datetime": paper.datetime,
        "date": paper.date,
        "time": paper.time,
        "risk_date": risk.date,
        "notify": paper.notify,
        "notify_entry": paper.notify_entry,
        "notify_exit": paper.notify_exit,
        "latest": paper._latest_closed_candles,
        "log_level": paper.log.level,
    }
    if quiet:
        import logging
        paper.log.setLevel(logging.ERROR)

    pcfg.logs_dir = out_dir
    paper.market_open = lambda: True
    paper.datetime = FakeDateTime
    paper.date = FakeDate
    paper.time = SimTime
    risk.date = FakeDate
    paper.notify = lambda *a, **k: None
    paper.notify_entry = lambda *a, **k: None
    paper.notify_exit = lambda *a, **k: None
    paper._entry_attempted.clear()
    paper._orphan_warned.clear()

    current_window: dict[str, pd.DataFrame] = {}
    paper._latest_closed_candles = lambda symbol, days=0: current_window.get(symbol, pd.DataFrame())

    positions: dict[tuple[str, str], object | None] = {
        (sym, strat): None for sym in dfs for strat in strategies
    }
    elogs = {sym: paper.PaperEventLog(sym) for sym in dfs}
    orb_traded: dict[str, date] = {}
    daily = risk.DailyTracker()

    bars_done = 0
    try:
        for tk in timeline:
            ts = pd.Timestamp(tk).to_pydatetime()
            # bar close = time_key + 5 min; runner evaluates ~10 s after close
            SimClock.now = ts + timedelta(minutes=5, seconds=10)

            for sym, df in dfs.items():
                i = tk_index[sym].get(tk)
                if i is None or i < 30:  # need a minimal indicator warmup
                    continue
                broker.set_index(sym, i)
                current_window[sym] = df.iloc[max(0, i - LOOKBACK_BARS + 1): i + 1].reset_index(drop=True)
                paper._eval_symbol_all_strategies(
                    sym, strategies, broker, 1, positions, elogs, daily,
                    orb_traded=orb_traded,
                )

            bars_done += 1
            if reconcile_every and bars_done % reconcile_every == 0:
                paper._reconcile_positions(broker, 1, positions, elogs)
    finally:
        pcfg.logs_dir = saved["logs_dir"]
        paper.market_open = saved["market_open"]
        paper.datetime = saved["datetime"]
        paper.date = saved["date"]
        paper.time = saved["time"]
        risk.date = saved["risk_date"]
        paper.notify = saved["notify"]
        paper.notify_entry = saved["notify_entry"]
        paper.notify_exit = saved["notify_exit"]
        paper._latest_closed_candles = saved["latest"]
        paper.log.setLevel(saved["log_level"])
        paper._entry_attempted.clear()

    return summarize(out_dir, positions, fill_mode)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarize(out_dir: Path, positions: dict, fill_mode: str) -> dict:
    events: list[dict] = []
    for f in sorted(out_dir.glob("paper_*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    closes = [e for e in events if e.get("event") == "position_close"]
    opens = [e for e in events if e.get("event") == "position_open"]
    unfilled_entries = [e for e in events if e.get("event") == "signal_skip"
                        and e.get("reason") == "entry_unfilled"]
    unfilled_exits = [e for e in events if e.get("event") == "error"
                      and "exit_unfilled" in str(e.get("message", ""))]
    mismatches = [e for e in events if e.get("event") == "error"
                  and "reconcile_mismatch" in str(e.get("message", ""))]

    per_strat: dict[str, dict] = {}
    for c in closes:
        s = per_strat.setdefault(c.get("strategy", "?"), {
            "trades": 0, "wins": 0, "pnl": 0.0, "gross_win": 0.0, "gross_loss": 0.0,
            "exit_reasons": {},
        })
        pnl = float(c.get("pnl", 0))
        s["trades"] += 1
        s["pnl"] += pnl
        if pnl > 0:
            s["wins"] += 1
            s["gross_win"] += pnl
        else:
            s["gross_loss"] += -pnl
        r = c.get("reason", "?")
        s["exit_reasons"][r] = s["exit_reasons"].get(r, 0) + 1

    still_open = [(k, v) for k, v in positions.items() if v is not None]
    slips = [e["slippage_bps"] for e in opens + closes
             if isinstance(e.get("slippage_bps"), (int, float))]

    return {
        "fill_mode": fill_mode,
        "out_dir": str(out_dir),
        "opens": len(opens),
        "closes": len(closes),
        "still_open": [(f"{sym}/{strat}") for (sym, strat), _ in still_open],
        "entry_unfilled": len(unfilled_entries),
        "exit_unfilled": len(unfilled_exits),
        "reconcile_mismatches": len(mismatches),
        "avg_slippage_bps": round(sum(slips) / len(slips), 2) if slips else 0.0,
        "per_strategy": per_strat,
        "total_pnl": round(sum(s["pnl"] for s in per_strat.values()), 4),
    }


def print_summary(s: dict) -> None:
    print(f"\n=== REPLAY SUMMARY (fill_mode={s['fill_mode']}) ===")
    print(f"  opens={s['opens']}  closes={s['closes']}  "
          f"entry_unfilled={s['entry_unfilled']}  exit_unfilled={s['exit_unfilled']}  "
          f"reconcile_mismatches={s['reconcile_mismatches']}")
    print(f"  avg slippage: {s['avg_slippage_bps']:+.2f} bps   total PnL: {s['total_pnl']:+.4f}")
    for strat, d in sorted(s["per_strategy"].items()):
        pf = (d["gross_win"] / d["gross_loss"]) if d["gross_loss"] > 0 else float("inf")
        win = d["wins"] / d["trades"] * 100 if d["trades"] else 0.0
        print(f"  {strat:8s} trades={d['trades']:<4d} win={win:5.1f}%  "
              f"pnl={d['pnl']:+9.4f}  PF={pf:5.3f}  exits={d['exit_reasons']}")
    if s["still_open"]:
        print(f"  still open at end: {', '.join(s['still_open'])}")
    print(f"  events: {s['out_dir']}/")
