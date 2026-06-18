from contextlib import contextmanager

from moomoo import OpenQuoteContext

from . import config as _config
from .logger import get_logger

log = get_logger("connection")

if _config.cfg.host != "127.0.0.1":
    log.warning("OpenD host is not localhost (%s) — connection is unencrypted", _config.cfg.host)


@contextmanager
def quote_context():
    cfg = _config.cfg
    ctx = OpenQuoteContext(host=cfg.host, port=cfg.port)
    log.debug("Opened QuoteContext to %s:%s", cfg.host, cfg.port)
    try:
        yield ctx
    finally:
        ctx.close()
        log.debug("Closed QuoteContext")
