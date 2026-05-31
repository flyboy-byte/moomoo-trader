import logging
import sys
from datetime import datetime

from .config import cfg


def get_logger(name: str) -> logging.Logger:
    cfg.logs_dir.mkdir(exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    date_str = datetime.now().strftime("%Y-%m-%d")
    fh = logging.FileHandler(cfg.logs_dir / f"{name}_{date_str}.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(sh)
    logger.addHandler(fh)
    return logger
