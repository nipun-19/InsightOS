"""Rotating file logger setup for InsightOS.

ARCHITECTURE.md §21 (Logging Strategy):
- A single rotating file logger; every module uses logging.getLogger(__name__).
- Location: data/logs/insightos.log, rotated at 5 MB, 3 backups kept.
- Window titles are NEVER written to the log file — only executable names
  and lifecycle events. Callers of this module are responsible for that
  guarantee; this module only configures where/how logs are written.
- Logging is 100% local — never transmitted anywhere.

Usage (from any module):
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Tracker started")

configure_logging() must be called exactly once, early in main.py's boot
sequence, before any other module logs anything.
"""

import logging
import logging.handlers
from pathlib import Path

import config


def configure_logging(level: str = config.LOG_DEFAULT_LEVEL) -> None:
    """Configure the root logger with a rotating file handler.

    Idempotent: calling this more than once will not duplicate handlers,
    so it is safe to call defensively from tests or tools.

    Args:
        level: Logging level name (e.g. "INFO", "WARNING", "ERROR").

    Returns:
        None.
    """
    root_logger = logging.getLogger()

    if root_logger.handlers:
        return  # Already configured — avoid duplicate handlers.

    root_logger.setLevel(level)

    log_dir: Path = config.LOG_FILE_PATH.parent
    log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(config.LOG_FILE_PATH),
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    formatter = logging.Formatter(fmt=config.LOG_FORMAT, datefmt=config.LOG_DATE_FORMAT)
    file_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger.

    Thin convenience wrapper so call sites don't need to import logging
    directly. Equivalent to logging.getLogger(name).

    Args:
        name: Typically __name__ of the calling module.

    Returns:
        A standard library Logger instance.
    """
    return logging.getLogger(name)
