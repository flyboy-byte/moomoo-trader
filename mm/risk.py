"""Safety checks run before any order is placed."""
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .config import cfg
from .logger import get_logger

log = get_logger("risk")

_KILL_SWITCH = Path(__file__).parent.parent / "STOP_TRADING.txt"


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


def calc_qty(price: float) -> int:
    """Return share count within MAX_POSITION_DOLLARS. Returns 0 if one share exceeds the cap."""
    if price <= 0:
        return 0
    return math.floor(cfg.max_position_dollars / price)


@dataclass
class DailyTracker:
    """Tracks per-day trade count and realized PnL. Resets automatically on a new calendar day."""
    _day: date = field(default_factory=date.today)
    _trades: int = 0
    _pnl: float = 0.0

    def _maybe_reset(self) -> None:
        today = date.today()
        if today != self._day:
            log.info("New trading day %s — resetting daily counters (prev: %d trades, pnl=%.4f)", today, self._trades, self._pnl)
            self._day = today
            self._trades = 0
            self._pnl = 0.0

    @property
    def trades(self) -> int:
        self._maybe_reset()
        return self._trades

    @property
    def pnl(self) -> float:
        self._maybe_reset()
        return self._pnl

    def can_open(self) -> bool:
        self._maybe_reset()
        if self._trades >= cfg.max_trades_per_day:
            log.warning("Daily trade limit reached (%d/%d) — no new entries", self._trades, cfg.max_trades_per_day)
            return False
        if self._pnl <= -abs(cfg.max_daily_loss):
            log.warning("Daily loss limit reached (pnl=%.4f limit=%.4f) — no new entries", self._pnl, -cfg.max_daily_loss)
            return False
        return True

    def record_trade(self, pnl: float) -> None:
        self._maybe_reset()
        self._trades += 1
        self._pnl += pnl
        log.info("Daily stats: trades=%d/%d  pnl=%.4f/%.4f", self._trades, cfg.max_trades_per_day, self._pnl, -cfg.max_daily_loss)
