"""Safety checks run before any order is placed."""
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import cfg
from .logger import get_logger

log = get_logger("risk")

_KILL_SWITCH = Path(__file__).parent.parent / "STOP_TRADING.txt"
_ET = ZoneInfo("America/New_York")
_OPEN = (9, 30)
_CLOSE = (16, 0)


def market_open() -> bool:
    """Return True if US equity market is currently open (Mon-Fri 9:30-16:00 ET)."""
    now = datetime.now(_ET)
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return _OPEN <= t < _CLOSE


def seconds_until_open() -> float:
    """Return seconds until next market open (2 min early warm-up buffer)."""
    now = datetime.now(_ET)
    if market_open():
        return 0.0
    candidate = now.replace(hour=9, minute=28, second=0, microsecond=0)
    # Only advance to tomorrow if the market has already opened today
    if now >= now.replace(hour=9, minute=30, second=0, microsecond=0):
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return max(60.0, (candidate - now).total_seconds())


def kill_switch_active() -> bool:
    if _KILL_SWITCH.exists():
        log.warning("Kill switch active: %s exists — no orders will be placed", _KILL_SWITCH)
        return True
    return False


def live_trading_blocked() -> bool:
    if cfg.live_trading_enabled:
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
    _day: date = field(default_factory=date.today)
    _trades: int = 0
    _pnl: float = 0.0
    _strategy_trades: dict = field(default_factory=dict)  # {strategy: trade_count}

    def _maybe_reset(self) -> None:
        today = date.today()
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
        if self._trades >= cfg.max_trades_per_day:
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
        self._trades += 1
        self._pnl += pnl
        if strategy:
            self._strategy_trades[strategy] = self._strategy_trades.get(strategy, 0) + 1
        log.info("Daily stats: trades=%d/%d  pnl=%.4f/%.4f  strategy_trades=%s",
                 self._trades, cfg.max_trades_per_day, self._pnl, -cfg.max_daily_loss,
                 self._strategy_trades)
