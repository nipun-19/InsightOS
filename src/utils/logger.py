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
import sys
from pathlib import Path

from src import config


def configure_logging(level: str = config.LOG_DEFAULT_LEVEL) -> None:
    """Configure the root logger with file and console handlers."""
    root_logger = logging.getLogger()

    root_logger.setLevel(level)

    log_dir: Path = config.LOG_FILE_PATH.parent
    log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = None
    for handler in root_logger.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            file_handler = handler
            break

    if file_handler is None:
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(config.LOG_FILE_PATH),
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        formatter = logging.Formatter(fmt=config.LOG_FORMAT, datefmt=config.LOG_DATE_FORMAT)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    console_handler = None
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.handlers.RotatingFileHandler):
            console_handler = handler
            break

    if console_handler is None:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(config, "LOG_CONSOLE_LEVEL", "INFO"))
        console_handler.setFormatter(logging.Formatter(fmt=config.LOG_FORMAT, datefmt=config.LOG_DATE_FORMAT))
        root_logger.addHandler(console_handler)


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
