"""Local settings.json read/write for InsightOS.

Per ARCHITECTURE.md §6, this module owns app configuration — widget
position, widget visibility, last update-check timestamp — as distinct
from tracked usage data, which lives exclusively in SQLite (core/database.py).
Nothing in this file is user activity data; it is safe, non-sensitive
local app state.
"""

import json
from pathlib import Path
from typing import Any

import config
from utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULTS: dict[str, Any] = {
    "widget_visible": True,
    "widget_x": config.WIDGET_DEFAULT_X,
    "widget_y": config.WIDGET_DEFAULT_Y,
    "last_update_check": None,
}


def load_settings() -> dict[str, Any]:
    """Load settings.json, filling in defaults for any missing keys.

    If the file doesn't exist or is corrupt, defaults are returned and
    logged — this must never crash the app on startup.

    Returns:
        A dict of settings, always containing every key in _DEFAULTS.
    """
    path: Path = config.SETTINGS_FILE_PATH
    if not path.exists():
        return dict(_DEFAULTS)

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read settings.json (%s) — using defaults", exc)
        return dict(_DEFAULTS)

    merged = dict(_DEFAULTS)
    merged.update(data)
    return merged


def save_settings(settings: dict[str, Any]) -> None:
    """Persist a settings dict to settings.json, creating data/ if needed.

    Args:
        settings: The full settings dict to write (typically load_settings()
            merged with updated values).

    Returns:
        None.
    """
    path: Path = config.SETTINGS_FILE_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, sort_keys=True)
    except OSError as exc:
        logger.warning("Failed to write settings.json: %s", exc)


def get_value(key: str) -> Any:
    """Read a single setting, falling back to its default if unset.

    Args:
        key: Setting name, e.g. "widget_visible" or "last_update_check".

    Returns:
        The stored value, or the default for that key if not present.
    """
    return load_settings().get(key, _DEFAULTS.get(key))


def set_value(key: str, value: Any) -> None:
    """Update a single setting and persist the full settings file.

    Args:
        key: Setting name to update.
        value: New value to store.

    Returns:
        None.
    """
    settings = load_settings()
    settings[key] = value
    save_settings(settings)
