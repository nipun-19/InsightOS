# system_tray.py
"""System tray icon and menu — the persistent anchor of InsightOS (§10).

As long as the tray icon exists, the app is running. This is the only
component allowed to terminate the process (via "Exit InsightOS").

Per ARCHITECTURE.md §6, this file must contain no tracking logic and no
database writes — it only reads via core/database.py for display, and
lazily opens the Dashboard / Desktop Widget / Updater on user action.
Those modules are imported inside their handler methods rather than at
module load time, matching §9's note that "Dashboard/Widget [are] opened
lazily on demand."
"""

from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from src.ui.toasts import show_toast

from src import config
from src.core import database as db
from src.utils import settings_store, time_utils
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SystemTray(QSystemTrayIcon):
    """The tray icon, its menu, and the periodic label/tooltip refresh."""

    def __init__(self, app: QApplication, on_exit: Callable[[], None]) -> None:
        """Build the tray icon and menu, and start the label refresh timer.

        Args:
            app: The running QApplication instance (used to open windows).
            on_exit: Callback invoked after the user confirms "Exit
                InsightOS" — main.py wires this to the shutdown sequence.
        """
        super().__init__(self._build_tray_icon())
        self._app = app
        self._on_exit = on_exit
        self._dashboard_window = None
        self._desktop_widget = None

        self.setToolTip(config.APP_NAME)
        self._build_menu()
        self.activated.connect(self._on_activated)

        self._refresh_timer = QTimer()
        self._refresh_timer.setInterval(config.TRAY_TOOLTIP_REFRESH_INTERVAL_SECONDS * 1000)
        self._refresh_timer.timeout.connect(self._refresh_label)
        self._refresh_timer.start()
        self._refresh_label()

        self.setVisible(True)
        logger.info("System tray initialized")

    def _build_tray_icon(self) -> QIcon:
        """Return the branded tray icon, falling back to the PNG asset if needed."""
        for icon_path in (config.TRAY_ICON_PATH, getattr(config, "TRAY_FALLBACK_ICON_PATH", None)):
            if icon_path is None:
                continue
            if icon_path.exists() and icon_path.is_file():
                icon = QIcon(str(icon_path))
                if not icon.isNull():
                    return icon
        return QIcon()

    def _build_menu(self) -> None:
        """Construct the tray context menu described in ARCHITECTURE.md §10."""
        menu = QMenu()
        menu.setStyleSheet(
            "QMenu { background-color: #ffffff; border: 1px solid rgba(15, 23, 42, 0.08); border-radius: 12px; padding: 6px; }"
            "QMenu::item { padding: 8px 12px; border-radius: 8px; }"
            "QMenu::item:selected { background-color: rgba(37, 99, 235, 0.10); color: #0f172a; }"
        )

        open_action = QAction("Open Dashboard", menu)
        open_action.triggered.connect(self._open_dashboard)
        menu.addAction(open_action)

        self._widget_action = QAction("Show Widget", menu)
        self._widget_action.setCheckable(True)
        self._widget_action.setChecked(bool(settings_store.get_value("widget_visible")))
        self._widget_action.toggled.connect(self._toggle_widget)
        menu.addAction(self._widget_action)

        menu.addSeparator()

        self._today_label_action = QAction("Today: 0m", menu)
        self._today_label_action.setEnabled(False)
        menu.addAction(self._today_label_action)

        menu.addSeparator()

        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        update_action = QAction("Check for Updates", menu)
        update_action.triggered.connect(self._check_for_updates)
        menu.addAction(update_action)

        exit_action = QAction("Exit InsightOS", menu)
        exit_action.triggered.connect(self._confirm_exit)
        menu.addAction(exit_action)

        self.setContextMenu(menu)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Open the Dashboard on left-click or double-click, per §10."""
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._open_dashboard()

    def _refresh_label(self) -> None:
        """Refresh the tooltip and the disabled "Today: …" menu label.

        Throttled to config.TRAY_TOOLTIP_REFRESH_INTERVAL_SECONDS (§10, §19),
        decoupled from the tracker's own polling interval.
        """
        today = time_utils.today_str()
        summary = db.get_today_summary(today)
        total = time_utils.format_duration(summary.total_screen_seconds)

        active = db.get_active_session()
        current_app = active.app_name if active else "Idle"

        self._today_label_action.setText(f"Today: {total}")
        self.setToolTip(f"{current_app} — Today: {total}")

    def _open_dashboard(self) -> None:
        """Open the Dashboard window, creating it if it isn't already open.

        Per §9, Dashboard windows are destroyed on close, so a fresh
        instance is created if the previous one was closed.
        """
        from src.ui.dashboard.dashboard_window import DashboardWindow  # lazy: avoid UI import cycle

        if self._dashboard_window is None:
            self._dashboard_window = DashboardWindow()
            self._dashboard_window.destroyed.connect(self._on_dashboard_closed)
        self._dashboard_window.show()
        self._dashboard_window.raise_()
        self._dashboard_window.activateWindow()

    def _on_dashboard_closed(self) -> None:
        """Clear the cached Dashboard reference once its window is destroyed."""
        self._dashboard_window = None

    def _toggle_widget(self, checked: bool) -> None:
        """Show or hide the Desktop Widget, persisting the choice.

        Per §11, the widget is hidden (not destroyed) on close, so it's
        created once and reused for the app's lifetime.
        """
        from src.ui.desktop_widget import DesktopWidget  # lazy: avoid UI import cycle

        if self._desktop_widget is None:
            self._desktop_widget = DesktopWidget()
            self._app.desktop_widget = self._desktop_widget

        if checked:
            self._desktop_widget.show()
        else:
            self._desktop_widget.hide()
        settings_store.set_value("widget_visible", checked)

    def _open_settings(self) -> None:
        """Open the polished settings dialog."""
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        show_toast("Settings updated", "Your preferences were saved.")

    def _check_for_updates(self) -> None:
        """Trigger a manual update check, bypassing the 24h automatic timer."""
        from src.services import updater  # lazy: updater is the only network-capable module

        updater.check_for_updates(force=True)
        show_toast("Update check started", "InsightOS is checking for the latest release.")

    def _confirm_exit(self) -> None:
        """Show the exit confirmation dialog and invoke on_exit if accepted."""
        answer = QMessageBox.question(
            None,
            "Exit InsightOS",
            "This will stop usage tracking. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._on_exit()