"""Simple persistence helpers for startup and window state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from src import config
from src.utils import settings_store


class StartupStateStore:
    """Persist lightweight window and lifecycle state for native startup behavior."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or getattr(config, "STARTUP_STATE_FILE_PATH", config.DATA_DIR / "startup_state.json")
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile("w", encoding="utf-8", dir=str(self._path.parent), delete=False) as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                temp_path = Path(handle.name)
            os.replace(temp_path, self._path)
        except OSError:
            return

    def remember_window(self, window_title: str, geometry: tuple[int, int, int, int]) -> None:
        payload = self.load()
        payload["window_geometry"] = {"title": window_title, "geometry": list(geometry)}
        self.save(payload)

    def remember_dashboard_state(self, tab_index: int, history_range: str, history_query: str, history_sort: str) -> None:
        payload = self.load()
        payload["dashboard_state"] = {
            "tab_index": tab_index,
            "history_range": history_range,
            "history_query": history_query,
            "history_sort": history_sort,
        }
        self.save(payload)

    def remember_widget(self, geometry: tuple[int, int, int, int], visible: bool, compact: bool, opacity: float) -> None:
        payload = self.load()
        payload["widget"] = {
            "geometry": list(geometry),
            "visible": visible,
            "compact": compact,
            "opacity": opacity,
        }
        self.save(payload)

    def restore_widget(self) -> dict[str, Any]:
        payload = self.load().get("widget", {})
        geometry = payload.get("geometry", [config.WIDGET_DEFAULT_X, config.WIDGET_DEFAULT_Y, config.WIDGET_WIDTH, config.WIDGET_HEIGHT])
        if not isinstance(geometry, (list, tuple)) or len(geometry) != 4:
            geometry = [config.WIDGET_DEFAULT_X, config.WIDGET_DEFAULT_Y, config.WIDGET_WIDTH, config.WIDGET_HEIGHT]
        try:
            geometry = [int(geometry[0]), int(geometry[1]), int(geometry[2]), int(geometry[3])]
        except (TypeError, ValueError):
            geometry = [config.WIDGET_DEFAULT_X, config.WIDGET_DEFAULT_Y, config.WIDGET_WIDTH, config.WIDGET_HEIGHT]
        return {
            "geometry": tuple(geometry),
            "visible": bool(payload.get("visible", True)),
            "compact": bool(payload.get("compact", False)),
            "opacity": float(payload.get("opacity", settings_store.get_value("widget_opacity"))),
        }

    def restore_dashboard_state(self) -> dict[str, Any]:
        payload = self.load().get("dashboard_state", {})
        return {
            "tab_index": int(payload.get("tab_index", 0)),
            "history_range": str(payload.get("history_range", "Today")),
            "history_query": str(payload.get("history_query", "")),
            "history_sort": str(payload.get("history_sort", "Newest")),
        }
