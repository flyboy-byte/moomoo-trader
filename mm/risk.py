"""Safety checks run before any order is placed."""
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import clock
from . import config as _config
from .clock import is_market_open as market_open
from .clock import seconds_until_open
from .logger import get_logger

# Re-export so existing callers (paper.py, tests) importing from risk still work.
__all__ = ["market_open", "seconds_until_open"]

log = get_logger("risk")

_KILL_SWITCH = Path(__file__).parent.parent / "STOP_TRADING.txt"


def kill_switch_active() -> bool:
    if _KILL_SWITCH.exists():
        log.warning("Kill switch active: %s exists — no orders will be placed", _KILL_SWITCH)
        return True
    return False


def live_trading_blocked() -> bool:
    if _config.cfg.live_trading_enabled:
        log.error("LIVE_TRADING_ENABLED=true in config — refusing to proceed (set to false)")
        return True
    return False


def trading_allowed() -> bool:
    """Return True only if every safety check passes."""
    if live_trading_blocked():
        return False
    if kill_switch_active():
        return False
    return True


def calc_qty(price: float, symbol: str | None = None) -> int:
    """Return share count within position dollar cap. Returns 0 if one share exceeds the cap.

    Uses SYMBOL_SIZE_OVERRIDES for the given symbol if set, else MAX_POSITION_DOLLARS.
    """
    if price <= 0:
        return 0
    cfg = _config.cfg
    cap = cfg.symbol_size_overrides.get(symbol, cfg.max_position_dollars) if symbol else cfg.max_position_dollars
    return math.floor(cap / price)


def calc_qty_risk(price: float, stop_price: float, risk_dollars: float,
                  cap_dollars: float) -> int:
    """Risk-normalized share count: every trade risks ~risk_dollars to its stop.

        qty = risk_dollars / (entry - stop)   capped by cap_dollars / price

    Tight stops (low-vol days, tight ORB ranges) get more shares; wide stops get
    fewer — equalizing dollar risk per trade instead of dollar exposure. The
    dollar cap still bounds total position size. Returns 0 (no trade) when the
    stop distance is zero/negative or one share already exceeds the cap.
    """
    if price <= 0 or risk_dollars <= 0:
        return 0
    dist = abs(price - stop_price)
    if dist <= 0:
        return 0
    qty = math.floor(risk_dollars / dist)
    max_qty = math.floor(cap_dollars / price) if cap_dollars > 0 else qty
    return max(0, min(qty, max_qty))


def calc_qty_fractional(price: float, dollars: float) -> float:
    """Return fractional share count for a given dollar allocation.

    Used when TOTAL_CAPITAL is set and FRACTIONAL_SHARES=true.
    Returns a float qty — Moomoo converts qty to float internally and supports fractional shares.
    Rounds to 6 decimal places to avoid floating-point noise in order submissions.
    """
    if price <= 0 or dollars <= 0:
        return 0.0
    return round(dollars / price, 6)


def per_slot_dollars(n_symbols: int, n_strategies: int) -> float:
    """Compute per-position dollar allocation from TOTAL_CAPITAL.

    Divides total capital equally across all (symbol, strategy) slots.
    Returns 0.0 if TOTAL_CAPITAL is not set.
    """
    cfg = _config.cfg
    if cfg.total_capital <= 0:
        return 0.0
    n_slots = max(1, n_symbols * n_strategies)
    dollars = cfg.total_capital / n_slots
    log.info("Capital allocation: $%.2f / %d slots = $%.4f per position",
             cfg.total_capital, n_slots, dollars)
    return dollars


@dataclass
class DailyTracker:
    """Tracks per-day trade count and realized PnL. Resets automatically on a new calendar day.

    Enforces two limits:
    - Global: MAX_TRADES_PER_DAY across all strategies combined.
    - Per-strategy: MAX_TRADES_PER_STRATEGY per strategy (0 = disabled).
    """
    _day: date = field(default_factory=clock.today)
    _trades: int = 0
    _pnl: float = 0.0
    _strategy_trades: dict = field(default_factory=dict)  # {strategy: trade_count}

    def _maybe_reset(self) -> None:
        today = clock.today()
        if today != self._day:
            log.info("New trading day %s — resetting daily counters (prev: %d trades, pnl=%.4f)",
                     today, self._trades, self._pnl)
            self._day = today
            self._trades = 0
            self._pnl = 0.0
            self._strategy_trades = {}

    @property
    def trades(self) -> int:
        self._maybe_reset()
        return self._trades

    @property
    def pnl(self) -> float:
        self._maybe_reset()
        return self._pnl

    def can_open(self, strategy: str = "") -> bool:
        """Return True if both global and per-strategy limits allow a new entry."""
        self._maybe_reset()
        cfg = _config.cfg
        if cfg.max_trades_per_day > 0 and self._trades >= cfg.max_trades_per_day:
            log.warning("Daily trade limit reached (%d/%d) — no new entries",
                        self._trades, cfg.max_trades_per_day)
            return False
        if self._pnl <= -abs(cfg.max_daily_loss):
            log.warning("Daily loss limit reached (pnl=%.4f limit=%.4f) — no new entries",
                        self._pnl, -cfg.max_daily_loss)
            return False
        if strategy and cfg.max_trades_per_strategy > 0:
            strat_count = self._strategy_trades.get(strategy, 0)
            if strat_count >= cfg.max_trades_per_strategy:
                log.warning("Per-strategy limit reached [%s] (%d/%d) — no new entries",
                            strategy, strat_count, cfg.max_trades_per_strategy)
                return False
        return True

    def record_trade(self, pnl: float, strategy: str = "") -> None:
        self._maybe_reset()
        cfg = _config.cfg
        self._trades += 1
        self._pnl += pnl
        if strategy:
            self._strategy_trades[strategy] = self._strategy_trades.get(strategy, 0) + 1
        log.info("Daily stats: trades=%d/%d  pnl=%.4f/%.4f  strategy_trades=%s",
                 self._trades, cfg.max_trades_per_day, self._pnl, -cfg.max_daily_loss,
                 self._strategy_trades)


# ---------------------------------------------------------------------------
# Per-position sizing — set at run_multi() startup, read by evals
# ---------------------------------------------------------------------------

# Set at startup from TOTAL_CAPITAL / (n_symbols * n_strategies). 0 = not set.
_slot_dollars: float = 0.0


def _position_cap(symbol: str) -> float:
    """Dollar cap for a single position — slot dollars if capital mode, else per-symbol cap."""
    if _slot_dollars > 0:
        return _slot_dollars
    return _config.cfg.symbol_size_overrides.get(symbol, _config.cfg.max_position_dollars)


def _qty(price: float, symbol: str, stop: float | None = None) -> int | float:
    """Return order qty using risk-normalized, fractional, or whole-share logic.

    When RISK_DOLLARS_PER_TRADE is set and the caller provides the stop price:
    qty = risk_dollars / stop_distance, capped by the position dollar cap —
    every trade risks the same dollars regardless of volatility.

    Else, when TOTAL_CAPITAL is set and FRACTIONAL_SHARES=true: returns float qty
    derived from the pre-computed per-slot dollar allocation.
    Falls back to whole-share calc_qty() when fractional result < 1 — Moomoo
    rejects sub-share orders with "Invalid quantity" and the trade is silently lost.
    Also falls back when TOTAL_CAPITAL is not set or FRACTIONAL_SHARES=false.
    """
    if _config.cfg.risk_dollars_per_trade > 0 and stop is not None:
        return calc_qty_risk(price, stop, _config.cfg.risk_dollars_per_trade, _position_cap(symbol))
    if _slot_dollars > 0 and _config.cfg.fractional_shares:
        qty = calc_qty_fractional(price, _slot_dollars)
        if qty >= 1:
            return qty
        log.warning("Fractional qty %.6f < 1 for %s at %.2f — falling back to whole-share",
                    qty, symbol, price)
    return calc_qty(price, symbol)
