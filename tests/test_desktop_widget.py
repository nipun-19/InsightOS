import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.core import platform_win
from src.ui.dashboard.dashboard_window import DashboardWindow
from src.ui.desktop_widget import DesktopWidget, NavigationButton, friendly_app_name
from src.ui.settings_dialog import SettingsDialog
from src.utils import settings_store


def test_friendly_app_name_removes_executable_suffix_and_maps_known_apps() -> None:
    assert friendly_app_name("msedge.exe") == "Microsoft Edge"
    assert friendly_app_name("code.exe") == "Visual Studio Code"
    assert friendly_app_name("spotify.exe") == "Spotify"
    assert friendly_app_name("MyApp.exe") == "Myapp"


def test_dashboard_window_constructs_with_today_and_history_tabs() -> None:
    app = QApplication.instance() or QApplication([])
    window = DashboardWindow()
    try:
        assert window.count() == 2
        assert window.tabText(0) == "Today"
        assert window.tabText(1) == "History"
    finally:
        window.close()
        app.quit()


def test_find_desktop_shell_parent_prefers_hidden_workerw_over_progman(monkeypatch) -> None:
    worker_hwnd = 0x10101
    progman_hwnd = 0x10138

    class FakeUser32:
        def IsWindow(self, hwnd: int) -> bool:
            return hwnd in {worker_hwnd, progman_hwnd}

        def IsWindowVisible(self, hwnd: int) -> bool:
            return hwnd == progman_hwnd

        def EnumWindows(self, callback, lparam: int) -> bool:
            for hwnd in (worker_hwnd, progman_hwnd):
                callback(hwnd, lparam)
            return True

        def GetClassNameW(self, hwnd: int, buffer: ctypes.c_wchar_p, size: int) -> int:
            buffer.value = "WorkerW" if hwnd == worker_hwnd else "Progman"
            return 0

        def GetWindowThreadProcessId(self, hwnd: int, pid_ptr) -> int:
            pid_ptr.value = 11988
            return 1

        def GetWindowRect(self, hwnd: int, rect) -> bool:
            r = ctypes.cast(rect, ctypes.POINTER(wintypes.RECT)).contents
            r.left = 0
            r.top = 0
            r.right = 1920
            r.bottom = 1080
            return True

    monkeypatch.setattr(platform_win, "_USER32", FakeUser32())
    monkeypatch.setattr(platform_win, "get_shell_window", lambda: progman_hwnd)
    monkeypatch.setattr(platform_win, "get_desktop_window", lambda: 0)

    assert platform_win.find_desktop_shell_parent() == worker_hwnd


def test_desktop_foreground_detection_accepts_shell_and_widget_owned_popup(monkeypatch) -> None:
    owners = {33: 22, 22: 11, 99: 0}

    class FakeUser32:
        def GetWindow(self, hwnd: int, command: int) -> int:
            assert command == platform_win.GW_OWNER
            return owners.get(hwnd, 0)

    foreground = {"hwnd": 1, "class": "Progman"}
    monkeypatch.setattr(platform_win, "_USER32", FakeUser32())
    monkeypatch.setattr(platform_win, "get_foreground_window", lambda: foreground["hwnd"])
    monkeypatch.setattr(
        platform_win, "get_window_class_name", lambda hwnd: foreground["class"]
    )

    assert platform_win.is_desktop_or_owned_widget_foreground(11)
    foreground.update(hwnd=33, **{"class": "QtPopup"})
    assert platform_win.is_desktop_or_owned_widget_foreground(11)
    foreground.update(hwnd=99, **{"class": "Shell_TrayWnd"})
    assert not platform_win.is_desktop_or_owned_widget_foreground(11)


def test_set_window_topmost_uses_no_activation_or_geometry_changes(monkeypatch) -> None:
    calls = []

    class FakeUser32:
        def SetWindowPos(self, *args: int) -> bool:
            calls.append(args)
            return True

    monkeypatch.setattr(platform_win, "_USER32", FakeUser32())

    assert platform_win.set_window_topmost(123, True)
    hwnd, insert_after, x, y, width, height, flags = calls[0]
    assert hwnd == 123
    assert insert_after == platform_win.HWND_TOPMOST
    assert (x, y, width, height) == (0, 0, 0, 0)
    assert flags & platform_win.SWP_NOACTIVATE
    assert flags & platform_win.SWP_NOMOVE
    assert flags & platform_win.SWP_NOSIZE


def test_attach_widget_to_desktop_requires_valid_window_state(monkeypatch) -> None:
    class FakeUser32:
        def __init__(self) -> None:
            self.last_error = 0

        def GetWindowLongPtrW(self, hwnd: int, index: int) -> int:
            return 0x0

        def SetParent(self, hwnd: int, parent: int) -> int:
            return 1

        def IsWindowVisible(self, hwnd: int) -> bool:
            return False

        def GetParent(self, hwnd: int) -> int:
            return 0

        def GetWindowRect(self, hwnd: int, rect) -> bool:
            rect.left = 0
            rect.top = 0
            rect.right = 0
            rect.bottom = 0
            return True

        def MonitorFromWindow(self, hwnd: int, flag: int) -> int:
            return 0

        def SetWindowLongPtrW(self, hwnd: int, index: int, value: int) -> int:
            return 1

        def SetWindowPos(self, hwnd: int, hwnd_after: int, x: int, y: int, w: int, h: int, flags: int) -> bool:
            return True

        def GetForegroundWindow(self) -> int:
            return 0

        def GetShellWindow(self) -> int:
            return 0

        def GetDesktopWindow(self) -> int:
            return 0

        def GetClassNameW(self, hwnd: int, buffer: ctypes.c_wchar_p, size: int) -> int:
            buffer.value = "TestClass"
            return 0

    monkeypatch.setattr(platform_win, "_USER32", FakeUser32())
    monkeypatch.setattr(platform_win, "find_desktop_shell_parent", lambda: 123)

    assert platform_win.attach_widget_to_desktop(456) is False


def test_desktop_widget_is_non_topmost_and_accepts_control_focus() -> None:
    app = QApplication.instance() or QApplication([])
    widget = DesktopWidget()
    try:
        window_id = int(widget.winId())
        active_window = app.activeWindow()
        widget._show_top_level_window()

        assert widget.isVisible() is True
        assert widget.parent() is None
        assert int(widget.winId()) == window_id
        assert not widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert not widget.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
        assert widget.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        assert widget._refresh_timer.isActive()
        assert app.activeWindow() is active_window
    finally:
        widget.close()
        app.quit()


def test_desktop_foreground_transitions_only_change_z_order(monkeypatch, tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("src.config.SETTINGS_FILE_PATH", tmp_path / "settings.json")
    monkeypatch.setattr("src.config.STARTUP_STATE_FILE_PATH", tmp_path / "startup_state.json")
    foreground_is_desktop = False
    z_order_changes = []
    foreground_callback = []
    monkeypatch.setattr(
        platform_win,
        "is_desktop_or_owned_widget_foreground",
        lambda hwnd: foreground_is_desktop,
    )
    monkeypatch.setattr(
        platform_win,
        "watch_foreground_changes",
        lambda callback: foreground_callback.append(callback) or (1, callback),
    )
    monkeypatch.setattr(platform_win, "unwatch_foreground_changes", lambda hook: True)
    monkeypatch.setattr(
        platform_win,
        "set_window_topmost",
        lambda hwnd, topmost: z_order_changes.append(topmost) or True,
    )
    widget = DesktopWidget()
    try:
        assert widget._refresh_timer.isActive()

        foreground_is_desktop = True
        foreground_callback[0]()
        foreground_is_desktop = False
        foreground_callback[0]()

        assert z_order_changes[-2:] == [True, False]
        assert widget.isVisible()
        assert widget._refresh_timer.isActive()
    finally:
        widget.close()
        app.quit()


def test_foreground_event_hook_keeps_callback_alive_and_unhooks(monkeypatch) -> None:
    seen = []

    class FakeUser32:
        def SetWinEventHook(self, event_min, event_max, module, callback, process_id, thread_id, flags):
            seen.append(("install", event_min, event_max, callback, flags))
            callback(9, event_min, 10, 0, 0, 11, 12)
            return 77

        def UnhookWinEvent(self, hook):
            seen.append(("unhook", hook))
            return True

    monkeypatch.setattr(platform_win, "_USER32", FakeUser32())
    hook = platform_win.watch_foreground_changes(lambda: seen.append(("foreground",)))

    assert hook is not None
    assert hook[0] == 77
    assert seen[1] == ("foreground",)
    assert platform_win.unwatch_foreground_changes(hook[0])
    assert seen[-1] == ("unhook", 77)


def test_widget_frame_keeps_its_styled_background_opaque() -> None:
    app = QApplication.instance() or QApplication([])
    widget = DesktopWidget()
    try:
        assert not widget._frame.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert "background-color: #F8FAFC;" in widget._frame.styleSheet()
    finally:
        widget.close()
        app.quit()


def test_today_caption_is_centered_below_the_ring_at_widget_size() -> None:
    app = QApplication.instance() or QApplication([])
    widget = DesktopWidget()
    try:
        ring = widget._progress_widget._ring_rect()
        caption = widget._progress_widget._caption_label.geometry()
        assert caption.left() * 2 + caption.width() == widget._progress_widget.width()
        assert caption.top() > ring.bottom()
        assert caption.bottom() < widget._progress_widget.height()
    finally:
        widget.close()
        app.quit()


def test_all_widget_controls_have_accessible_working_routes(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    widget = DesktopWidget()
    routes = []
    settings_writes = []
    previous_compact = widget._compact_mode
    monkeypatch.setattr(
        widget,
        "_show_widget_menu",
        lambda: routes.append("menu"),
    )
    monkeypatch.setattr(
        widget,
        "_open_dashboard",
        lambda tab_index=0: routes.append(("analytics", tab_index)),
    )
    monkeypatch.setattr(widget, "_open_settings", lambda: routes.append("settings"))
    monkeypatch.setattr(settings_store, "set_value", lambda key, value: settings_writes.append((key, value)))
    try:
        assert widget._menu_button.accessibleName() == "Widget options"
        assert widget._nav_buttons[0].accessibleName() == "Open analytics dashboard"
        assert widget._nav_buttons[1].accessibleName() == "Open settings"
        assert widget._nav_buttons[2].accessibleName() == "Toggle compact focus view"
        assert all(button.focusPolicy() == Qt.FocusPolicy.StrongFocus for button in widget._nav_buttons)

        QTest.mouseClick(widget._menu_button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(widget._nav_buttons[0], Qt.MouseButton.LeftButton)
        QTest.mouseClick(widget._nav_buttons[1], Qt.MouseButton.LeftButton)
        QTest.mouseClick(widget._nav_buttons[2], Qt.MouseButton.LeftButton)

        assert routes == ["menu", ("analytics", 0), "settings"]
        assert widget._compact_mode is not previous_compact
        assert ("widget_compact_mode", not previous_compact) in settings_writes
    finally:
        widget.close()
        app.quit()


def test_plus_and_focus_navigation_icons_are_visually_distinct() -> None:
    app = QApplication.instance() or QApplication([])
    images = []
    for icon in ("add", "focus"):
        button = NavigationButton(icon)
        button.resize(32, 35)
        image = QImage(button.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        button.render(image)
        images.append(image)
        button.close()

    assert images[0] != images[1]
    app.quit()


def test_theme_toggle_persists_and_updates_open_insightos_windows(monkeypatch, tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("src.config.SETTINGS_FILE_PATH", tmp_path / "settings.json")
    widget = DesktopWidget()
    restarted_widget = None
    dashboard = DashboardWindow()
    dialog = SettingsDialog()
    try:
        widget.set_theme("dark")
        assert settings_store.get_value("theme") == "dark"
        assert widget._theme == "dark"
        assert "#171C26" in widget._frame.styleSheet()
        assert widget._frame.palette().color(QPalette.ColorRole.Window).name() == "#171c26"
        assert "#171C26" in dashboard.styleSheet()
        assert "#171C26" in dialog.styleSheet()

        restarted_widget = DesktopWidget()
        assert restarted_widget._theme == "dark"
        assert "#171C26" in restarted_widget._frame.styleSheet()

        widget.set_theme("light")
        assert settings_store.get_value("theme") == "light"
        assert "#F8FAFC" in widget._frame.styleSheet()
        assert widget._frame.palette().color(QPalette.ColorRole.Window).name() == "#f8fafc"
        assert "#F8FAFC" in dashboard.styleSheet()
        assert "#F8FAFC" in dialog.styleSheet()
        assert "#F8FAFC" in restarted_widget._frame.styleSheet()
    finally:
        if restarted_widget is not None:
            restarted_widget.close()
        dialog.close()
        dashboard.close()
        widget.close()
        app.quit()


def test_widget_menu_dark_appearance_action_toggles_theme(monkeypatch, tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("src.config.SETTINGS_FILE_PATH", tmp_path / "settings.json")
    monkeypatch.setattr("src.config.STARTUP_STATE_FILE_PATH", tmp_path / "startup_state.json")
    widget = DesktopWidget()
    try:
        def choose_dark_appearance(menu, _position):
            action = next(action for action in menu.actions() if action.text() == "Dark appearance")
            action.trigger()
            return action

        monkeypatch.setattr(widget, "_exec_widget_menu", choose_dark_appearance)
        widget._show_widget_menu()

        assert settings_store.get_value("theme") == "dark"
        assert widget._theme == "dark"
    finally:
        widget.close()
        app.quit()


def test_widget_position_clamps_to_available_screen_geometry() -> None:
    app = QApplication.instance() or QApplication([])
    widget = DesktopWidget()
    try:
        screen = app.primaryScreen()
        assert screen is not None
        available = screen.availableGeometry()

        x, y = widget._clamp_position_to_screen(available.right() + 500, available.bottom() + 500)

        assert x == max(available.left(), available.right() - widget.width())
        assert y == max(available.top(), available.bottom() - widget.height())
    finally:
        widget.close()
        app.quit()
