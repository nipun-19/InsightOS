# src/version.py
"""Version identifier for InsightOS.

This is the single authoritative version source used by runtime code and
packaging metadata.
"""

from __future__ import annotations

__version__: str = "1.0.0"


def get_version() -> str:
    """Return the authoritative project version."""
    return __version__
