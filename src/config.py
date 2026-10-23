# src/config.py
"""Central configuration for InsightOS.

This module is the single source of truth for every constant used across
the application. No module other than this one may define a magic number,
path, interval, or threshold — everything configurable lives here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from src.version import __version__

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent.parent
APP_NAME: str = "InsightOS"
APP_RESOURCE_DIR: Path = BASE_DIR
APP_VERSION: str = __version__


def resolve_app_resource_root() -> Path:
    """Return the read-only application resource root.

    When running inside a source checkout, this is the repository root so
    development stays straightforward. When frozen/installed, it resolves to the
    packaged application bundle or the executable directory.
    """
    environment_override = os.environ.get("INSIGHTOS_RESOURCE_DIR")
    if environment_override:
        return Path(environment_override).expanduser().resolve()

    if getattr(sys, "frozen", False):
        # PyInstaller / frozen app bundle; either MEIPASS or the exe directory.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return Path(sys.executable).resolve().parent

    return BASE_DIR


def resolve_user_data_dir() -> Path:
    """Return the runtime data directory.

    Source-tree development stays repo-local for determinism; explicit overrides
    and frozen app installs use a user-scoped location.
    """
    global DATA_DIR, LOG_DIR, DATABASE_PATH, LOG_FILE_PATH, SETTINGS_FILE_PATH, STARTUP_STATE_FILE_PATH, LOCK_FILE_PATH
    environment_override = os.environ.get("INSIGHTOS_DATA_DIR")
    if environment_override:
        resolved = Path(environment_override).expanduser().resolve()
    elif getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if local_app_data:
            resolved = Path(local_app_data).expanduser() / APP_NAME
        else:
            resolved = Path.home() / "AppData" / "Local" / APP_NAME
    else:
        resolved = BASE_DIR / "data"

    globals()["DATA_DIR"] = resolved
    globals()["LOG_DIR"] = resolved / "logs"
    globals()["DATABASE_PATH"] = resolved / "insightos.db"
    globals()["LOG_FILE_PATH"] = resolved / "logs" / "insightos.log"
    globals()["SETTINGS_FILE_PATH"] = resolved / "settings.json"
    globals()["STARTUP_STATE_FILE_PATH"] = resolved / "startup_state.json"
    globals()["LOCK_FILE_PATH"] = resolved / "insightos.lock"
    return resolved


APP_RESOURCE_DIR = resolve_app_resource_root()
resolve_user_data_dir()

DATA_DIR: Path = globals()["DATA_DIR"]
LOG_DIR: Path = globals()["LOG_DIR"]
TRAY_ICON_PATH: Path = APP_RESOURCE_DIR / "assets" / "branding" / "symbol" / "logo_vector.svg"
TRAY_FALLBACK_ICON_PATH: Path = APP_RESOURCE_DIR / "assets" / "branding" / "symbol" / "logo_vector.svg"
WIDGET_LOGO_PATH: Path = APP_RESOURCE_DIR / "assets" / "branding" / "symbol" / "logo_vector.svg"

DATABASE_PATH: Path = globals()["DATABASE_PATH"]
LOG_FILE_PATH: Path = globals()["LOG_FILE_PATH"]
SETTINGS_FILE_PATH: Path = globals()["SETTINGS_FILE_PATH"]
STARTUP_STATE_FILE_PATH: Path = globals()["STARTUP_STATE_FILE_PATH"]
LOCK_FILE_PATH: Path = globals()["LOCK_FILE_PATH"]
APP_ENTRYPOINT: Path = BASE_DIR / "main.py"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT: int = 3
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
LOG_FILE_LEVEL: str = "DEBUG"
LOG_CONSOLE_LEVEL: str = "INFO"
LOG_DEFAULT_LEVEL: str = "INFO"

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
WIDGET_WIDTH: int = 360
WIDGET_HEIGHT: int = 240
WIDGET_COMPACT_HEIGHT: int = 220
WIDGET_DEFAULT_X: int = 48
WIDGET_DEFAULT_Y: int = 48
WIDGET_REFRESH_INTERVAL_SECONDS: int = 5
WIDGET_LIVE_REFRESH_INTERVAL_SECONDS: int = 3
WIDGET_VISIBILITY_POLL_INTERVAL_MS: int = 150
WIDGET_DAILY_TARGET_SECONDS: int = 8 * 60 * 60

# ---------------------------------------------------------------------------
# Valid enums (kept here so no module hardcodes the literal set)
# ---------------------------------------------------------------------------
SYSTEM_EVENT_TYPES: tuple[str, ...] = ("boot", "shutdown", "sleep", "wake")