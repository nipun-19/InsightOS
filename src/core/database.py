"""SQLite access layer for InsightOS.

Per ARCHITECTURE.md §6 (Engineering Rule #8): "Database queries must exist
ONLY inside database.py." No other module may import sqlite3 or write raw
SQL. This module owns connection management (thread-local, WAL mode),
schema creation, and every CRUD/query operation used by the Tracker and UI.

Threading (§16): each thread must use its own connection under WAL mode.
get_connection() returns a thread-local connection, created lazily.
"""

import sqlite3
import threading
import time

import config
from core.models import AppSession, AppUsage, DailySummary, IdlePeriod
from utils import time_utils
from utils.logger import get_logger

logger = get_logger(__name__)

_local = threading.local()

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
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


def get_connection() -> sqlite3.Connection:
    """Return this thread's SQLite connection, creating it on first use."""
    connection = getattr(_local, "connection", None)
    if connection is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(config.DB_PATH),
            timeout=config.DB_BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,  # autocommit; transactions are single statements
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {config.DB_BUSY_TIMEOUT_MS}")
        _local.connection = connection
    return connection


def init_db() -> None:
    """Create the schema if missing and record the schema version. Idempotent."""
    conn = get_connection()
    conn.executescript(_SCHEMA_SQL)
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (config.SCHEMA_VERSION,))
    logger.info("Database initialized at %s", config.DB_PATH)


def checkpoint_and_close() -> None:
    """Checkpoint the WAL file and close this thread's connection (§15)."""
    connection = getattr(_local, "connection", None)
    if connection is not None:
        connection.execute("PRAGMA wal_checkpoint(FULL)")
        connection.close()
        _local.connection = None
        logger.info("Database checkpointed and closed")


def _run_write(operation_name: str, fn) -> None:
    """Run a write callable with the §20 retry policy: retry once on
    sqlite3.OperationalError, then log and drop rather than crash."""
    attempts = config.DB_WRITE_RETRY_ATTEMPTS + 1
    for attempt in range(1, attempts + 1):
        try:
            fn()
            return
        except sqlite3.OperationalError as exc:
            if attempt < attempts:
                logger.warning(
                    "DB write '%s' failed (attempt %d/%d): %s — retrying",
                    operation_name, attempt, attempts, exc,
                )
                time.sleep(config.DB_WRITE_RETRY_BACKOFF_SECONDS)
            else:
                logger.warning(
                    "DB write '%s' failed after %d attempts: %s — dropped",
                    operation_name, attempts, exc,
                )


def log_system_event(event_type: str, timestamp: str | None = None) -> None:
    """Insert a lifecycle event row (boot/shutdown/sleep/wake)."""
    ts = timestamp or time_utils.utc_now_iso()

    def _write() -> None:
        get_connection().execute(
            "INSERT INTO system_events (event_type, timestamp) VALUES (?, ?)", (event_type, ts)
        )

    _run_write("log_system_event", _write)
    logger.info("System event logged: %s", event_type)


def reconcile_orphaned_sessions() -> None:
    """Close sessions/idle periods left open by a crash (§8): a row with
    end_time IS NULL from a previous local date is closed at its own
    start_time (zero duration) so stale data never inflates today's totals.
    """
    today = time_utils.today_str()
    conn = get_connection()

    orphaned_sessions = conn.execute(
        "SELECT id, start_time FROM app_sessions WHERE end_time IS NULL AND date != ?", (today,)
    ).fetchall()
    for row in orphaned_sessions:
        conn.execute(
            "UPDATE app_sessions SET end_time = ?, duration_seconds = 0 WHERE id = ?",
            (row["start_time"], row["id"]),
        )

    orphaned_idle = conn.execute(
        "SELECT id, start_time FROM idle_periods WHERE end_time IS NULL AND date != ?", (today,)
    ).fetchall()
    for row in orphaned_idle:
        conn.execute(
            "UPDATE idle_periods SET end_time = ?, duration_seconds = 0 WHERE id = ?",
            (row["start_time"], row["id"]),
        )

    if orphaned_sessions or orphaned_idle:
        logger.info(
            "Reconciled %d orphaned session(s), %d orphaned idle period(s)",
            len(orphaned_sessions), len(orphaned_idle),
        )


def open_app_session(app_name: str, window_title: str | None, start_time: str, date: str) -> int:
    """Insert a new open app session (end_time NULL). Returns the new row id."""
    cursor = get_connection().execute(
        "INSERT INTO app_sessions (app_name, window_title, start_time, date) VALUES (?, ?, ?, ?)",
        (app_name, window_title, start_time, date),
    )
    return int(cursor.lastrowid)


def close_app_session(session_id: int, end_time: str) -> None:
    """Close an open app session, computing and freezing its duration."""
    conn = get_connection()

    def _write() -> None:
        row = conn.execute(
            "SELECT start_time FROM app_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return
        duration = time_utils.seconds_between(row["start_time"], end_time)
        conn.execute(
            "UPDATE app_sessions SET end_time = ?, duration_seconds = ? WHERE id = ?",
            (end_time, duration, session_id),
        )

    _run_write("close_app_session", _write)


def get_active_session() -> AppSession | None:
    """Return the currently open app session, or None if nothing is active."""
    row = get_connection().execute(
        "SELECT * FROM app_sessions WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _row_to_app_session(row) if row else None


def open_idle_period(start_time: str, date: str) -> int:
    """Insert a new open idle period (end_time NULL). Returns the new row id."""
    cursor = get_connection().execute(
        "INSERT INTO idle_periods (start_time, date) VALUES (?, ?)", (start_time, date)
    )
    return int(cursor.lastrowid)


def close_idle_period(idle_id: int, end_time: str) -> None:
    """Close an open idle period, computing and freezing its duration."""
    conn = get_connection()

    def _write() -> None:
        row = conn.execute(
            "SELECT start_time FROM idle_periods WHERE id = ?", (idle_id,)
        ).fetchone()
        if row is None:
            return
        duration = time_utils.seconds_between(row["start_time"], end_time)
        conn.execute(
            "UPDATE idle_periods SET end_time = ?, duration_seconds = ? WHERE id = ?",
            (end_time, duration, idle_id),
        )

    _run_write("close_idle_period", _write)


def get_active_idle_period() -> IdlePeriod | None:
    """Return the currently open idle period, or None if the user isn't idle."""
    row = get_connection().execute(
        "SELECT * FROM idle_periods WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _row_to_idle_period(row) if row else None


def upsert_daily_summary(
    date: str, screen_delta: int = 0, idle_delta: int = 0, activity_time: str | None = None
) -> None:
    """Increment today's summary row (creating it if needed) by the given deltas."""
    conn = get_connection()

    def _write() -> None:
        conn.execute(
            "INSERT OR IGNORE INTO daily_summary (date, first_activity) VALUES (?, ?)",
            (date, activity_time),
        )
        conn.execute(
            """
            UPDATE daily_summary
            SET total_screen_seconds = total_screen_seconds + ?,
                total_idle_seconds = total_idle_seconds + ?,
                last_activity = COALESCE(?, last_activity),
                first_activity = COALESCE(first_activity, ?)
            WHERE date = ?
            """,
            (screen_delta, idle_delta, activity_time, activity_time, date),
        )

    _run_write("upsert_daily_summary", _write)


def get_today_summary(date: str) -> DailySummary:
    """Fetch the daily_summary row for a date (zeroed if none exists yet)."""
    row = get_connection().execute("SELECT * FROM daily_summary WHERE date = ?", (date,)).fetchone()
    if row is None:
        return DailySummary(date=date)
    return DailySummary(
        date=row["date"],
        total_screen_seconds=row["total_screen_seconds"],
        total_idle_seconds=row["total_idle_seconds"],
        first_activity=row["first_activity"],
        last_activity=row["last_activity"],
    )


def get_daily_summaries(dates: list[str]) -> list[DailySummary]:
    """Fetch one DailySummary per requested date, preserving input order,
    zeroed for any date with no row yet. Used for history bar charts (§12)."""
    if not dates:
        return []
    placeholders = ",".join("?" for _ in dates)
    rows = get_connection().execute(
        f"SELECT * FROM daily_summary WHERE date IN ({placeholders})", dates
    ).fetchall()
    by_date = {row["date"]: row for row in rows}
    return [
        DailySummary(
            date=d,
            total_screen_seconds=by_date[d]["total_screen_seconds"] if d in by_date else 0,
            total_idle_seconds=by_date[d]["total_idle_seconds"] if d in by_date else 0,
            first_activity=by_date[d]["first_activity"] if d in by_date else None,
            last_activity=by_date[d]["last_activity"] if d in by_date else None,
        )
        for d in dates
    ]


def get_top_apps(dates: list[str], limit: int = config.TOP_APPS_COUNT) -> list[AppUsage]:
    """Return the top apps by total closed-session duration over a date range.

    Only counts closed sessions (duration_seconds NOT NULL); callers needing
    a live "today" total must add the active session's elapsed time themselves.
    """
    if not dates:
        return []
    placeholders = ",".join("?" for _ in dates)
    rows = get_connection().execute(
        f"""
        SELECT app_name, SUM(duration_seconds) AS total_seconds
        FROM app_sessions
        WHERE date IN ({placeholders}) AND duration_seconds IS NOT NULL
        GROUP BY app_name
        ORDER BY total_seconds DESC
        LIMIT ?
        """,
        (*dates, limit),
    ).fetchall()
    return [AppUsage(app_name=row["app_name"], total_seconds=row["total_seconds"]) for row in rows]


def get_sessions_for_date(date: str) -> list[AppSession]:
    """Return every app session for a date, ordered by start time — used for
    the Today tab's Daily Timeline segmented strip (§12)."""
    rows = get_connection().execute(
        "SELECT * FROM app_sessions WHERE date = ? ORDER BY start_time ASC", (date,)
    ).fetchall()
    return [_row_to_app_session(row) for row in rows]


def _row_to_app_session(row: sqlite3.Row) -> AppSession:
    """Convert a sqlite3.Row from app_sessions into an AppSession."""
    return AppSession(
        id=row["id"], app_name=row["app_name"], window_title=row["window_title"],
        start_time=row["start_time"], end_time=row["end_time"],
        duration_seconds=row["duration_seconds"], date=row["date"],
    )


def _row_to_idle_period(row: sqlite3.Row) -> IdlePeriod:
    """Convert a sqlite3.Row from idle_periods into an IdlePeriod."""
    return IdlePeriod(
        id=row["id"], start_time=row["start_time"], end_time=row["end_time"],
        duration_seconds=row["duration_seconds"], date=row["date"],
    )
