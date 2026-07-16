"""Plain dataclasses mirroring the SQLite schema (ARCHITECTURE.md §7).

Per §6, this module contains ONLY data shapes — no SQL, no file I/O, no
business logic. `core/database.py` is responsible for translating between
sqlite3.Row objects and these dataclasses.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SystemEvent:
    """Mirrors a row in the `system_events` table.

    Attributes:
        id: Primary key. None for a not-yet-persisted instance.
        event_type: One of "boot", "shutdown", "sleep", "wake".
        timestamp: ISO8601 UTC timestamp of when the event occurred.
        created_at: ISO8601 UTC timestamp of when the row was inserted.
    """

    event_type: str
    timestamp: str
    id: int | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class AppSession:
    """Mirrors a row in the `app_sessions` table.

    Attributes:
        id: Primary key. None for a not-yet-persisted instance.
        app_name: Executable name, e.g. "chrome.exe".
        window_title: Foreground window title at session start. Stored in
            the database only — never written to the log file (§21).
        start_time: ISO8601 UTC timestamp when the session began.
        end_time: ISO8601 UTC timestamp when the session ended, or None if
            this session is still active (the currently foregrounded app).
        duration_seconds: Set once at close time; never recomputed later,
            so a closed row stays correct even after a later crash (§7).
        date: Local "YYYY-MM-DD" date the session started on.
    """

    app_name: str
    start_time: str
    date: str
    id: int | None = None
    window_title: str | None = None
    end_time: str | None = None
    duration_seconds: int | None = None

    @property
    def is_active(self) -> bool:
        """Whether this session has no end_time yet (currently foregrounded).

        Returns:
            True if the session is still open.
        """
        return self.end_time is None


@dataclass(frozen=True)
class IdlePeriod:
    """Mirrors a row in the `idle_periods` table.

    Attributes:
        id: Primary key. None for a not-yet-persisted instance.
        start_time: ISO8601 UTC timestamp when idling began.
        end_time: ISO8601 UTC timestamp when idling ended, or None if the
            user is still idle.
        duration_seconds: Set once at close time; never recomputed later.
        date: Local "YYYY-MM-DD" date the idle period started on.
    """

    start_time: str
    date: str
    id: int | None = None
    end_time: str | None = None
    duration_seconds: int | None = None

    @property
    def is_active(self) -> bool:
        """Whether this idle period is still ongoing.

        Returns:
            True if the idle period has no end_time yet.
        """
        return self.end_time is None


@dataclass(frozen=True)
class DailySummary:
    """Mirrors a row in the `daily_summary` table.

    Attributes:
        date: Local "YYYY-MM-DD" date; primary key.
        total_screen_seconds: Cumulative active (non-idle) seconds for the day.
        total_idle_seconds: Cumulative idle seconds for the day.
        first_activity: ISO8601 UTC timestamp of the first tracked activity.
        last_activity: ISO8601 UTC timestamp of the most recent tracked activity.
    """

    date: str
    total_screen_seconds: int = 0
    total_idle_seconds: int = 0
    first_activity: str | None = None
    last_activity: str | None = None


@dataclass(frozen=True)
class AppUsage:
    """Aggregated usage for a single app over some date range.

    Not a DB table — this is the shape returned by database.py's
    "top apps" queries, which GROUP BY app_name and SUM duration_seconds
    across one or more `app_sessions` rows.

    Attributes:
        app_name: Executable name, e.g. "chrome.exe".
        total_seconds: Summed duration across all matching sessions.
    """

    app_name: str
    total_seconds: int
