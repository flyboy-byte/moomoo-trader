"""Order execution layer — placement, fill confirmation, reconcile.

Contains:
- trade_context()     — OpenSecTradeContext context manager
- _place_buy/sell/short/cover — raw order placement with market-hours guard
- _confirm_fill()     — poll until fill, terminal, or timeout
- _cancel_order()     — cancel with exception handling
- _execute_entry()    — place + confirm entry; return fill or None
- _execute_exit()     — marketable exit with buffer retry; return fill or None
- _order_status()     — single order status lookup
- _reconcile_positions() — compare local vs broker state; clear ghosts
"""
import math
from contextlib import contextmanager

from moomoo import (
    OpenSecTradeContext,
    RET_OK,
    TrdEnv,
    TrdMarket,
    TrdSide,
    OrderType,
)

from . import clock
from . import config as _config
from .events import PaperEventLog, PaperPosition, _clear_position
from .logger import get_logger
from .notifications import notify

log = get_logger("paper")


# ---------------------------------------------------------------------------
# Reconcile helpers
# ---------------------------------------------------------------------------

_RECONCILE_GRACE_MINUTES = 30
_orphan_warned: set[str] = set()

_FILLED_STATUSES = {"FILLED_ALL", "FILLED_PART"}
_PENDING_STATUSES = {"WAITING_SUBMIT", "SUBMITTING", "SUBMITTED", "NONE", "UNSUBMITTED"}


def _order_status(tctx, acc_id: int, order_id: str) -> str | None:
    """Return the broker's status string for an order, or None if unknown."""
    if not order_id:
        return None
    try:
        ret, df = tctx.order_list_query(order_id=str(order_id),
                                        trd_env=TrdEnv.SIMULATE, acc_id=acc_id)
    except Exception as e:
        log.warning("order_list_query failed for %s: %s", order_id, e)
        return None
    if ret != RET_OK or df.empty:
        return None
    return str(df.iloc[0]["order_status"])


def _reconcile_positions(
    tctx, acc_id: int,
    positions: dict[tuple[str, str], "PaperPosition | None"],
    elogs: dict[str, "PaperEventLog"],
) -> None:
    """Compare local position state against the broker's actual open positions.

    If the broker shows no position for a symbol where we have local state,
    check the entry order's status before assuming the trade is a ghost:
    limit orders placed at candle close can sit pending for minutes (SIMULATE
    fill latency), and position_list_query can lag a fresh fill. Clearing in
    that window orphans a real position with no exit management (this happened
    live 2026-06-10: order pended 5.5 min, reconcile cleared at minute 4).

    - Order filled       → keep local state (position list is lagging).
    - Order pending and position younger than grace → keep, fill may come.
    - Order pending past grace → cancel order, clear (entry never happened).
    - Order cancelled/failed/unknown → clear (genuine ghost).
    """
    import pandas as pd
    try:
        ret, df = tctx.position_list_query(trd_env=TrdEnv.SIMULATE, acc_id=acc_id)
    except Exception as e:
        log.warning("Broker reconciliation failed (will use local state): %s", e)
        return

    if ret != RET_OK:
        log.warning("Broker reconciliation: position_list_query failed — %s", df)
        return

    sym_col = "code" if "code" in df.columns else "stock_code"
    broker_syms: set[str] = set()
    if not df.empty and sym_col in df.columns:
        for _, row in df.iterrows():
            if float(row.get("qty", 0)) != 0:
                broker_syms.add(str(row[sym_col]))

    now_et = clock.now_et()

    any_local = False
    for (sym, strat), pos in list(positions.items()):
        if pos is None:
            continue
        any_local = True
        if sym not in broker_syms:
            # Broker shows zero net for this symbol. Before concluding it's a ghost,
            # check if another strategy on the same symbol has a FILLED order —
            # that means offsetting long+short positions net to 0, which is valid
            # (e.g. BB+KDJ long SPY + ORB short SPY). Clearing either position in
            # that scenario would leave a stranded unmanaged trade.
            other_filled = any(
                p is not None and p.order_id and
                _order_status(tctx, acc_id, p.order_id) in _FILLED_STATUSES
                for (osym, ostrat), p in positions.items()
                if osym == sym and ostrat != strat
            )
            if other_filled:
                log.info("RECONCILE SKIP [%s/%s]: broker net=0 but another strategy on %s "
                         "has FILLED order — treating as offsetting positions, keeping",
                         sym, strat, sym)
                continue

            status = _order_status(tctx, acc_id, pos.order_id)
            age_min = (now_et - pd.Timestamp(pos.entry_time).to_pydatetime()).total_seconds() / 60

            if status in _FILLED_STATUSES:
                log.info("RECONCILE OK [%s/%s]: order %s is %s — position list lagging, keeping",
                         sym, strat, pos.order_id, status)
                continue
            if (status in _PENDING_STATUSES or (status is None and pos.order_id)) \
                    and age_min < _RECONCILE_GRACE_MINUTES:
                log.info("RECONCILE WAIT [%s/%s]: entry order %s status=%s (%.0f min old) — keeping",
                         sym, strat, pos.order_id, status, age_min)
                continue
            if status in _PENDING_STATUSES:
                try:
                    from moomoo import ModifyOrderOp
                    tctx.modify_order(ModifyOrderOp.CANCEL, pos.order_id, 0, 0,
                                      trd_env=TrdEnv.SIMULATE, acc_id=acc_id)
                    log.warning("RECONCILE: cancelled stale pending entry order %s", pos.order_id)
                except Exception as e:
                    log.error("RECONCILE: failed to cancel stale order %s: %s — cancel manually",
                              pos.order_id, e)

            msg = (f"RECONCILE MISMATCH [{sym}/{strat}]: local entry={pos.entry_price:.4f} "
                   f"but broker has no {sym} position (order status={status}) — clearing")
            log.error(msg)
            elogs[sym].error(
                f"reconcile_mismatch strat={strat} local_entry={pos.entry_price} "
                f"order_status={status} cleared",
                strategy=strat,
            )
            notify(f"[PAPER] CRITICAL: {msg}")
            _clear_position(sym, strat)
            positions[(sym, strat)] = None
        else:
            log.info("RECONCILE OK [%s/%s]: broker confirms %s position", sym, strat, sym)

    for bsym in broker_syms:
        if not any(sym == bsym and pos is not None for (sym, _), pos in positions.items()):
            if bsym not in _orphan_warned:
                _orphan_warned.add(bsym)
                log.warning(
                    "RECONCILE WARNING: broker has %s position but no local state — investigate manually", bsym
                )

    if not any_local:
        log.debug("RECONCILE: no local positions to verify")


# ---------------------------------------------------------------------------
# Trade context
# ---------------------------------------------------------------------------

@contextmanager
def trade_context():
    ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host=_config.cfg.host,
        port=_config.cfg.port,
    )
    try:
        yield ctx
    finally:
        ctx.close()


def _get_simulate_acc_id(ctx: OpenSecTradeContext) -> int:
    ret, data = ctx.get_acc_list()
    if ret != RET_OK:
        log.error("get_acc_list failed: %s", data)
        return 0
    sim_rows = data[data["trd_env"] == TrdEnv.SIMULATE]
    if sim_rows.empty:
        log.warning("No SIMULATE account found — using acc_id=0")
        return 0
    return int(sim_rows.iloc[0]["acc_id"])


# ---------------------------------------------------------------------------
# Raw order placement with market-hours guard
# ---------------------------------------------------------------------------

def _place_buy(ctx, acc_id: int, symbol: str, price: float, qty: int) -> str:
    if not clock.is_market_open():
        log.error("Order refused (market closed): BUY %s", symbol)
        return ""
    price = round(price, 2)
    ret, data = ctx.place_order(
        price=price, qty=qty, code=symbol,
        trd_side=TrdSide.BUY, order_type=OrderType.NORMAL,
        trd_env=TrdEnv.SIMULATE, acc_id=acc_id,
    )
    if ret == RET_OK:
        order_id = str(data["order_id"].iloc[0])
        log.info("BUY  %s qty=%s price=%.4f order_id=%s", symbol, qty, price, order_id)
        return order_id
    log.error("BUY failed: %s", data)
    return ""


def _place_sell(ctx, acc_id: int, symbol: str, price: float, qty: int) -> str:
    if not clock.is_market_open():
        log.error("Order refused (market closed): SELL %s", symbol)
        return ""
    price = round(price, 2)
    ret, data = ctx.place_order(
        price=price, qty=qty, code=symbol,
        trd_side=TrdSide.SELL, order_type=OrderType.NORMAL,
        trd_env=TrdEnv.SIMULATE, acc_id=acc_id,
    )
    if ret == RET_OK:
        order_id = str(data["order_id"].iloc[0])
        log.info("SELL %s qty=%s price=%.4f order_id=%s", symbol, qty, price, order_id)
        return order_id
    log.error("SELL failed: %s", data)
    return ""


def _place_short(ctx, acc_id: int, symbol: str, price: float, qty: int) -> str:
    if not clock.is_market_open():
        log.error("Order refused (market closed): SELL_SHORT %s", symbol)
        return ""
    price = round(price, 2)
    ret, data = ctx.place_order(
        price=price, qty=qty, code=symbol,
        trd_side=TrdSide.SELL_SHORT, order_type=OrderType.NORMAL,
        trd_env=TrdEnv.SIMULATE, acc_id=acc_id,
    )
    if ret == RET_OK:
        order_id = str(data["order_id"].iloc[0])
        log.info("SELL_SHORT %s qty=%s price=%.4f order_id=%s", symbol, qty, price, order_id)
        return order_id
    log.error("SELL_SHORT failed: %s", data)
    return ""


def _place_cover(ctx, acc_id: int, symbol: str, price: float, qty: int) -> str:
    if not clock.is_market_open():
        log.error("Order refused (market closed): BUY_BACK %s", symbol)
        return ""
    price = round(price, 2)
    ret, data = ctx.place_order(
        price=price, qty=qty, code=symbol,
        trd_side=TrdSide.BUY_BACK, order_type=OrderType.NORMAL,
        trd_env=TrdEnv.SIMULATE, acc_id=acc_id,
    )
    if ret == RET_OK:
        order_id = str(data["order_id"].iloc[0])
        log.info("BUY_BACK %s qty=%s price=%.4f order_id=%s", symbol, qty, price, order_id)
        return order_id
    log.error("BUY_BACK failed: %s", data)
    return ""


# ---------------------------------------------------------------------------
# Fill confirmation and cancellation
# ---------------------------------------------------------------------------

_FILL_TIMEOUT_S = 20
_FILL_POLL_S = 2
_exit_unfilled_notified: set[tuple[str, str]] = set()
_CANCEL_RECHECK_S = 6
_EXIT_BUFFERS = (0.003, 0.01)
_TERMINAL_STATUSES = {"CANCELLED_ALL", "CANCELLED_PART", "FAILED", "DISABLED", "DELETED"}


def _confirm_fill(tctx, acc_id: int, order_id: str,
                  timeout_s: float | None = None) -> tuple[str | None, float, float | None]:
    """Poll an order until filled, terminal, or timeout.

    Returns (status, dealt_qty, dealt_avg_price). dealt_avg_price is None
    if nothing was filled.
    """
    deadline = clock.monotonic() + (timeout_s if timeout_s is not None else _FILL_TIMEOUT_S)
    status: str | None = None
    dealt = 0.0
    price: float | None = None
    while True:
        try:
            ret, df = tctx.order_list_query(order_id=str(order_id),
                                            trd_env=TrdEnv.SIMULATE, acc_id=acc_id)
            if ret == RET_OK and not df.empty:
                row = df.iloc[0]
                status = str(row["order_status"])
                dealt = float(row.get("dealt_qty", 0) or 0)
                price = float(row["dealt_avg_price"]) if dealt > 0 else None
                if status == "FILLED_ALL" or status in _TERMINAL_STATUSES:
                    return status, dealt, price
        except Exception as e:
            log.warning("confirm_fill query failed for order %s: %s", order_id, e)
        if clock.monotonic() >= deadline:
            return status, dealt, price
        clock.sleep(_FILL_POLL_S)


def _cancel_order(tctx, acc_id: int, order_id: str) -> bool:
    try:
        from moomoo import ModifyOrderOp
        ret, data = tctx.modify_order(ModifyOrderOp.CANCEL, order_id, 0, 0,
                                      trd_env=TrdEnv.SIMULATE, acc_id=acc_id)
        if ret == RET_OK:
            return True
        log.error("Cancel failed for order %s: %s", order_id, data)
    except Exception as e:
        log.error("Cancel exception for order %s: %s", order_id, e)
    return False


def _execute_entry(tctx, acc_id: int, symbol: str, qty: int | float, intended: float,
                   strategy: str, elog: "PaperEventLog",
                   direction: str = "long") -> tuple[str, float, float] | None:
    """Place an entry limit at the signal price and wait for the fill.

    Returns (order_id, fill_price, fill_qty) on a confirmed fill. Returns None
    if the order failed or didn't fill in the window — the order is cancelled
    and NO position exists. Chasing a moved price is not the strategy's signal.
    """
    side = "SELL_SHORT" if direction == "short" else "BUY"
    place = _place_short if direction == "short" else _place_buy
    elog.order_attempt(side, qty, intended, strategy=strategy)
    order_id = place(tctx, acc_id, symbol, intended, qty)
    elog.order_result(side, success=bool(order_id), order_id=order_id, strategy=strategy)
    if not order_id:
        return None

    status, dealt, fill = _confirm_fill(tctx, acc_id, order_id)
    if dealt <= 0:
        _cancel_order(tctx, acc_id, order_id)
        status, dealt, fill = _confirm_fill(tctx, acc_id, order_id, timeout_s=_CANCEL_RECHECK_S)
    if dealt > 0 and fill is not None:
        slip = (fill - intended) / intended * 10000
        log.info("%-8s [%s] entry fill confirmed %.4f (intended %.4f, slip %+.1f bps)",
                 symbol, strategy, fill, intended, slip)
        return order_id, fill, dealt

    log.warning("%-8s [%s] entry order %s not filled (status=%s) — no trade",
                symbol, strategy, order_id, status)
    elog.signal_skip("entry_unfilled", score=0, bonus=0, min_score=0, strategy=strategy)
    return None


def _execute_exit(tctx, acc_id: int, symbol: str, position: "PaperPosition",
                  intended: float, reason: str, elog: "PaperEventLog") -> float | None:
    """Place a marketable exit limit and wait for the fill.

    Sells slightly below / covers slightly above the candle close so the limit
    is immediately marketable (the close is minutes stale; a sell above market
    pends and dies at EOD — proven live 2026-06-04). Returns the actual fill
    price, or None if the exit could not be executed — the caller must keep
    the position open and retry on the next poll.
    """
    is_short = position.direction == "short"
    side = "BUY_BACK" if is_short else "SELL"
    place = _place_cover if is_short else _place_sell

    for buf in _EXIT_BUFFERS:
        limit = intended * (1 + buf) if is_short else intended * (1 - buf)
        elog.order_attempt(side, position.qty, limit, strategy=position.strategy)
        order_id = place(tctx, acc_id, symbol, limit, position.qty)
        elog.order_result(side, success=bool(order_id), order_id=order_id,
                          strategy=position.strategy)
        if not order_id:
            continue
        status, dealt, fill = _confirm_fill(tctx, acc_id, order_id)
        if dealt <= 0:
            _cancel_order(tctx, acc_id, order_id)
            status, dealt, fill = _confirm_fill(tctx, acc_id, order_id, timeout_s=_CANCEL_RECHECK_S)
        if dealt > 0 and fill is not None:
            if dealt < float(position.qty):
                log.warning("%-8s [%s] exit PARTIAL fill %.6f/%.6f at %.4f",
                            symbol, position.strategy, dealt, float(position.qty), fill)
            _exit_unfilled_notified.discard((symbol, position.strategy))
            return fill
        log.warning("%-8s [%s] exit order %s not filled (status=%s, buffer=%.1f%%)",
                    symbol, position.strategy, order_id, status, buf * 100)

    msg = (f"EXIT UNFILLED [{symbol}/{position.strategy}] reason={reason} — "
           f"position stays open, retrying next poll")
    log.error(msg)
    elog.error(f"exit_unfilled reason={reason}", strategy=position.strategy)
    key = (symbol, position.strategy)
    if key not in _exit_unfilled_notified:
        _exit_unfilled_notified.add(key)
        notify(f"[PAPER] CRITICAL: {msg}")
    return None
