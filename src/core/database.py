# src/core/database.py
"""SQLite persistence layer for InsightOS.

This is the **only** file in the codebase permitted to contain SQL. It owns
schema creation, migrations, and every read/write query. Thread-local
connections make it safe to call from the Tracker thread and any UI thread
concurrently under WAL mode, as required by the threading model.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from src import config
from src.core.models import AppSession, DailySummary, IdlePeriod, SystemEvent
from src.utils.logger import get_logger
from src.utils.time_utils import parse_iso, utc_now_iso

logger = get_logger(__name__)

_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS system_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT NOT NULL CHECK (event_type IN ('boot','shutdown','sleep','wake')),
    timestamp   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_sessions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name          TEXT NOT NULL,
    window_title      TEXT,
    start_time        TEXT NOT NULL,
    end_time          TEXT,
    duration_seconds  INTEGER,
    date              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idle_periods (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time        TEXT NOT NULL,
    end_time          TEXT,
    duration_seconds  INTEGER,
    date              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_summary (
    date                  TEXT PRIMARY KEY,
    total_screen_seconds  INTEGER NOT NULL DEFAULT 0,
    total_idle_seconds    INTEGER NOT NULL DEFAULT 0,
    first_activity        TEXT,
    last_activity         TEXT
);

CREATE INDEX IF NOT EXISTS idx_app_sessions_date   ON app_sessions(date);
CREATE INDEX IF NOT EXISTS idx_app_sessions_active ON app_sessions(end_time) WHERE end_time IS NULL;
CREATE INDEX IF NOT EXISTS idx_idle_periods_date   ON idle_periods(date);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""


class Database:
    """Thread-safe SQLite gateway for all InsightOS persistence.

    One :class:`Database` instance is shared process-wide; each thread that
    calls into it receives its own private ``sqlite3.Connection`` via
    :meth:`get_connection`, as required for safe concurrent WAL access.
    """

    def __init__(self, db_path: Path = config.DATABASE_PATH) -> None:
        """Create the gateway and ensure the schema exists on disk.

        :param db_path: Location of the SQLite file. Defaults to the
            configured production path; tests may override it.
        """
        self._db_path = db_path
        self._local = threading.local()
        self._schema_lock = threading.Lock()
        self._schema_ready = False
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def get_connection(self) -> sqlite3.Connection:
        """Return this thread's private, WAL-mode SQLite connection."""
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(
                str(self._db_path),
                timeout=config.DB_CONNECTION_TIMEOUT_SECONDS,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.connection = conn
        return conn

    def _ensure_schema(self) -> None:
        """Create tables/indexes and record the schema version, once."""
        with self._schema_lock:
            if self._schema_ready:
                return
            conn = self.get_connection()
            conn.executescript(_SCHEMA_SQL)
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (config.SCHEMA_VERSION,),
                )
            conn.commit()
            self._schema_ready = True

    def _write(self):
        """Return a transaction context that commits on success and rolls back on failure.

        SQLite errors are never silently swallowed here; a failure propagates to
        the caller so tracking can fail safely without pretending the write
        succeeded.
        """
        return _WriteTransaction(self)

    # ------------------------------------------------------------------
    # system_events
    # ------------------------------------------------------------------

    def log_system_event(self, event_type: str) -> None:
        """Record a lifecycle event (boot, shutdown, sleep, or wake)."""
        if event_type not in config.SYSTEM_EVENT_TYPES:
            raise ValueError(f"Invalid event_type: {event_type!r}")
        with self._write() as conn:
            conn.execute(
                "INSERT INTO system_events (event_type, timestamp) VALUES (?, ?)",
                (event_type, utc_now_iso()),
            )

    def get_recent_events(self, limit: int = 20) -> list[SystemEvent]:
        """Return the most recent lifecycle events, newest first."""
        conn = self.get_connection()
        rows = conn.execute(
            "SELECT * FROM system_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [SystemEvent.from_row(row) for row in rows]

    # ------------------------------------------------------------------
    # app_sessions
    # ------------------------------------------------------------------

    def start_app_session(
        self, app_name: str, window_title: Optional[str], start_time: str, date: str
    ) -> Optional[int]:
        """Open a new active app session and return its row id."""
        with self._write() as conn:
            cursor = conn.execute(
                "INSERT INTO app_sessions (app_name, window_title, start_time, date) "
                "VALUES (?, ?, ?, ?)",
                (app_name, window_title, start_time, date),
            )
            return cursor.lastrowid

    def close_app_session(
        self,
        session_id: int,
        end_time: Optional[str] = None,
        duration_seconds: Optional[int] = None,
    ) -> None:
        """Close an active app session, fixing its ``duration_seconds``."""
        end = end_time or utc_now_iso()
        with self._write() as conn:
            row = conn.execute(
                "SELECT start_time FROM app_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return
            duration = duration_seconds if duration_seconds is not None else _elapsed_seconds(row["start_time"], end)
            conn.execute(
                "UPDATE app_sessions SET end_time = ?, duration_seconds = ? WHERE id = ?",
                (end, duration, session_id),
            )

    def get_active_session(self) -> Optional[AppSession]:
        """Return the currently open app session, if any."""
        conn = self.get_connection()
        row = conn.execute(
            "SELECT * FROM app_sessions WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return AppSession.from_row(row) if row is not None else None

    def get_sessions_for_date(self, date: str) -> list[AppSession]:
        """Return every app session recorded on ``date``, oldest first."""
        conn = self.get_connection()
        rows = conn.execute(
            "SELECT * FROM app_sessions WHERE date = ? ORDER BY start_time ASC", (date,)
        ).fetchall()
        return [AppSession.from_row(row) for row in rows]

    def get_sessions_for_dates(self, dates: list[str]) -> list[AppSession]:
        """Return every app session recorded in the provided date buckets."""
        if not dates:
            return []
        placeholders = ",".join("?" for _ in dates)
        conn = self.get_connection()
        rows = conn.execute(
            f"SELECT * FROM app_sessions WHERE date IN ({placeholders}) ORDER BY start_time ASC",
            dates,
        ).fetchall()
        return [AppSession.from_row(row) for row in rows]

    def search_sessions(self, query: str, dates: list[str] | None = None) -> list[AppSession]:
        """Return sessions whose app name or window title contains the query."""
        if not query.strip():
            return self.get_sessions_for_dates(dates or [])
        pattern = f"%{query.strip()}%"
        if dates:
            placeholders = ",".join("?" for _ in dates)
            conn = self.get_connection()
            rows = conn.execute(
                f"SELECT * FROM app_sessions WHERE date IN ({placeholders}) AND (app_name LIKE ? OR window_title LIKE ?) ORDER BY start_time ASC",
                [*dates, pattern, pattern],
            ).fetchall()
        else:
            conn = self.get_connection()
            rows = conn.execute(
                "SELECT * FROM app_sessions WHERE app_name LIKE ? OR window_title LIKE ? ORDER BY start_time ASC",
                (pattern, pattern),
            ).fetchall()
        return [AppSession.from_row(row) for row in rows]

    def get_top_apps(self, dates: list[str], limit: int = config.TOP_APPS_LIMIT) -> list[tuple[str, int]]:
        """Return the top apps by total duration across ``dates``.

        :return: List of ``(app_name, total_seconds)`` tuples, longest first.
        """
        if not dates:
            return []
        placeholders = ",".join("?" for _ in dates)
        conn = self.get_connection()
        rows = conn.execute(
            f"SELECT app_name, SUM(duration_seconds) AS total "
            f"FROM app_sessions WHERE date IN ({placeholders}) AND duration_seconds IS NOT NULL "
            f"GROUP BY app_name ORDER BY total DESC LIMIT ?",
            (*dates, limit),
        ).fetchall()
        return [(row["app_name"], row["total"]) for row in rows]

    def reconcile_orphaned_sessions(self) -> None:
        """Close any session/idle rows left open by a previous crash.

        Uses each row's own ``start_time`` as its end, so a crash never
        inflates the following day's totals with stale open rows.
        """
        with self._write() as conn:
            for table in ("app_sessions", "idle_periods"):
                rows = conn.execute(
                    f"SELECT id, start_time FROM {table} WHERE end_time IS NULL"
                ).fetchall()
                for row in rows:
                    conn.execute(
                        f"UPDATE {table} SET end_time = ?, duration_seconds = 0 WHERE id = ?",
                        (row["start_time"], row["id"]),
                    )

    # ------------------------------------------------------------------
    # idle_periods
    # ------------------------------------------------------------------

    def start_idle_period(self, start_time: str, date: str) -> Optional[int]:
        """Open a new active idle period and return its row id."""
        with self._write() as conn:
            cursor = conn.execute(
                "INSERT INTO idle_periods (start_time, date) VALUES (?, ?)",
                (start_time, date),
            )
            return cursor.lastrowid

    def close_idle_period(self, idle_id: int, end_time: Optional[str] = None) -> None:
        """Close an active idle period, fixing its ``duration_seconds``."""
        end = end_time or utc_now_iso()
        with self._write() as conn:
            row = conn.execute(
                "SELECT start_time FROM idle_periods WHERE id = ?", (idle_id,)
            ).fetchone()
            if row is None:
                return
            duration = _elapsed_seconds(row["start_time"], end)
            conn.execute(
                "UPDATE idle_periods SET end_time = ?, duration_seconds = ? WHERE id = ?",
                (end, duration, idle_id),
            )

    def get_active_idle_period(self) -> Optional[IdlePeriod]:
        """Return the currently open idle period, if any."""
        conn = self.get_connection()
        row = conn.execute(
            "SELECT * FROM idle_periods WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return IdlePeriod.from_row(row) if row is not None else None

    # ------------------------------------------------------------------
    # daily_summary
    # ------------------------------------------------------------------

    def upsert_daily_summary(
        self,
        date: str,
        screen_seconds_delta: int = 0,
        idle_seconds_delta: int = 0,
        activity_timestamp: Optional[str] = None,
    ) -> None:
        """Add deltas to a date's running totals, creating the row if needed."""
        timestamp = activity_timestamp or utc_now_iso()
        with self._write() as conn:
            conn.execute(
                """
                INSERT INTO daily_summary
                    (date, total_screen_seconds, total_idle_seconds, first_activity, last_activity)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    total_screen_seconds = total_screen_seconds + excluded.total_screen_seconds,
                    total_idle_seconds = total_idle_seconds + excluded.total_idle_seconds,
                    last_activity = excluded.last_activity
                """,
                (date, screen_seconds_delta, idle_seconds_delta, timestamp, timestamp),
            )

    def get_daily_summary(self, date: str) -> Optional[DailySummary]:
        """Return the aggregate totals for a single date, if recorded."""
        conn = self.get_connection()
        row = conn.execute(
            "SELECT * FROM daily_summary WHERE date = ?", (date,)
        ).fetchone()
        return DailySummary.from_row(row) if row is not None else None

    def get_summaries_range(self, dates: list[str]) -> list[DailySummary]:
        """Return the aggregate totals for each date in ``dates``, in order."""
        conn = self.get_connection()
        summaries: dict[str, DailySummary] = {}
        if dates:
            placeholders = ",".join("?" for _ in dates)
            rows = conn.execute(
                f"SELECT * FROM daily_summary WHERE date IN ({placeholders})", dates
            ).fetchall()
            summaries = {row["date"]: DailySummary.from_row(row) for row in rows}
        return [summaries.get(date, DailySummary(date=date)) for date in dates]

    def get_history_stats(self, dates: list[str]) -> dict[str, int]:
        """Return a compact set of factual statistics for the provided date range."""
        if not dates:
            return {}
        placeholders = ",".join("?" for _ in dates)
        conn = self.get_connection()
        total_sessions = conn.execute(
            f"SELECT COUNT(*) AS count FROM app_sessions WHERE date IN ({placeholders})",
            dates,
        ).fetchone()["count"]
        total_seconds = conn.execute(
            f"SELECT COALESCE(SUM(duration_seconds), 0) AS total FROM app_sessions WHERE date IN ({placeholders}) AND duration_seconds IS NOT NULL",
            dates,
        ).fetchone()["total"]
        app_count = conn.execute(
            f"SELECT COUNT(DISTINCT app_name) AS count FROM app_sessions WHERE date IN ({placeholders})",
            dates,
        ).fetchone()["count"]
        longest = conn.execute(
            f"SELECT MAX(duration_seconds) AS value FROM app_sessions WHERE date IN ({placeholders}) AND duration_seconds IS NOT NULL",
            dates,
        ).fetchone()["value"] or 0
        return {
            "total_sessions": int(total_sessions),
            "total_seconds": int(total_seconds),
            "unique_apps": int(app_count),
            "longest_session_seconds": int(longest),
        }

    def export_history_csv(self, dates: list[str], target_path: str) -> None:
        """Export tracked sessions for the supplied date range to CSV."""
        sessions = self.get_sessions_for_dates(dates)
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["id", "app_name", "window_title", "start_time", "end_time", "duration_seconds", "date"])
            writer.writeheader()
            for session in sessions:
                writer.writerow({
                    "id": session.id,
                    "app_name": session.app_name,
                    "window_title": session.window_title or "",
                    "start_time": session.start_time,
                    "end_time": session.end_time or "",
                    "duration_seconds": session.duration_seconds or 0,
                    "date": session.date,
                })

    def export_history_json(self, dates: list[str], target_path: str) -> None:
        """Export tracked sessions for the supplied date range to JSON."""
        sessions = self.get_sessions_for_dates(dates)
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "sessions": [
                {
                    "id": session.id,
                    "app_name": session.app_name,
                    "window_title": session.window_title,
                    "start_time": session.start_time,
                    "end_time": session.end_time,
                    "duration_seconds": session.duration_seconds,
                    "date": session.date,
                }
                for session in sessions
            ]
        }
        with open(target_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def checkpoint_and_close(self) -> None:
        """Flush the WAL file and close this thread's connection cleanly.

        Called during shutdown, after the tracker has stopped writing.
        """
        conn = getattr(self._local, "connection", None)
        if conn is None:
            return
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.commit()
        except sqlite3.OperationalError:
            logger.warning("WAL checkpoint failed during shutdown", exc_info=True)
        finally:
            conn.close()
            self._local.connection = None


class _WriteTransaction:
    """Simple transactional wrapper for SQLite writes."""

    def __init__(self, database: "Database") -> None:
        self._database = database
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self._conn = self._database.get_connection()
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._conn is None:
            return False
        if exc_type is None:
            try:
                self._conn.commit()
                return False
            except sqlite3.OperationalError:
                self._conn.rollback()
                logger.error("Database commit failed", exc_info=(exc_type, exc_val, exc_tb))
                raise
        self._conn.rollback()
        return False


def _elapsed_seconds(start_iso: str, end_iso: str) -> int:
    """Return whole seconds between two ISO8601 timestamps, floored at zero."""
    delta = parse_iso(end_iso) - parse_iso(start_iso)
    return max(0, int(delta.total_seconds()))


# Module-level public API — tracker.py, main.py, desktop_widget.py, and
# system_tray.py call functions directly on this module rather than
# instantiating Database themselves. Backed by a lazy singleton.

_db_instance: Optional[Database] = None
_db_instance_lock = threading.Lock()


def _get_db() -> Database:
    """Return the process-wide Database singleton, creating it once."""
    global _db_instance
    if _db_instance is None:
        with _db_instance_lock:
            if _db_instance is None:
                _db_instance = Database()
    return _db_instance

def init_db() -> None:
    """Ensure the database singleton and schema are initialized (§9)."""
    _get_db()

def log_system_event(event_type: str) -> None:
    """See :meth:`Database.log_system_event`."""
    _get_db().log_system_event(event_type)

def open_app_session(app_name: str, window_title: Optional[str], start_time: str, date: str) -> Optional[int]:
    """See :meth:`Database.start_app_session`."""
    return _get_db().start_app_session(app_name, window_title, start_time, date)

def close_app_session(
    session_id: int, end_time: Optional[str] = None, duration_seconds: Optional[int] = None
) -> None:
    """See :meth:`Database.close_app_session`."""
    _get_db().close_app_session(session_id, end_time, duration_seconds)

def open_idle_period(start_time: str, date: str) -> Optional[int]:
    """See :meth:`Database.start_idle_period`."""
    return _get_db().start_idle_period(start_time, date)

def close_idle_period(idle_id: int, end_time: Optional[str] = None) -> None:
    """See :meth:`Database.close_idle_period`."""
    _get_db().close_idle_period(idle_id, end_time)

def upsert_daily_summary(
    date: str, screen_delta: int = 0, idle_delta: int = 0, activity_time: Optional[str] = None
) -> None:
    """See :meth:`Database.upsert_daily_summary`."""
    _get_db().upsert_daily_summary(
        date, screen_seconds_delta=screen_delta, idle_seconds_delta=idle_delta, activity_timestamp=activity_time
    )

def get_today_summary(date: str) -> DailySummary:
    """Return totals for ``date``; an all-zero DailySummary if none recorded."""
    summary = _get_db().get_daily_summary(date)
    return summary if summary is not None else DailySummary(date=date)

def get_sessions_for_dates(dates: list[str]) -> list[AppSession]:
    """See :meth:`Database.get_sessions_for_dates`."""
    return _get_db().get_sessions_for_dates(dates)

def search_sessions(query: str, dates: list[str] | None = None) -> list[AppSession]:
    """See :meth:`Database.search_sessions`."""
    return _get_db().search_sessions(query, dates)

def get_history_stats(dates: list[str]) -> dict[str, int]:
    """See :meth:`Database.get_history_stats`."""
    return _get_db().get_history_stats(dates)

def export_history_csv(dates: list[str], target_path: str) -> None:
    """See :meth:`Database.export_history_csv`."""
    _get_db().export_history_csv(dates, target_path)

def export_history_json(dates: list[str], target_path: str) -> None:
    """See :meth:`Database.export_history_json`."""
    _get_db().export_history_json(dates, target_path)

def get_active_session() -> Optional[AppSession]:
    """See :meth:`Database.get_active_session`."""
    return _get_db().get_active_session()

def get_top_apps(dates: list[str], limit: int = config.TOP_APPS_LIMIT) -> list[tuple[str, int]]:
    """See :meth:`Database.get_top_apps`."""
    return _get_db().get_top_apps(dates, limit=limit)

def reconcile_orphaned_sessions() -> None:
    """See :meth:`Database.reconcile_orphaned_sessions`."""
    _get_db().reconcile_orphaned_sessions()

def checkpoint_and_close() -> None:
    """See :meth:`Database.checkpoint_and_close`."""
    _get_db().checkpoint_and_close()