"""Time and market-hours seam — the single patch point for replay and tests.

All time-dependent code in the mm package calls through here instead of the
stdlib directly. The replay harness and unit tests replace these module-level
functions to simulate an arbitrary wall clock without touching individual
modules.

Import graph: clock ← events ← execution ← evals ← paper(loop)
              risk imports clock; nothing imports paper.
"""
import time as _time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_OPEN = (9, 30)
_CLOSE = (16, 0)


def now() -> datetime:
    """Current local time (naive)."""
    return datetime.now()


def now_et() -> datetime:
    """Current ET time (tzinfo stripped — candle timestamps are naive ET)."""
    return datetime.now(_ET).replace(tzinfo=None)


def today() -> date:
    """Current local date."""
    return date.today()


def monotonic() -> float:
    """Monotonic clock for timeout arithmetic."""
    return _time.monotonic()


def sleep(seconds: float) -> None:
    _time.sleep(seconds)


def is_market_open() -> bool:
    """True if US equity market is open (Mon-Fri 09:30-16:00 ET)."""
    n = now_et()
    if n.weekday() >= 5:
        return False
    t = (n.hour, n.minute)
    return _OPEN <= t < _CLOSE


def seconds_until_open() -> float:
    """Seconds until next market open (2 min early warm-up buffer)."""
    n = now_et()
    if is_market_open():
        return 0.0
    candidate = n.replace(hour=9, minute=28, second=0, microsecond=0)
    if n >= n.replace(hour=9, minute=30, second=0, microsecond=0):
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return max(60.0, (candidate - n).total_seconds())
