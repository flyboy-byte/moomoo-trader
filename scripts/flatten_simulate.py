"""Flatten orphaned simulate-account positions.

Compares the broker's open positions against the paper runner's local position
state and sells any untracked (orphaned) shares — leftovers from exits that
never filled before fill-confirmation was added (see CLAUDE.md finding 15/16).

Dry-run by default. Market must be open for orders to fill.

  python scripts/flatten_simulate.py          # show what would be sold
  python scripts/flatten_simulate.py --yes    # actually place the sell orders
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from moomoo import (  # noqa: E402
    OpenSecTradeContext, RET_OK, TrdEnv, TrdMarket, TrdSide, OrderType, SecurityFirm,
)

from mm.config import cfg  # noqa: E402
from mm.risk import market_open  # noqa: E402

MARKETABLE_BUFFER = 0.005  # sell 0.5% below last price so the limit fills immediately


def _tracked_qty() -> dict[str, float]:
    """Sum locally-tracked open qty per symbol across all strategy position files."""
    tracked: dict[str, float] = {}
    for path in cfg.logs_dir.glob("paper_*_position.json"):
        try:
            d = json.loads(path.read_text())
            tracked[d["symbol"]] = tracked.get(d["symbol"], 0.0) + float(d["qty"])
        except Exception as e:
            print(f"  WARNING: could not read {path.name}: {e}")
    return tracked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="place orders (default: dry run)")
    args = ap.parse_args()

    tctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.US, host=cfg.host,
                               port=cfg.port, security_firm=SecurityFirm.FUTUINC)
    try:
        ret, accs = tctx.get_acc_list()
        if ret != RET_OK:
            sys.exit(f"get_acc_list failed: {accs}")
        acc = int(accs[accs["trd_env"] == TrdEnv.SIMULATE].iloc[0]["acc_id"])

        ret, pos = tctx.position_list_query(trd_env=TrdEnv.SIMULATE, acc_id=acc)
        if ret != RET_OK:
            sys.exit(f"position_list_query failed: {pos}")
        if pos.empty:
            print("Broker shows no open positions — nothing to flatten.")
            return

        tracked = _tracked_qty()
        print(f"Locally tracked open qty: {tracked or 'none'}\n")

        orders = []
        for _, row in pos.iterrows():
            sym = str(row["stock_code"])
            qty = float(row["qty"])
            orphan = qty - tracked.get(sym, 0.0)
            price = float(row["nominal_price"])
            status = f"orphaned {orphan:g} of {qty:g}" if orphan > 0 else "fully tracked"
            print(f"  {sym}: qty={qty:g} cost={float(row['cost_price']):.2f} "
                  f"last={price:.2f} — {status}")
            if orphan > 0:
                orders.append((sym, orphan, round(price * (1 - MARKETABLE_BUFFER), 2)))

        if not orders:
            print("\nNo orphaned shares.")
            return

        if not args.yes:
            print(f"\nDry run — would SELL: {orders}\nRe-run with --yes to execute.")
            return

        if not market_open():
            sys.exit("\nMarket is closed — orders would pend/cancel. Run during RTH.")

        for sym, qty, limit in orders:
            ret, data = tctx.place_order(price=limit, qty=qty, code=sym,
                                         trd_side=TrdSide.SELL, order_type=OrderType.NORMAL,
                                         trd_env=TrdEnv.SIMULATE, acc_id=acc)
            if ret != RET_OK:
                print(f"  SELL {sym} x{qty:g} FAILED: {data}")
                continue
            order_id = str(data["order_id"].iloc[0])
            print(f"  SELL {sym} x{qty:g} @ {limit} placed (order {order_id})", end="", flush=True)
            for _ in range(10):
                time.sleep(2)
                ret, df = tctx.order_list_query(order_id=order_id,
                                                trd_env=TrdEnv.SIMULATE, acc_id=acc)
                if ret == RET_OK and not df.empty and str(df.iloc[0]["order_status"]) == "FILLED_ALL":
                    print(f" — FILLED at {float(df.iloc[0]['dealt_avg_price']):.2f}")
                    break
            else:
                print(" — not confirmed filled yet, check the app")
    finally:
        tctx.close()


if __name__ == "__main__":
    main()
