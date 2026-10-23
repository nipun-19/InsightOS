from types import SimpleNamespace

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from src import config
from src.core.models import AppSession, DailySummary
from src.core import tracker as tracker_module
from src.core.tracker import Tracker
from src.ui import desktop_widget as widget_module
from src.ui.desktop_widget import DesktopWidget
from src.ui.dashboard import today_view


def test_tracker_splits_active_summary_at_midnight(monkeypatch):
    class FakeDatabase:
        def __init__(self):
            self.sessions = []
            self.updates = []

        def open_app_session(self, *args):
            self.sessions.append(args)
            return 1

        def close_app_session(self, *args, **kwargs):
            pass

        def upsert_daily_summary(self, date, screen_delta=0, idle_delta=0, activity_time=None):
            self.updates.append((date, screen_delta, idle_delta, activity_time))

    database = FakeDatabase()
    monkeypatch.setattr(tracker_module, "db", database)
    monkeypatch.setattr(tracker_module.platform_win, "get_idle_seconds", lambda: 0)
    monkeypatch.setattr(tracker_module.platform_win, "get_foreground_app", lambda: ("A.exe", "A"))
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: 2.0)
    monkeypatch.setattr(tracker_module.time_utils, "utc_now_iso", lambda: "2026-01-02T00:00:01+00:00")
    monkeypatch.setattr(tracker_module.time_utils, "today_str", lambda: "2026-01-02")
    monkeypatch.setattr(tracker_module.time_utils, "to_local", lambda value: value)

    tracker = Tracker()
    tracker._last_tick_monotonic = 0.0
    tracker._last_summary_flush = 2.0
    tracker._last_tick_wall_iso = "2026-01-01T23:59:59+00:00"
    tracker._tick()
    tracker._flush_pending_summary("2026-01-02T00:00:01+00:00", "2026-01-02")

    assert [update[0] for update in database.updates] == ["2026-01-01", "2026-01-02"]
    assert sum(update[1] for update in database.updates) == 2


def test_subsecond_midnight_remainder_is_not_carried_into_new_day(monkeypatch):
    database = SimpleNamespace(
        open_app_session=lambda *args: 1,
        close_app_session=lambda *args, **kwargs: None,
        upsert_daily_summary=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(tracker_module, "db", database)
    monkeypatch.setattr(tracker_module.platform_win, "get_idle_seconds", lambda: 0)
    monkeypatch.setattr(tracker_module.platform_win, "get_foreground_app", lambda: ("A.exe", "A"))
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: 0.2)
    monkeypatch.setattr(tracker_module.time_utils, "utc_now_iso", lambda: "2026-01-02T00:00:00.100000+00:00")
    monkeypatch.setattr(tracker_module.time_utils, "today_str", lambda: "2026-01-02")
    monkeypatch.setattr(tracker_module.time_utils, "to_local", lambda value: value)

    tracker = Tracker()
    tracker._last_tick_monotonic = 0.0
    tracker._last_summary_flush = 0.2
    tracker._last_tick_wall_iso = "2026-01-01T23:59:59.900000+00:00"
    tracker._tick()

    assert tracker._pending_summary_date == "2026-01-02"


def make_widget(monkeypatch, tracker_snapshot, active_session, summary, top_apps):
    app = QApplication.instance() or QApplication([])
    database = SimpleNamespace(
        get_active_session=lambda: active_session,
        get_today_summary=lambda date: summary,
        get_top_apps=lambda dates, limit: top_apps,
        get_history_stats=lambda dates: {"total_seconds": sum(seconds for _, seconds in top_apps)},
    )
    monkeypatch.setattr(widget_module, "db", database)
    tracker = SimpleNamespace(
        current_session_snapshot=lambda: tracker_snapshot,
        today_screen_total_snapshot=lambda date: summary.total_screen_seconds,
    )
    widget = DesktopWidget(tracker)
    return app, widget


def test_widget_current_uses_tracker_snapshot(monkeypatch):
    active = AppSession(
        app_name="A.exe",
        start_time="2026-01-01T10:00:00+00:00",
        date="2026-01-01",
    )
    app, widget = make_widget(
        monkeypatch,
        ("A.exe", 42.0),
        active,
        DailySummary("2026-01-01"),
        [],
    )
    try:
        widget._refresh_live()
        assert widget._activity_name.text() == "A"
        assert widget._activity_time.text() == "00:00:42"
    finally:
        widget.close()
        app.quit()


def test_widget_refresh_reads_fresh_summary_and_top_apps_without_writes(monkeypatch):
    active = AppSession(
        app_name="A.exe",
        start_time="2026-01-01T10:00:00+00:00",
        date="2026-01-01",
    )
    writes = []
    app = QApplication.instance() or QApplication([])
    database = SimpleNamespace(
        get_active_session=lambda: active,
        get_today_summary=lambda date: DailySummary(date, total_screen_seconds=180),
        get_top_apps=lambda dates, limit: [("A.exe", 120), ("B.exe", 60)],
        upsert_daily_summary=lambda *args, **kwargs: writes.append((args, kwargs)),
    )
    monkeypatch.setattr(widget_module, "db", database)
    pending = {"seconds": 119.0}
    widget = DesktopWidget(
        SimpleNamespace(
            current_session_snapshot=lambda: ("A.exe", 120.0),
            today_screen_total_snapshot=lambda date: (
                database.get_today_summary(date).total_screen_seconds + pending["seconds"]
            ),
        )
    )
    try:
        widget._refresh_summary()
        assert widget._progress_widget._value == 299
        assert widget._progress_widget._value_label.text() == "4m"
        assert widget._top_apps_labels[0].text() == "A • 4m"
        assert widget._top_apps_labels[1].text() == "B • 1m"
        assert writes == []

        pending["seconds"] = 0.0
        database.get_today_summary = lambda date: DailySummary(date, total_screen_seconds=300)
        database.get_top_apps = lambda dates, limit: [("B.exe", 240)]
        widget._refresh_summary()
        assert widget._progress_widget._value_label.text() == "5m"
        assert widget._top_apps_labels[0].text() == "B • 4m"
    finally:
        widget.close()
        app.quit()


def test_widget_displays_pending_activity_before_first_minute(monkeypatch):
    active = AppSession(
        app_name="A.exe",
        start_time="2026-01-01T10:00:00+00:00",
        date="2026-01-01",
    )
    app = QApplication.instance() or QApplication([])
    database = SimpleNamespace(
        get_active_session=lambda: active,
        get_today_summary=lambda date: DailySummary(date),
        get_top_apps=lambda dates, limit: [],
        get_history_stats=lambda dates: {"total_seconds": 0},
    )
    monkeypatch.setattr(widget_module, "db", database)
    widget = DesktopWidget(
        SimpleNamespace(
            current_session_snapshot=lambda: ("A.exe", 17.0),
            today_screen_total_snapshot=lambda date: 17.0,
        )
    )
    monkeypatch.setattr(widget_module.time_utils, "today_str", lambda: "2026-01-01")
    try:
        widget._refresh_summary()
        assert widget._progress_widget._value == 17
        assert widget._progress_widget._value_label.text() == "<1m"
        assert widget._top_apps_labels[0].text() == "A • <1m"
    finally:
        widget.close()
        app.quit()


def test_widget_timer_refreshes_unflushed_screen_time(monkeypatch):
    active = AppSession(
        app_name="A.exe",
        start_time="2026-01-01T10:00:00+00:00",
        date="2026-01-01",
    )
    pending = {"seconds": 0.0}
    app = QApplication.instance() or QApplication([])
    database = SimpleNamespace(
        get_active_session=lambda: active,
        get_today_summary=lambda date: DailySummary(date, total_screen_seconds=180),
        get_top_apps=lambda dates, limit: [("A.exe", 120)],
        get_history_stats=lambda dates: {"total_seconds": 180},
    )
    monkeypatch.setattr(widget_module, "db", database)
    widget = DesktopWidget(
        SimpleNamespace(
            current_session_snapshot=lambda: ("A.exe", 120.0),
            today_screen_total_snapshot=lambda date: (
                database.get_today_summary(date).total_screen_seconds + pending["seconds"]
            ),
        )
    )
    try:
        assert widget._progress_widget._value == 180
        assert widget._refresh_timer.isActive()

        pending["seconds"] = 120.0
        QTest.qWait(config.WIDGET_LIVE_REFRESH_INTERVAL_SECONDS * 1000 + 100)

        assert widget._progress_widget._value == 300
        assert widget._progress_widget._value_label.text() == "5m"
        assert widget._refresh_timer.isActive()
    finally:
        widget.close()
        app.quit()


def test_widget_uses_persisted_sessions_when_daily_summary_is_missing(monkeypatch):
    active = AppSession(
        app_name="A.exe",
        start_time="2026-01-01T10:00:00+00:00",
        date="2026-01-01",
    )
    app, widget = make_widget(
        monkeypatch,
        ("A.exe", 30.0),
        active,
        DailySummary("2026-01-01"),
        [("A.exe", 50), ("B.exe", 20)],
    )
    monkeypatch.setattr(widget_module.time_utils, "today_str", lambda: "2026-01-01")
    try:
        widget._refresh_summary()
        assert widget._progress_widget._value_label.text() == "1m"
        assert widget._top_apps_labels[0].text() == "A • 1m"
    finally:
        widget.close()
        app.quit()


def test_today_view_surfaces_factual_summary_and_tracker_session(monkeypatch):
    app = QApplication.instance() or QApplication([])
    active = AppSession(
        app_name="A.exe",
        start_time="2026-01-01T10:00:00+00:00",
        date="2026-01-01",
    )
    database = SimpleNamespace(
        get_today_summary=lambda date: DailySummary(date, total_screen_seconds=300, total_idle_seconds=42),
        get_active_session=lambda: active,
        get_sessions_for_dates=lambda dates: [],
        get_top_apps=lambda dates, limit: [("A.exe", 120)],
        get_history_stats=lambda dates: {
            "total_sessions": 3,
            "longest_session_seconds": 90,
        },
    )
    monkeypatch.setattr(today_view, "db", database)
    monkeypatch.setattr(today_view.time_utils, "today_str", lambda: "2026-01-01")
    view = today_view.TodayView(tracker=SimpleNamespace(current_session_snapshot=lambda: ("A.exe", 150)))
    try:
        view.refresh()
        assert view._total_card.value_label.text() == "5m"
        assert view._idle_card.value_label.text() == "0m"
        assert view._session_count_card.value_label.text() == "3"
        assert view._longest_session_card.value_label.text() == "2m"
        assert view._current_app_card.value_label.text() == "A.exe"
        labels = [label.text() for label in view.findChildren(QLabel)]
        assert "Active time" in labels
        assert "Focus time" not in labels
    finally:
        view.close()
        app.quit()


def test_today_view_empty_state_is_factual(monkeypatch):
    app = QApplication.instance() or QApplication([])
    database = SimpleNamespace(
        get_today_summary=lambda date: DailySummary(date),
        get_active_session=lambda: None,
        get_sessions_for_dates=lambda dates: [],
        get_top_apps=lambda dates, limit: [],
        get_history_stats=lambda dates: {
            "total_sessions": 0,
            "longest_session_seconds": 0,
        },
    )
    monkeypatch.setattr(today_view, "db", database)
    view = today_view.TodayView()
    try:
        view.refresh()
        assert view._total_card.value_label.text() == "0m"
        assert view._idle_card.value_label.text() == "0m"
        assert view._session_count_card.value_label.text() == "0"
        assert view._longest_session_card.value_label.text() == "0m"
        assert view._current_app_card.value_label.text() == "Idle"
    finally:
        view.close()
        app.quit()


def test_desktop_widget_uses_factual_activity_language():
    app = QApplication.instance() or QApplication([])
    widget = DesktopWidget()
    try:
        assert widget._subtitle_label.text() == "Today's activity"
    finally:
        widget.close()
        app.quit()
