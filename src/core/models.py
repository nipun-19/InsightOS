# src/core/models.py
"""Plain dataclasses mirroring rows in the InsightOS SQLite schema.

These models carry data only — no SQL, no I/O, no formatting logic. Row
parsing (``from_row``) is the single exception, since it is the natural
boundary between raw ``sqlite3.Row`` objects and typed application data.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class SystemEvent:
    """A single lifecycle event: boot, shutdown, sleep, or wake.

    :ivar id: Primary key, ``None`` until persisted.
    :ivar event_type: One of ``"boot"``, ``"shutdown"``, ``"sleep"``, ``"wake"``.
    :ivar timestamp: ISO8601 UTC instant the event occurred.
    :ivar created_at: ISO8601 UTC instant the row was written.
    """

    event_type: str
    timestamp: str
    id: Optional[int] = None
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SystemEvent":
        """Build a :class:`SystemEvent` from a ``system_events`` row."""
        return cls(
            id=row["id"],
            event_type=row["event_type"],
            timestamp=row["timestamp"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class AppSession:
    """A contiguous span of time a single application held the foreground.

    :ivar app_name: Executable name, e.g. ``"chrome.exe"``.
    :ivar window_title: Foreground window title at session start; database-only.
    :ivar start_time: ISO8601 UTC start instant.
    :ivar end_time: ISO8601 UTC end instant, or ``None`` if still active.
    :ivar duration_seconds: Fixed at close-time; never recomputed later.
    :ivar date: Local ``YYYY-MM-DD`` bucket the session belongs to.
    """

    app_name: str
    start_time: str
    date: str
    id: Optional[int] = None
    window_title: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: Optional[int] = None

    @property
    def is_active(self) -> bool:
        """Return ``True`` when the session has not yet been closed."""
        return self.end_time is None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AppSession":
        """Build an :class:`AppSession` from an ``app_sessions`` row."""
        return cls(
            id=row["id"],
            app_name=row["app_name"],
            window_title=row["window_title"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            duration_seconds=row["duration_seconds"],
            date=row["date"],
        )


@dataclass(slots=True)
class IdlePeriod:
    """A contiguous span of time with no keyboard/mouse activity.

    :ivar start_time: ISO8601 UTC start instant.
    :ivar end_time: ISO8601 UTC end instant, or ``None`` if still active.
    :ivar duration_seconds: Fixed at close-time; never recomputed later.
    :ivar date: Local ``YYYY-MM-DD`` bucket the idle period belongs to.
    """

    start_time: str
    date: str
    id: Optional[int] = None
    end_time: Optional[str] = None
    duration_seconds: Optional[int] = None

    @property
    def is_active(self) -> bool:
        """Return ``True`` when the idle period has not yet been closed."""
        return self.end_time is None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "IdlePeriod":
        """Build an :class:`IdlePeriod` from an ``idle_periods`` row."""
        return cls(
            id=row["id"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            duration_seconds=row["duration_seconds"],
            date=row["date"],
        )


@dataclass(slots=True)
class DailySummary:
    """Aggregate totals for a single local calendar date.

    :ivar date: Local ``YYYY-MM-DD`` bucket, primary key.
    :ivar total_screen_seconds: Sum of active (non-idle) foreground time.
    :ivar total_idle_seconds: Sum of idle time.
    :ivar first_activity: ISO8601 UTC instant of the day's first activity.
    :ivar last_activity: ISO8601 UTC instant of the day's most recent activity.
    """

    date: str
    total_screen_seconds: int = 0
    total_idle_seconds: int = 0
    first_activity: Optional[str] = None
    last_activity: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "DailySummary":
        """Build a :class:`DailySummary` from a ``daily_summary`` row."""
        return cls(
            date=row["date"],
            total_screen_seconds=row["total_screen_seconds"],
            total_idle_seconds=row["total_idle_seconds"],
            first_activity=row["first_activity"],
            last_activity=row["last_activity"],
        )


@dataclass(slots=True)
class AppUsage:
    """A simple aggregate row for top-app usage summaries."""

    app_name: str
    total_seconds: int