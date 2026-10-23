"""Shared InsightOS appearance preferences and color tokens."""

from __future__ import annotations

from typing import TypedDict

from src.utils import settings_store


class ThemeColors(TypedDict):
    surface: str
    raised_surface: str
    text: str
    muted_text: str
    border: str
    divider: str
    field: str


_THEMES: dict[str, ThemeColors] = {
    "light": {
        "surface": "#F8FAFC",
        "raised_surface": "#FFFFFF",
        "text": "#0F172A",
        "muted_text": "#475569",
        "border": "rgba(15, 23, 42, 0.08)",
        "divider": "rgba(148, 163, 184, 0.22)",
        "field": "#FFFFFF",
    },
    "dark": {
        "surface": "#171C26",
        "raised_surface": "#202938",
        "text": "#F1F5F9",
        "muted_text": "#CBD5E1",
        "border": "rgba(226, 232, 240, 0.14)",
        "divider": "rgba(148, 163, 184, 0.30)",
        "field": "#111827",
    },
}


def current_theme() -> str:
    """Return the saved theme, using light mode for unknown values."""
    theme = settings_store.get_value("theme")
    return theme if isinstance(theme, str) and theme in _THEMES else "light"


def colors_for(theme: str | None = None) -> ThemeColors:
    """Return the palette for a supported theme."""
    selected = theme if isinstance(theme, str) else current_theme()
    return _THEMES.get(selected, _THEMES["light"])
