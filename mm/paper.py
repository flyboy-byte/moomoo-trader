"""
Paper-trading loop.

Polls OpenD every 60 seconds, evaluates the last N closed 5-min candles through
the full signal engine, and places simulated orders via OpenSecTradeContext.

Supports multiple simultaneous strategies on the same symbols. Each (symbol, strategy)
pair has independent position state and P&L tracking. Candles are fetched once per
symbol per poll and shared across all active strategies.

Active strategies are controlled by STRATEGIES in .env (comma-separated list of
"bb_kdj" and/or "vwap"). Defaults to STRATEGY_TYPE for backward compatibility.

Kill switch: create STOP_TRADING.txt in the project root to pause without killing
the process. Remove the file to resume.

Structured event log: every signal check, risk block, order attempt, fill, and exit
is written to logs/paper_SYMBOL_YYYY-MM-DD.jsonl with a strategy tag on each event.
"""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import clock
from . import risk as _risk
from .config import cfg, validate_config
from .data import fetch_candles
from .notifications import notify, notify_entry, notify_exit
from .risk import trading_allowed, per_slot_dollars, DailyTracker
from .strategy import compute_signals
from .vwap_strategy import compute_vwap_signals
from .logger import get_logger

# ---------------------------------------------------------------------------
# Back-compat re-exports — external callers (tests, scripts, replay) import
# these via mm.paper; the canonical locations are the modules below.
# ---------------------------------------------------------------------------
from .events import (        # noqa: F401
    PaperEventLog, PaperPosition,
    _load_position, _load_orb_traded, _save_orb_traded,
    _clear_position,
)
from .evals import (         # noqa: F401
    _entry_attempted,
    _eval_bb_kdj, _eval_bb_kdj_loose, _eval_vwap, _eval_vwap_pb, _eval_orb,
)
from .execution import (     # noqa: F401
    _orphan_warned,
    _reconcile_positions, trade_context, _get_simulate_acc_id,
    _place_buy, _place_sell, _place_short, _place_cover,
    _confirm_fill, _execute_entry, _execute_exit,
)
from .risk import (          # noqa: F401
    _qty, _position_cap, _slot_dollars,
)

log = get_logger("paper")

POLL_SECONDS = 60
CANDLE_LOOKBACK_DAYS = 7  # wide enough to survive a holiday + weekend with no trading days
MAX_CONSECUTIVE_ERRORS = 3
BACKOFF_SECONDS = 300  # 5 min after repeated failures


# ---------------------------------------------------------------------------
# Candle fetching with explicit closed-candle verification
# ---------------------------------------------------------------------------

def _latest_closed_candles(symbol: str, days: int = CANDLE_LOOKBACK_DAYS) -> pd.DataFrame:
    """Fetch recent candles and drop the last bar, which may still be forming.

    The Moomoo API can return the currently forming candle as the last row.
    We always discard it to guarantee we only evaluate closed bars.

    Stale check is applied to the bar AFTER dropping the forming row — i.e. the
    bar that will actually be evaluated. Checking the forming bar's age is wrong:
    a same-day partial bar has age ~0 but the second-to-last could be from yesterday.
    """
    end = clock.now().strftime("%Y-%m-%d")
    start = (clock.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = fetch_candles(symbol=symbol, ktype=cfg.candle_ktype, start=start, end=end)
    if df.empty:
        return df

    if len(df) < 2:
        log.warning("%s: fewer than 2 candles returned — skipping", symbol)
        return pd.DataFrame()

    # Drop the last (possibly still-forming) bar first
    df = df.iloc[:-1].reset_index(drop=True)

    # NOW check staleness of the bar we'll actually evaluate
    last_closed_ts = df.iloc[-1]["time_key"]
    now_et = clock.now_et()
    age_min = (now_et - pd.Timestamp(last_closed_ts)).total_seconds() / 60
    log.info(
        "Candle check: last_closed=%s  age=%.0fmin",
        last_closed_ts, age_min,
    )
    if age_min > 15:
        log.warning("Stale candles: last closed bar %s is %.0f min old — skipping eval",
                    last_closed_ts, age_min)
        return pd.DataFrame()
    return df


def _trigger_eod_summary() -> None:
    """Load today's JSONL and post EOD summary to Discord (no-op if webhook not set)."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "eod_summary",
            Path(__file__).parent.parent / "scripts" / "eod_summary.py",
        )
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        s = mod.load_summary(clock.today())
        log.info("EOD: %d closed trades  pnl=%+.2f", len(s.closed_trades), s.realized_pnl)
        if cfg.discord_webhook_url:
            notify(mod.format_discord(s))
    except Exception as e:
        log.warning("EOD summary failed: %s", e)


# ---------------------------------------------------------------------------
# Multi-symbol loop — fetches candles once, runs all active strategies
# ---------------------------------------------------------------------------

def run_multi(symbols: list[str] | None = None) -> None:
    """Run the paper loop across multiple symbols and strategies each poll cycle.

    Candles are fetched once per symbol. All active strategies evaluate the same
    bar. Each (symbol, strategy) pair has independent position state.

    Active strategies: cfg.active_strategies (from STRATEGIES env var).
    Shared DailyTracker: combined daily loss/trade limit across all strategies.
    """
    symbols = symbols or cfg.symbols
    strategies = cfg.active_strategies

    # --- Config validation (fail fast on bad .env before touching the broker) ---
    errors = validate_config()
    for msg in errors:
        if msg.startswith("CRITICAL"):
            log.error("CONFIG ERROR: %s", msg)
        else:
            log.warning("CONFIG WARNING: %s", msg)
    if any(e.startswith("CRITICAL") for e in errors):
        log.error("Aborting: critical config error(s). Fix .env and restart.")
        return

    if cfg.total_capital > 0:
        _risk._slot_dollars = per_slot_dollars(len(symbols), len(strategies))
        mode = "fractional" if cfg.fractional_shares else "whole-share"
        log.info("Capital mode: TOTAL_CAPITAL=%.2f  slots=%d  per_slot=%.4f  mode=%s",
                 cfg.total_capital, len(symbols) * len(strategies), _risk._slot_dollars, mode)
    else:
        _risk._slot_dollars = 0.0

    log.info("Multi runner: symbols=%s  strategies=%s  ktype=%s  min_signal_score=%d",
             symbols, strategies, cfg.candle_ktype, cfg.min_signal_score)
    notify(f"[PAPER] Multi runner started: {', '.join(symbols)} | {', '.join(strategies)}")

    # positions[(symbol, strategy)] = PaperPosition | None
    positions: dict[tuple[str, str], PaperPosition | None] = {
        (sym, strat): _load_position(sym, strat)
        for sym in symbols
        for strat in strategies
    }
    # One event log per symbol (all strategies share the file, tagged per event)
    elogs: dict[str, PaperEventLog] = {sym: PaperEventLog(sym) for sym in symbols}

    # ORB one-trade-per-day enforcement (persisted across restarts)
    orb_traded: dict[str, date] = _load_orb_traded(symbols)

    acc_id: int | None = None
    daily = DailyTracker()
    consecutive_errors = 0
    _was_market_open: bool = False
    _session_day: date = clock.today()
    _reconcile_counter: int = 0
    _RECONCILE_EVERY: int = 15  # poll cycles (~15 min)

    for (sym, strat), pos in positions.items():
        if pos:
            elogs[sym].info(
                f"recovered_position entry={pos.entry_price} stop={pos.stop_price} qty={pos.qty}",
                strategy=strat,
            )

    # --- Startup: reconcile local position state against broker ---
    has_local_positions = any(p is not None for p in positions.values())
    if has_local_positions:
        log.info("Local positions found — reconciling against broker state...")
        try:
            with trade_context() as tctx:
                startup_acc_id = _get_simulate_acc_id(tctx)
                _reconcile_positions(tctx, startup_acc_id, positions, elogs)
                acc_id = startup_acc_id
        except Exception as e:
            log.warning("Startup reconciliation failed (%s) — proceeding with local state", e)
    else:
        log.info("No local positions to reconcile — starting fresh")

    while True:
        _is_market_open = clock.is_market_open()
        today = clock.today()

        # New calendar day — heartbeat so you know it's alive
        if today != _session_day:
            _session_day = today
            notify(f"[PAPER] New session {today} | {', '.join(symbols)} | {', '.join(strategies)}")

        # Market just closed — post EOD summary
        if _was_market_open and not _is_market_open:
            _trigger_eod_summary()
        _was_market_open = _is_market_open

        if not _is_market_open:
            secs = clock.seconds_until_open()
            log.info("Market closed — sleeping %.0f min until near open", secs / 60)
            clock.sleep(max(secs, POLL_SECONDS))
            continue

        if not trading_allowed():
            log.info("Trading blocked — waiting")
            clock.sleep(POLL_SECONDS)
            continue

        try:
            with trade_context() as tctx:
                if acc_id is None:
                    acc_id = _get_simulate_acc_id(tctx)

                _reconcile_counter += 1
                if _reconcile_counter >= _RECONCILE_EVERY:
                    _reconcile_counter = 0
                    # Run even with no local positions — catches orphaned broker
                    # positions (e.g. an exit the runner believes happened but didn't).
                    _reconcile_positions(tctx, acc_id, positions, elogs)

                for symbol in symbols:
                    _eval_symbol_all_strategies(
                        symbol, strategies, tctx, acc_id, positions, elogs, daily,
                        orb_traded=orb_traded,
                    )

        except KeyboardInterrupt:
            log.info("Multi runner stopped by user")
            notify("[PAPER] Multi runner stopped")
            break
        except Exception as e:
            consecutive_errors += 1
            log.error("Multi loop error #%d: %s", consecutive_errors, e, exc_info=True)
            for elog in elogs.values():
                elog.error(str(e))
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                log.warning("%d errors — backing off %ds", consecutive_errors, BACKOFF_SECONDS)
                notify(f"[PAPER] {consecutive_errors} errors, backing off {BACKOFF_SECONDS}s")
                clock.sleep(BACKOFF_SECONDS)
                consecutive_errors = 0
                continue
        else:
            consecutive_errors = 0

        clock.sleep(POLL_SECONDS)


def _eval_symbol_all_strategies(
    symbol: str,
    strategies: list[str],
    tctx,
    acc_id: int,
    positions: dict[tuple[str, str], PaperPosition | None],
    elogs: dict[str, PaperEventLog],
    daily: DailyTracker,
    orb_traded: dict[str, date] | None = None,
) -> None:
    """Fetch candles once for symbol, then evaluate each active strategy."""
    elog = elogs[symbol]

    df_raw = _latest_closed_candles(symbol)
    if len(df_raw) < 20:
        log.warning("%s: not enough candles (%d)", symbol, len(df_raw))
        return

    # Annotate once per strategy type needed (avoid double compute_signals)
    df_bb: pd.DataFrame | None = None
    df_vwap: pd.DataFrame | None = None

    for strat in strategies:
        if strat == "bb_kdj":
            if df_bb is None:
                df_bb = compute_signals(df_raw)
            positions[(symbol, strat)] = _eval_bb_kdj(
                symbol, df_bb, tctx, acc_id,
                positions[(symbol, strat)], elog, daily,
            )
        elif strat == "bb_kdj_loose":
            if df_bb is None:
                df_bb = compute_signals(df_raw)
            positions[(symbol, strat)] = _eval_bb_kdj_loose(
                symbol, df_bb, tctx, acc_id,
                positions[(symbol, strat)], elog, daily,
            )
        elif strat == "vwap":
            if df_vwap is None:
                df_vwap = compute_vwap_signals(df_raw)
            positions[(symbol, strat)] = _eval_vwap(
                symbol, df_vwap, tctx, acc_id,
                positions[(symbol, strat)], elog, daily,
            )
        elif strat == "orb":
            prev_pos = positions[(symbol, strat)]
            already_entered = (orb_traded or {}).get(symbol) == clock.today()
            positions[(symbol, strat)] = _eval_orb(
                symbol, df_raw, tctx, acc_id,
                prev_pos, elog, daily,
                already_entered=already_entered,
            )
            # New position just opened — persist the traded date so restarts can't re-enter
            if prev_pos is None and positions[(symbol, strat)] is not None:
                if orb_traded is not None:
                    orb_traded[symbol] = clock.today()
                    _save_orb_traded(symbol, clock.today())
        elif strat == "vwap_pb":
            if df_bb is None:
                df_bb = compute_signals(df_raw)
            positions[(symbol, strat)] = _eval_vwap_pb(
                symbol, df_bb, tctx, acc_id,
                positions[(symbol, strat)], elog, daily,
            )
        else:
            log.warning("Unknown strategy '%s' — skipping", strat)


# ---------------------------------------------------------------------------
# Single-symbol entry point (backward compat)
# ---------------------------------------------------------------------------

def run(symbol: str | None = None) -> None:
    """Single-symbol paper runner. Wraps run_multi for backward compatibility."""
    symbol = symbol or cfg.symbol
    run_multi(symbols=[symbol])
