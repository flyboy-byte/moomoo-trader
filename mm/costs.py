"""Transaction cost model — the ruler that was missing.

Every engine in this repo (backtest, replay, and the SIMULATE paper runner) reports
frictionless fills. The 2026-08-29 audit showed why that matters: the live portfolio's
trade-count-weighted return was +1.31 bps across 106 trades, against this project's own
stated round-trip cost estimate of 1-3 bps. In other words the entire measured "edge"
was inside its own cost of trading, and no report said so.

This module is the single place that answer lives. Reporting applies it now
(scripts/analyze_trades.py); the Goal B wide scan applies the same model so wide-scan
results and live results stay comparable. See docs/research-reset.md.

DELIBERATE DESIGN CHOICES
-------------------------
1. **Self-contained constants, no cfg import.** Same pattern as mm/gap_fade.py. Costs are
   a property of the market and the broker, not a strategy knob, and they must not become
   something that gets quietly tuned until results look good. Changing a number here is a
   visible edit to a file whose whole purpose is to be pessimistic.

2. **One round-trip number per symbol, not a spread/slippage/commission decomposition.**
   We cannot observe bid-ask from 5-min OHLC bars, so a decomposition would be false
   precision. One honest, conservative aggregate is better than three invented components.

3. **Sensitivity over point estimates.** The right cost is genuinely uncertain, so the
   reporting layer sweeps a range (see COST_SCENARIOS) rather than arguing for one value.
   "The edge dies above 2 bps" is a far more useful statement than "PF is 1.09".

4. **Pessimistic defaults.** An optimistic cost model invalidates everything downstream.
   Where uncertain, this module rounds against the strategy.

WHY THE DEFAULTS ARE WHAT THEY ARE
-----------------------------------
Raw quoted spread on SPY is ~1c on a ~$766 price = ~0.13 bps, which would suggest costs
are negligible. They are not, for two reasons this model folds into one number:

  - These strategies place LIMIT orders. A resting limit is adversely selected: it fills
    precisely when the market is moving through it. The realized cost of a passive fill is
    therefore worse than the half-spread it appears to earn, and this does not show up in
    any bar-based simulation.
  - Fills in the replay/backtest engines are resolved against the NEXT bar's OHLC, which
    is optimistic about intra-bar path.

So the defaults below are not quoted spreads; they are all-in round-trip frictions in the
range this project already documented for itself (1-3 bps for the liquid ETFs).

Single names are NOT the same regime — a $50 stock with a 1c spread is ~2 bps of spread
alone before any adverse selection. This is load-bearing for Goal B: a strategy scraping
+1.3 bps on SPY may be structurally impossible on single stocks, and a per-symbol model is
the only way to see that rather than discover it after spending API quota.
"""
from __future__ import annotations

# Round-trip cost in basis points of notional, per symbol.
# Covers spread crossing + adverse selection on passive fills + slippage. Entry and exit
# together — do NOT apply this twice per trade.
SYMBOL_ROUND_TRIP_BPS: dict[str, float] = {
    "US.SPY": 1.5,
    "US.QQQ": 1.5,
    "US.IWM": 2.5,   # lower price, wider relative spread than SPY/QQQ
}

# Anything not listed above. Deliberately pessimistic: an unknown symbol is assumed to be
# a single name with a materially worse cost profile than the three index ETFs this
# project was built on. Goal B should replace this with measured per-symbol values before
# any wide-scan result is treated as evidence.
DEFAULT_ROUND_TRIP_BPS: float = 5.0

# Per-trade commission in dollars (round trip). Moomoo's US equities tier is
# commission-free, so this is 0.0 — but it is here as an explicit, visible zero rather
# than an unstated assumption, and so a future real-money analysis can set it.
COMMISSION_PER_TRADE: float = 0.0

# Cost levels the reporting layer sweeps, so results are read as a curve rather than a
# point. 0.0 reproduces the old frictionless numbers for continuity.
COST_SCENARIOS: tuple[float, ...] = (0.0, 1.0, 2.0, 5.0)


def round_trip_bps(symbol: str) -> float:
    """All-in round-trip cost for `symbol`, in bps of notional."""
    return SYMBOL_ROUND_TRIP_BPS.get(symbol, DEFAULT_ROUND_TRIP_BPS)


def trade_cost(
    symbol: str,
    entry_price: float,
    qty: float,
    *,
    bps_override: float | None = None,
) -> float:
    """Dollar cost of one complete round trip (entry + exit).

    Charged on entry notional. Using entry rather than average notional slightly
    understates cost on winners and overstates on losers; the difference is second-order
    next to the uncertainty in the bps figure itself, and entry notional is the one both
    the live logs and the backtest engines always have.

    `bps_override` lets the reporting layer sweep COST_SCENARIOS without mutating module
    state (which would not be thread- or test-safe).
    """
    if entry_price <= 0 or qty <= 0:
        return 0.0
    bps = round_trip_bps(symbol) if bps_override is None else bps_override
    notional = entry_price * qty
    return notional * (bps / 10_000.0) + COMMISSION_PER_TRADE


def net_pnl(
    gross_pnl: float,
    symbol: str,
    entry_price: float,
    qty: float,
    *,
    bps_override: float | None = None,
) -> float:
    """Gross PnL minus round-trip cost. Costs always reduce PnL regardless of direction."""
    return gross_pnl - trade_cost(symbol, entry_price, qty, bps_override=bps_override)


def net_bps(
    gross_pnl: float,
    symbol: str,
    entry_price: float,
    qty: float,
    *,
    bps_override: float | None = None,
) -> float | None:
    """Net return on entry notional, in bps. None when notional is unknown/zero.

    This is the number that actually matters for a strategy holding minutes: it is
    directly comparable to the cost hurdle, unlike dollar PnL at 1-share sizing.
    """
    if entry_price <= 0 or qty <= 0:
        return None
    notional = entry_price * qty
    net = net_pnl(gross_pnl, symbol, entry_price, qty, bps_override=bps_override)
    return net / notional * 10_000.0
