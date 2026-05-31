from contextlib import contextmanager
from moomoo import OpenQuoteContext, RET_OK

from .config import cfg
from .logger import get_logger

log = get_logger("connection")


@contextmanager
def quote_context():
    ctx = OpenQuoteContext(host=cfg.host, port=cfg.port)
    log.debug("Opened QuoteContext to %s:%s", cfg.host, cfg.port)
    try:
        yield ctx
    finally:
        ctx.close()
        log.debug("Closed QuoteContext")
