import ctypes
from types import SimpleNamespace

from src import config
from src.core import platform_win, tracker as tracker_module
from src.core.database import Database
from src.core.models import DailySummary
from src.core.tracker import Tracker, TrackerState


class FakeDatabase:
    def __init__(self) -> None:
        self.next_id = 1
        self.open_sessions = []
        self.closed_sessions = []
        self.open_idle = []
        self.closed_idle = []
        self.summary_updates = []

    def open_app_session(self, app_name, window_title, start_time, date):
        session_id = self.next_id
        self.next_id += 1
        self.open_sessions.append((session_id, app_name, window_title, start_time, date))
        return session_id

    def close_app_session(self, session_id, end_time, duration_seconds=None):
        self.closed_sessions.append((session_id, end_time, duration_seconds))

    def open_idle_period(self, start_time, date):
        idle_id = self.next_id
        self.next_id += 1
        self.open_idle.append((idle_id, start_time, date))
        return idle_id

    def close_idle_period(self, idle_id, end_time):
        self.closed_idle.append((idle_id, end_time))

    def upsert_daily_summary(self, date, screen_delta=0, idle_delta=0, activity_time=None):
        self.summary_updates.append((date, screen_delta, idle_delta, activity_time))


def make_tracker(monkeypatch, foreground_results, idle_results=None):
    fake_db = FakeDatabase()
    monkeypatch.setattr(tracker_module, "db", fake_db)
    results = iter(foreground_results)
    idle_values = iter(idle_results or [0] * len(foreground_results))
    monkeypatch.setattr(tracker_module.platform_win, "get_foreground_app", lambda: next(results))
    monkeypatch.setattr(tracker_module.platform_win, "get_idle_seconds", lambda: next(idle_values))
    tracker = Tracker()
    tracker._last_summary_flush = 0
    return tracker, fake_db


def test_normal_polling_persists_measured_elapsed_time(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [("A.exe", "A")])
    tracker._last_tick_monotonic = 10.0
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: 13.5)
    monkeypatch.setattr(tracker_module.time_utils, "today_str", lambda: "today")
    monkeypatch.setattr(tracker_module.time_utils, "utc_now_iso", lambda: "now")

    tracker._tick()
    tracker._flush_pending_summary("now", "today")

    assert fake_db.summary_updates == [("today", 3, 0, "now")]


def test_delayed_tick_counts_elapsed_time_not_one_poll_interval(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [("A.exe", "A")])
    tracker._last_tick_monotonic = 10.0
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: 25.0)

    tracker._tick()
    tracker._flush_pending_summary("now", "today")

    assert fake_db.summary_updates[0][1] == 15
    assert fake_db.summary_updates[0][1] != int(config.POLL_INTERVAL_SECONDS)


def test_app_switch_closes_a_and_opens_b(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [("A.exe", "A"), ("B.exe", "B")])
    tracker._last_tick_monotonic = 10.0
    clock = iter((12.0, 12.0, 14.0, 14.0))
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: next(clock))

    tracker._tick()
    tracker._tick()

    assert [row[1] for row in fake_db.open_sessions] == ["A.exe", "B.exe"]
    assert [row[0] for row in fake_db.closed_sessions] == [1]


def test_startup_with_active_app_starts_one_session_without_phantom_gap(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [("A.exe", "A")])
    tracker._last_tick_monotonic = 10.0
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: 12.0)
    monkeypatch.setattr(tracker_module.time_utils, "utc_now_iso", lambda: "2026-01-01T10:00:02+00:00")
    monkeypatch.setattr(tracker_module.time_utils, "today_str", lambda: "2026-01-01")

    tracker._tick()

    assert len(fake_db.open_sessions) == 1
    assert len(fake_db.closed_sessions) == 0
    assert fake_db.open_sessions[0][1:] == ("A.exe", "A", "2026-01-01T10:00:02+00:00", "2026-01-01")
    assert tracker.current_session_snapshot() == ("A.exe", 2.0)


def test_screen_total_snapshot_includes_unflushed_time_only_for_its_date(monkeypatch):
    monkeypatch.setattr(
        tracker_module,
        "db",
        SimpleNamespace(
            get_today_summary=lambda date: DailySummary(
                date,
                total_screen_seconds=100 if date == "2026-10-22" else 0,
            )
        ),
    )
    tracker = Tracker()
    tracker._queue_summary_update(screen_delta=14.5, summary_date="2026-10-22")

    assert tracker.today_screen_total_snapshot("2026-10-22") == 114.5
    assert tracker.today_screen_total_snapshot("2026-10-23") == 0


def test_same_app_repeats_do_not_duplicate_session(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [("A.exe", "A"), ("A.exe", "A")])
    tracker._last_tick_monotonic = 10.0
    clock = iter((12.0, 14.0, 14.0))
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(tracker_module.time_utils, "utc_now_iso", lambda: "2026-01-01T10:00:02+00:00")
    monkeypatch.setattr(tracker_module.time_utils, "today_str", lambda: "2026-01-01")

    tracker._tick()
    tracker._tick()

    assert [row[1] for row in fake_db.open_sessions] == ["A.exe"]
    assert len(fake_db.closed_sessions) == 0
    assert tracker.current_session_snapshot() == ("A.exe", 4.0)


def test_idle_threshold_closes_active_session(monkeypatch):
    tracker, fake_db = make_tracker(
        monkeypatch,
        [("A.exe", "A"), ("A.exe", "A")],
        [0, config.IDLE_THRESHOLD_SECONDS],
    )
    tracker._last_tick_monotonic = 10.0
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: 12.0)
    tracker._tick()

    tracker._tick()

    assert tracker.state == TrackerState.IDLE
    assert fake_db.closed_sessions == [(1, fake_db.open_idle[0][1], 2)]
    assert len(fake_db.open_idle) == 1


def test_idle_threshold_counts_final_active_interval_in_session_without_recounting_screen_summary(monkeypatch):
    tracker, fake_db = make_tracker(
        monkeypatch,
        [("A.exe", "A")],
        [config.IDLE_THRESHOLD_SECONDS],
    )
    tracker._active_session_id = 1
    tracker._active_session_app = "A.exe"
    tracker._active_session_elapsed = 2.0
    tracker._last_tick_wall_iso = "2026-01-01T10:00:01+00:00"
    tracker._last_tick_monotonic = 10.0
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: 12.0)
    monkeypatch.setattr(tracker_module.time_utils, "today_str", lambda: "2026-01-01")
    monkeypatch.setattr(tracker_module.time_utils, "utc_now_iso", lambda: "2026-01-01T10:00:02+00:00")

    tracker._tick()

    assert tracker.state == TrackerState.IDLE
    assert fake_db.closed_sessions == [(1, "2026-01-01T10:00:02+00:00", 4)]
    assert fake_db.summary_updates == []


def test_shutdown_closes_and_flushes_active_session(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [])
    tracker._active_session_id = 7
    tracker._active_session_app = "A.exe"
    tracker._pending_screen_seconds = 4.9

    tracker.close_active_session_and_idle("shutdown")

    assert fake_db.closed_sessions == [(7, "shutdown", 0)]
    assert fake_db.summary_updates == [(tracker_module.time_utils.today_str(), 4, 0, "shutdown")]
    assert tracker._active_session_id is None


def test_shutdown_includes_final_interval_once(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [])
    tracker._active_session_id = 7
    tracker._active_session_app = "A.exe"
    tracker._active_session_elapsed = 3.0
    tracker._last_tick_monotonic = 10.0
    tracker._last_tick_wall_iso = "2026-01-01T10:00:00+00:00"
    tracker._last_summary_flush = 100.0
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: 15.0)
    monkeypatch.setattr(tracker_module.time_utils, "today_str", lambda: "2026-01-01")

    tracker.close_active_session_and_idle("2026-01-01T10:00:05+00:00")

    assert fake_db.closed_sessions == [(7, "2026-01-01T10:00:05+00:00", 8)]
    assert fake_db.summary_updates == [
        ("2026-01-01", 5, 0, "2026-01-01T10:00:05+00:00")
    ]


def test_summary_is_not_incremented_twice(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [("A.exe", "A")])
    tracker._last_tick_monotonic = 10.0
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: 12.0)

    tracker._tick()
    tracker._flush_pending_summary("now", "today")

    assert fake_db.summary_updates[0][1] == 2
    assert len(fake_db.summary_updates) == 1


def test_unresolved_foreground_does_not_create_or_count_session(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [(None, "Unknown")])
    tracker._last_tick_monotonic = 10.0
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: 20.0)

    tracker._tick()
    tracker._flush_pending_summary("now", "today")

    assert fake_db.open_sessions == []
    assert fake_db.summary_updates == []


def test_sleep_wake_resets_monotonic_baseline(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [("A.exe", "A")])
    tracker._state = TrackerState.POLLING
    tracker._active_session_id = 1
    tracker._active_session_app = "A.exe"
    tracker._last_tick_monotonic = 10.0
    clock = iter((11.0, 1000.0))
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(tracker_module.time_utils, "utc_now_iso", lambda: "now")

    tracker.on_sleep()
    tracker.on_wake()

    assert tracker._last_tick_monotonic == 1000.0
    assert fake_db.closed_sessions == [(1, "now", 0)]


def test_reconciliation_is_delegated_once_on_start(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [])
    calls = []
    fake_db.reconcile_orphaned_sessions = lambda: calls.append("reconcile")
    fake_db.log_system_event = lambda event: calls.append(event)
    monkeypatch.setattr(tracker_module.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))

    tracker.start()

    assert calls == ["reconcile", "boot"]


def test_foreground_executable_resolution_returns_process_basename(monkeypatch):
    class FakeUser32:
        def GetForegroundWindow(self):
            return 10

        def GetWindowTextW(self, hwnd, buffer, size):
            buffer.value = "Alpha"

        def GetWindowThreadProcessId(self, hwnd, process_id):
            process_id = ctypes.cast(process_id, ctypes.POINTER(ctypes.wintypes.DWORD))
            process_id.contents.value = 42
            return 1

        def GetClassNameW(self, hwnd, buffer, size):
            buffer.value = "NotShell"
            return len(buffer.value)

    class FakeKernel32:
        def OpenProcess(self, access, inherit, process_id):
            return 99

        def QueryFullProcessImageNameW(self, handle, flags, buffer, length):
            buffer.value = r"C:\Apps\Alpha.exe"
            length = ctypes.cast(length, ctypes.POINTER(ctypes.wintypes.DWORD))
            length.contents.value = len(buffer.value)
            return 1

        def CloseHandle(self, handle):
            return 1

    monkeypatch.setattr(platform_win.sys, "platform", "win32")
    monkeypatch.setattr(platform_win, "_USER32", FakeUser32())
    monkeypatch.setattr(platform_win, "_KERNEL32", FakeKernel32())

    assert platform_win.get_foreground_app() == ("Alpha.exe", "Alpha")


def test_desktop_shell_windows_are_ignored_as_activity(monkeypatch):
    class FakeUser32:
        def GetForegroundWindow(self):
            return 10

        def GetWindowTextW(self, hwnd, buffer, size):
            buffer.value = "Program Manager"

        def GetWindowThreadProcessId(self, hwnd, process_id):
            process_id = ctypes.cast(process_id, ctypes.POINTER(ctypes.wintypes.DWORD))
            process_id.contents.value = 42
            return 1

        def GetClassNameW(self, hwnd, buffer, size):
            buffer.value = "Progman"
            return len(buffer.value)

    class FakeKernel32:
        def OpenProcess(self, access, inherit, process_id):
            return 99

        def QueryFullProcessImageNameW(self, handle, flags, buffer, length):
            buffer.value = r"C:\Windows\explorer.exe"
            length = ctypes.cast(length, ctypes.POINTER(ctypes.wintypes.DWORD))
            length.contents.value = len(buffer.value)
            return 1

        def CloseHandle(self, handle):
            return 1

    monkeypatch.setattr(platform_win.sys, "platform", "win32")
    monkeypatch.setattr(platform_win, "_USER32", FakeUser32())
    monkeypatch.setattr(platform_win, "_KERNEL32", FakeKernel32())

    assert platform_win.get_foreground_app() == (None, None)


def test_explorer_shell_surfaces_are_ignored_as_activity(monkeypatch):
    class FakeUser32:
        class_name = ""

        def GetForegroundWindow(self):
            return 30

        def GetWindowTextW(self, hwnd, buffer, size):
            buffer.value = ""

        def GetClassNameW(self, hwnd, buffer, size):
            buffer.value = self.class_name
            return len(buffer.value)

    fake_user32 = FakeUser32()
    monkeypatch.setattr(platform_win.sys, "platform", "win32")
    monkeypatch.setattr(platform_win, "_USER32", fake_user32)

    for shell_class in (
        "Shell_TrayWnd",
        "Shell_SecondaryTrayWnd",
        "ApplicationManager_DesktopShellWindow",
        "XamlExplorerHostIslandWindow",
    ):
        fake_user32.class_name = shell_class
        assert platform_win.get_foreground_app() == (None, None)


def test_real_file_explorer_window_is_not_rejected_as_shell(monkeypatch):
    class FakeUser32:
        def GetForegroundWindow(self):
            return 20

        def GetWindowTextW(self, hwnd, buffer, size):
            buffer.value = "D:\\Projects"

        def GetWindowThreadProcessId(self, hwnd, process_id):
            process_id = ctypes.cast(process_id, ctypes.POINTER(ctypes.wintypes.DWORD))
            process_id.contents.value = 42
            return 1

        def GetClassNameW(self, hwnd, buffer, size):
            buffer.value = "CabinetWClass"
            return len(buffer.value)

    class FakeKernel32:
        def OpenProcess(self, access, inherit, process_id):
            return 99

        def QueryFullProcessImageNameW(self, handle, flags, buffer, length):
            buffer.value = r"C:\Windows\explorer.exe"
            length = ctypes.cast(length, ctypes.POINTER(ctypes.wintypes.DWORD))
            length.contents.value = len(buffer.value)
            return 1

        def CloseHandle(self, handle):
            return 1

    monkeypatch.setattr(platform_win.sys, "platform", "win32")
    monkeypatch.setattr(platform_win, "_USER32", FakeUser32())
    monkeypatch.setattr(platform_win, "_KERNEL32", FakeKernel32())

    assert platform_win.get_foreground_app() == ("explorer.exe", "D:\\Projects")


def test_explorer_system_dialog_is_rejected_as_shell_activity(monkeypatch):
    class FakeUser32:
        def GetForegroundWindow(self):
            return 20

        def GetWindowTextW(self, hwnd, buffer, size):
            buffer.value = "Shut Down Windows"

        def GetWindowThreadProcessId(self, hwnd, process_id):
            process_id = ctypes.cast(process_id, ctypes.POINTER(ctypes.wintypes.DWORD))
            process_id.contents.value = 42
            return 1

        def GetClassNameW(self, hwnd, buffer, size):
            buffer.value = "#32770"
            return len(buffer.value)

    class FakeKernel32:
        def OpenProcess(self, access, inherit, process_id):
            return 99

        def QueryFullProcessImageNameW(self, handle, flags, buffer, length):
            buffer.value = r"C:\Windows\explorer.exe"
            length = ctypes.cast(length, ctypes.POINTER(ctypes.wintypes.DWORD))
            length.contents.value = len(buffer.value)
            return 1

        def CloseHandle(self, handle):
            return 1

    monkeypatch.setattr(platform_win.sys, "platform", "win32")
    monkeypatch.setattr(platform_win, "_USER32", FakeUser32())
    monkeypatch.setattr(platform_win, "_KERNEL32", FakeKernel32())

    assert platform_win.get_foreground_app() == (None, None)


def test_real_file_explorer_window_under_shell_parent_is_not_rejected(monkeypatch):
    class FakeUser32:
        def GetForegroundWindow(self):
            return 20

        def GetWindowTextW(self, hwnd, buffer, size):
            buffer.value = "Downloads"

        def GetWindowThreadProcessId(self, hwnd, process_id):
            process_id = ctypes.cast(process_id, ctypes.POINTER(ctypes.wintypes.DWORD))
            process_id.contents.value = 42
            return 1

        def GetClassNameW(self, hwnd, buffer, size):
            if hwnd == 20:
                buffer.value = "CabinetWClass"
            else:
                buffer.value = "WorkerW"
            return len(buffer.value)

        def GetParent(self, hwnd):
            return 99 if hwnd == 20 else None

    class FakeKernel32:
        def OpenProcess(self, access, inherit, process_id):
            return 99

        def QueryFullProcessImageNameW(self, handle, flags, buffer, length):
            buffer.value = r"C:\Windows\explorer.exe"
            length = ctypes.cast(length, ctypes.POINTER(ctypes.wintypes.DWORD))
            length.contents.value = len(buffer.value)
            return 1

        def CloseHandle(self, handle):
            return 1

    monkeypatch.setattr(platform_win.sys, "platform", "win32")
    monkeypatch.setattr(platform_win, "_USER32", FakeUser32())
    monkeypatch.setattr(platform_win, "_KERNEL32", FakeKernel32())

    assert platform_win.get_foreground_app() == ("explorer.exe", "Downloads")


def test_reconciliation_closes_orphans_once_without_duplicates(tmp_path):
    database = Database(tmp_path / "audit.db")
    session_id = database.start_app_session("A.exe", "A", "2026-01-01T00:00:00+00:00", "2026-01-01")

    database.reconcile_orphaned_sessions()
    first = database.get_sessions_for_date("2026-01-01")[0]
    database.reconcile_orphaned_sessions()
    second = database.get_sessions_for_date("2026-01-01")[0]

    assert session_id == first.id == second.id
    assert first.end_time == first.start_time
    assert first.duration_seconds == 0
    assert second.end_time == first.end_time
    assert len(database.get_sessions_for_date("2026-01-01")) == 1


def test_wall_clock_forward_jump_does_not_change_monotonic_duration(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [("A.exe", "A"), ("B.exe", "B")])
    tracker._last_tick_monotonic = 10.0
    monotonic_clock = iter((15.0, 15.0, 16.0, 16.0))
    wall_clock = iter(("2026-01-01T00:00:00+00:00", "2026-01-01T02:00:00+00:00"))
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: next(monotonic_clock))
    monkeypatch.setattr(tracker_module.time_utils, "utc_now_iso", lambda: next(wall_clock))

    tracker._tick()
    tracker._tick()

    assert fake_db.closed_sessions[0][2] == 5


def test_wall_clock_backward_jump_does_not_change_monotonic_duration(monkeypatch):
    tracker, fake_db = make_tracker(monkeypatch, [("A.exe", "A"), ("B.exe", "B")])
    tracker._last_tick_monotonic = 10.0
    monotonic_clock = iter((15.0, 15.0, 16.0, 16.0))
    wall_clock = iter(("2026-01-01T02:00:00+00:00", "2026-01-01T00:00:00+00:00"))
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: next(monotonic_clock))
    monkeypatch.setattr(tracker_module.time_utils, "utc_now_iso", lambda: next(wall_clock))

    tracker._tick()
    tracker._tick()

    assert fake_db.closed_sessions[0][2] == 5