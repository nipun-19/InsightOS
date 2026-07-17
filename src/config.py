# src/config.py
"""Central configuration for InsightOS.

This module is the single source of truth for every constant used across
the application. No module other than this one may define a magic number,
path, interval, or threshold — everything configurable lives here.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"
LOG_DIR: Path = DATA_DIR / "logs"

DATABASE_PATH: Path = DATA_DIR / "insightos.db"
LOG_FILE_PATH: Path = LOG_DIR / "insightos.log"
SETTINGS_FILE_PATH: Path = DATA_DIR / "settings.json"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT: int = 3
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
LOG_FILE_LEVEL: str = "DEBUG"
LOG_CONSOLE_LEVEL: str = "INFO"

# ---------------------------------------------------------------------------
# Tracker timing
# ---------------------------------------------------------------------------
POLL_INTERVAL_SECONDS: float = 2.0
IDLE_THRESHOLD_SECONDS: int = 120

# ---------------------------------------------------------------------------
# UI refresh timing
# ---------------------------------------------------------------------------
DASHBOARD_REFRESH_INTERVAL_SECONDS: int = 5
WIDGET_REFRESH_INTERVAL_SECONDS: int = 5
TRAY_TOOLTIP_REFRESH_INTERVAL_SECONDS: int = 30

# ---------------------------------------------------------------------------
# Updater
# ---------------------------------------------------------------------------
UPDATE_CHECK_INTERVAL_HOURS: int = 24
GITHUB_RELEASES_API_URL: str = (
    "https://api.github.com/repos/insightos/insightos/releases/latest"
)

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
AUTOSTART_DELAY_SECONDS: int = 45
PROCESS_PRIORITY_CLASS: str = "BELOW_NORMAL"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_CONNECTION_TIMEOUT_SECONDS: float = 5.0
DB_WRITE_RETRY_ATTEMPTS: int = 1
DB_WRITE_RETRY_BACKOFF_SECONDS: float = 0.2
SCHEMA_VERSION: int = 1

# ---------------------------------------------------------------------------
# Date / time formatting
# ---------------------------------------------------------------------------
DATE_FORMAT: str = "%Y-%m-%d"
ISO_TIME_FORMAT: str = "%Y-%m-%dT%H:%M:%S+00:00"

# ---------------------------------------------------------------------------
# History ranges
# ---------------------------------------------------------------------------
HISTORY_RANGE_YESTERDAY_DAYS: int = 1
HISTORY_RANGE_WEEK_DAYS: int = 7
HISTORY_RANGE_MONTH_DAYS: int = 30

# ---------------------------------------------------------------------------
# Dashboard / widget presentation limits
# ---------------------------------------------------------------------------
TOP_APPS_LIMIT: int = 5

# ---------------------------------------------------------------------------
# Valid enums (kept here so no module hardcodes the literal set)
# ---------------------------------------------------------------------------
SYSTEM_EVENT_TYPES: tuple[str, ...] = ("boot", "shutdown", "sleep", "wake")