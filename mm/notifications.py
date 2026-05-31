"""Optional Discord webhook notifications."""
import json
import urllib.request

from .config import cfg
from .logger import get_logger

log = get_logger("notifications")


def _post(payload: dict) -> None:
    if not cfg.discord_webhook_url:
        return
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        cfg.discord_webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as e:
        log.warning("Discord notification failed: %s", e)


def notify(message: str) -> None:
    log.debug("notify: %s", message)
    _post({"content": message})


def notify_entry(symbol: str, price: float, stop: float) -> None:
    notify(f"[PAPER] ENTRY {symbol} @ {price:.4f}  stop={stop:.4f}")


def notify_exit(symbol: str, price: float, reason: str, pnl: float) -> None:
    sign = "+" if pnl >= 0 else ""
    notify(f"[PAPER] EXIT  {symbol} @ {price:.4f}  reason={reason}  pnl={sign}{pnl:.4f}")
