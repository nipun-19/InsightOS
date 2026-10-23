import sqlite3
from types import SimpleNamespace

import pytest

from src.core import tracker as tracker_module
from src.core.database import Database
from src.core.tracker import Tracker


def tracker_database_adapter(database):
    return SimpleNamespace(
        open_app_session=database.start_app_session,
        close_app_session=database.close_app_session,
        open_idle_period=database.start_idle_period,
        close_idle_period=database.close_idle_period,
        upsert_daily_summary=lambda date, screen_delta=0, idle_delta=0, activity_time=None: database.upsert_daily_summary(
            date,
            screen_seconds_delta=screen_delta,
            idle_seconds_delta=idle_delta,
            activity_timestamp=activity_time,
        ),
    )


def test_authoritative_duration_ignores_wall_clock_jump(tmp_path):
    database = Database(tmp_path / "duration.db")
    session_id = database.start_app_session(
        "A.exe", "A", "2026-01-01T10:00:00+00:00", "2026-01-01"
    )

    database.close_app_session(
        session_id,
        "2026-01-01T09:45:00+00:00",
        duration_seconds=37,
    )

    session = database.get_sessions_for_date("2026-01-01")[0]
    assert session.duration_seconds == 37
    assert session.end_time == "2026-01-01T09:45:00+00:00"


def test_orphan_reconciliation_is_deterministic_and_allows_restart_session(tmp_path):
    database = Database(tmp_path / "restart.db")
    orphan_id = database.start_app_session(
        "A.exe", "A", "2026-01-01T10:00:00+00:00", "2026-01-01"
    )

    database.reconcile_orphaned_sessions()
    first = database.get_sessions_for_date("2026-01-01")[0]
    database.reconcile_orphaned_sessions()
    second = database.get_sessions_for_date("2026-01-01")[0]
    new_id = database.start_app_session(
        "B.exe", "B", "2026-01-01T11:00:00+00:00", "2026-01-01"
    )

    assert first.id == second.id == orphan_id
    assert first.end_time == first.start_time
    assert first.duration_seconds == 0
    assert second.end_time == first.end_time
    assert new_id != orphan_id
    assert database.get_active_session().id == new_id


def test_repeated_session_close_does_not_change_duration_or_create_rows(tmp_path):
    database = Database(tmp_path / "close.db")
    session_id = database.start_app_session(
        "A.exe", "A", "2026-01-01T10:00:00+00:00", "2026-01-01"
    )
    database.close_app_session(session_id, "2026-01-01T10:01:00+00:00", duration_seconds=60)
    database.close_app_session(session_id, "2026-01-01T10:02:00+00:00", duration_seconds=120)

    sessions = database.get_sessions_for_date("2026-01-01")
    assert len(sessions) == 1
    assert sessions[0].duration_seconds == 120
    assert database.get_active_session() is None


def test_session_date_is_retained_across_wall_clock_midnight(tmp_path):
    database = Database(tmp_path / "midnight.db")
    session_id = database.start_app_session(
        "A.exe", "A", "2026-01-01T23:59:59+00:00", "2026-01-01"
    )
    database.close_app_session(
        session_id,
        "2026-01-02T00:00:03+00:00",
        duration_seconds=4,
    )

    assert len(database.get_sessions_for_date("2026-01-01")) == 1
    assert database.get_sessions_for_date("2026-01-01")[0].duration_seconds == 4
    assert database.get_sessions_for_date("2026-01-02") == []


def test_active_session_query_has_one_row_after_normal_switch(tmp_path):
    database = Database(tmp_path / "switch.db")
    first_id = database.start_app_session(
        "A.exe", "A", "2026-01-01T10:00:00+00:00", "2026-01-01"
    )
    database.close_app_session(first_id, "2026-01-01T10:01:00+00:00", duration_seconds=60)
    second_id = database.start_app_session(
        "B.exe", "B", "2026-01-01T10:01:00+00:00", "2026-01-01"
    )

    assert database.get_active_session().id == second_id
    assert len(database.get_sessions_for_date("2026-01-01")) == 2
    assert database.get_sessions_for_date("2026-01-01")[0].end_time is not None


def test_tracker_shutdown_persists_final_interval_once(tmp_path, monkeypatch):
    database = Database(tmp_path / "shutdown.db")
    monkeypatch.setattr(tracker_module, "db", tracker_database_adapter(database))
    monkeypatch.setattr(tracker_module.platform_win, "get_idle_seconds", lambda: 0)
    monkeypatch.setattr(tracker_module.platform_win, "get_foreground_app", lambda: ("A.exe", "A"))
    monkeypatch.setattr(tracker_module.time_utils, "today_str", lambda: "2026-01-01")
    wall = iter(("2026-01-01T10:00:00+00:00", "2026-01-01T10:00:02+00:00"))
    monkeypatch.setattr(tracker_module.time_utils, "utc_now_iso", lambda: next(wall))
    tracker = Tracker()
    clock = iter((2.0, 4.0, 4.0))
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: next(clock))
    tracker._last_tick_monotonic = 0.0
    tracker._last_summary_flush = 100.0
    tracker._tick()
    tracker.close_active_session_and_idle("2026-01-01T10:00:03+00:00")

    session = database.get_sessions_for_date("2026-01-01")[0]
    summary = database.get_daily_summary("2026-01-01")
    assert session.end_time is not None
    assert session.duration_seconds == 4
    assert database.get_active_session() is None
    assert summary.total_screen_seconds == 4


def test_tracker_start_does_not_duplicate_polling_thread(tmp_path, monkeypatch):
    tracker = Tracker()
    starts = []

    class FakeThread:
        def __init__(self, *args, **kwargs):
            starts.append("start")

        def is_alive(self):
            return True

        def start(self):
            pass

    monkeypatch.setattr(tracker_module.threading, "Thread", FakeThread)
    monkeypatch.setattr(tracker_module.db, "reconcile_orphaned_sessions", lambda: None)
    monkeypatch.setattr(tracker_module.db, "log_system_event", lambda event: None)
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: 1.0)
    monkeypatch.setattr(tracker_module.time_utils, "utc_now_iso", lambda: "2026-01-01T00:00:00+00:00")

    tracker.start()
    tracker.start()

    assert len(starts) == 1


def test_database_write_failure_is_not_silently_swallowed(tmp_path):
    database = Database(tmp_path / "write_failure.db")

    class FakeConn:
        def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        def commit(self):
            raise AssertionError("commit should not run after failure")

        def rollback(self):
            pass

    database.get_connection = lambda: FakeConn()  # type: ignore[assignment]

    with pytest.raises(sqlite3.OperationalError):
        database.log_system_event("boot")


def test_tracker_idle_round_trip_persists_separate_non_overlapping_rows(tmp_path, monkeypatch):
    database = Database(tmp_path / "idle.db")
    monkeypatch.setattr(tracker_module, "db", tracker_database_adapter(database))
    idle_values = iter((0, 120, 0))
    monkeypatch.setattr(tracker_module.platform_win, "get_idle_seconds", lambda: next(idle_values))
    monkeypatch.setattr(tracker_module.platform_win, "get_foreground_app", lambda: ("A.exe", "A"))
    monkeypatch.setattr(tracker_module.time_utils, "today_str", lambda: "2026-01-01")
    wall = iter(
        (
            "2026-01-01T10:00:00+00:00",
            "2026-01-01T10:00:02+00:00",
            "2026-01-01T10:00:03+00:00",
        )
    )
    monkeypatch.setattr(tracker_module.time_utils, "utc_now_iso", lambda: next(wall))
    tracker = Tracker()
    clock = iter((2.0, 3.0, 4.0, 5.0, 5.0))
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: next(clock))
    tracker._last_tick_monotonic = 0.0
    tracker._last_summary_flush = 100.0
    tracker._tick()
    tracker._tick()
    tracker._tick()
    tracker.close_active_session_and_idle("2026-01-01T10:00:04+00:00")

    sessions = database.get_sessions_for_date("2026-01-01")
    idle = database.get_active_idle_period()
    summary = database.get_daily_summary("2026-01-01")
    assert len(sessions) == 2
    assert all(session.end_time is not None for session in sessions)
    assert [session.duration_seconds for session in sessions] == [3, 2]
    assert idle is None
    idle_rows = database.get_connection().execute(
        "SELECT start_time, end_time, duration_seconds FROM idle_periods"
    ).fetchall()
    assert len(idle_rows) == 1
    assert idle_rows[0][2] == 1
    assert summary.total_screen_seconds == 4
    assert summary.total_idle_seconds == 1