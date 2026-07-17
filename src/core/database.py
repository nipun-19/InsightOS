# src/core/database.py
"""SQLite persistence layer for InsightOS.

This is the **only** file in the codebase permitted to contain SQL. It owns
schema creation, migrations, and every read/write query. Thread-local
connections make it safe to call from the Tracker thread and any UI thread
concurrently under WAL mode, as required by the threading model.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

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

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """Context manager for a write operation with retry-on-lock.

        Commits on success. On ``sqlite3.OperationalError`` (e.g. the
        database is momentarily locked) it retries once after a short
        backoff, then logs and swallows the failure rather than crashing
        the caller, per the exception-handling strategy.
        """
        conn = self.get_connection()
        attempts = config.DB_WRITE_RETRY_ATTEMPTS + 1
        for attempt in range(1, attempts + 1):
            try:
                yield conn
                conn.commit()
                return
            except sqlite3.OperationalError:
                conn.rollback()
                if attempt >= attempts:
                    logger.warning("Dropping write after %d attempts", attempt, exc_info=True)
                    return
                logger.warning("Write failed (attempt %d), retrying", attempt, exc_info=True)
                time.sleep(config.DB_WRITE_RETRY_BACKOFF_SECONDS)
            except Exception:
                conn.rollback()
                raise

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

    def start_app_session(self, app_name: str, window_title: Optional[str], date: str) -> Optional[int]:
        """Open a new active app session and return its row id."""
        with self._write() as conn:
            cursor = conn.execute(
                "INSERT INTO app_sessions (app_name, window_title, start_time, date) "
                "VALUES (?, ?, ?, ?)",
                (app_name, window_title, utc_now_iso(), date),
            )
            return cursor.lastrowid

    def close_app_session(self, session_id: int, end_time: Optional[str] = None) -> None:
        """Close an active app session, fixing its ``duration_seconds``."""
        end = end_time or utc_now_iso()
        with self._write() as conn:
            row = conn.execute(
                "SELECT start_time FROM app_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return
            duration = _elapsed_seconds(row["start_time"], end)
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

    def start_idle_period(self, date: str) -> Optional[int]:
        """Open a new active idle period and return its row id."""
        with self._write() as conn:
            cursor = conn.execute(
                "INSERT INTO idle_periods (start_time, date) VALUES (?, ?)",
                (utc_now_iso(), date),
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


def _elapsed_seconds(start_iso: str, end_iso: str) -> int:
    """Return whole seconds between two ISO8601 timestamps, floored at zero."""
    delta = parse_iso(end_iso) - parse_iso(start_iso)
    return max(0, int(delta.total_seconds()))