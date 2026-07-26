import logging
import sys
from logging.handlers import TimedRotatingFileHandler

from . import config as _config

_quiet = False

# Per-bar loggers that flood output during backtests and batch API runs.
# Summary loggers (backtest, research, orb_strategy) intentionally excluded.
_NOISY_LOGGERS = {"strategy", "signals", "evals", "morning_regime", "orb_strategy"}


def set_quiet_mode(quiet: bool = True, extra: set[str] | None = None) -> None:
    """Silence per-trade console noise during backtests and batch API runs.

    Only quiets loggers in _NOISY_LOGGERS (plus any in `extra`).
    Summary loggers (backtest, research) stay at INFO so results are visible.
    File handlers are unaffected — DEBUG logs still go to disk.
    """
    global _quiet
    _quiet = quiet
    targets = _NOISY_LOGGERS | (extra or set())
    level = logging.WARNING if quiet else logging.INFO
    for name, logger in logging.Logger.manager.loggerDict.items():
        if name in targets and isinstance(logger, logging.Logger):
            for handler in logger.handlers:
                if isinstance(handler, logging.StreamHandler) and not isinstance(
                    handler, TimedRotatingFileHandler
                ):
                    handler.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    cfg = _config.cfg
    cfg.logs_dir.mkdir(exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.WARNING if (_quiet and name in _NOISY_LOGGERS) else logging.INFO)
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
