import logging
import sys
from logging.handlers import TimedRotatingFileHandler

from . import config as _config


def get_logger(name: str) -> logging.Logger:
    cfg = _config.cfg
    cfg.logs_dir.mkdir(exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    # Rotate at midnight, keep forever (backupCount=0 disables deletion).
    # Suffix format produces name.log.YYYY-MM-DD.
    fh = TimedRotatingFileHandler(
        filename=cfg.logs_dir / f"{name}.log",
        when="midnight",
        interval=1,
        backupCount=0,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(sh)
    logger.addHandler(fh)
    return logger
