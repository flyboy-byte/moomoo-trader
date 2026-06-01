import socket
import time
from moomoo import RET_OK

from .config import cfg
from .connection import quote_context
from .logger import get_logger

log = get_logger("health")


def check_socket() -> bool:
    try:
        with socket.create_connection((cfg.host, cfg.port), timeout=3):
            log.info("OpenD socket reachable at %s:%s", cfg.host, cfg.port)
            return True
    except OSError as e:
        log.error("OpenD socket unreachable: %s", e)
        return False


def check_quote(symbol: str = "US.AAPL") -> bool:
    try:
        with quote_context() as ctx:
            ret, data = ctx.get_market_snapshot([symbol])
            if ret == RET_OK:
                price = data["last_price"].iloc[0]
                log.info("Quote OK: %s last_price=%.2f", symbol, price)
                return True
            else:
                log.error("Quote error: %s", data)
                return False
    except Exception as e:
        log.error("Quote check failed: %s", e)
        return False


def run_health_check(retries: int = 6, delay: float = 10.0) -> bool:
    """Run health check with retries to handle OpenD login flapping on startup."""
    for attempt in range(1, retries + 1):
        if check_socket() and check_quote():
            log.info("Health check passed")
            return True
        if attempt < retries:
            log.warning("Health check failed (attempt %d/%d) — retrying in %.0fs", attempt, retries, delay)
            time.sleep(delay)
    log.error("Health check FAILED after %d attempts", retries)
    return False
