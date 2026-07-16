"""Floating always-on-top mini overlay — the Desktop Widget (§11).

100% read-only: this file has no code path capable of writing to the
database (§6, §22 rule 7 — business logic never lives in UI files). It
only reads via core/database.py and renders. Hidden (not destroyed) on
close so re-showing it is instant (§9).
"""

from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

import config
from core import database as db
from utils import settings_store, time_utils
from utils.logger import get_logger

logger = get_logger(__name__)


class DesktopWidget(QWidget):
    """The small draggable overlay showing today's total and the current app."""

    def __init__(self) -> None:
        """Build the widget UI, restore its saved position, and start refreshing."""
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setFixedSize(config.WIDGET_WIDTH, config.WIDGET_HEIGHT)
        self._drag_offset: QPoint | None = None

        self._build_ui()
        self._restore_position()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(config.WIDGET_REFRESH_INTERVAL_SECONDS * 1000)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start()
        self._refresh()

    def _build_ui(self) -> None:
        """Lay out the Today total, current app, live timer, and open button."""
        layout = QVBoxLayout(self)

        today_caption = QLabel("Today")
        self._today_value_label = QLabel("0m")

        current_app_caption = QLabel("Current App")
        self._current_app_label = QLabel("—")
        self._current_app_timer_label = QLabel("00:00:00")

        self._open_dashboard_button = QPushButton("Open Dashboard")
        self._open_dashboard_button.clicked.connect(self._open_dashboard)

        for widget in (
            today_caption,
            self._today_value_label,
            current_app_caption,
            self._current_app_label,
            self._current_app_timer_label,
            self._open_dashboard_button,
        ):
            layout.addWidget(widget)

    def _refresh(self) -> None:
        """Re-read today's summary and the active session, and update labels.

        Reads only database.get_today_summary() and
        database.get_active_session(), per §11.
        """
        today = time_utils.today_str()
        summary = db.get_today_summary(today)
        self._today_value_label.setText(time_utils.format_duration(summary.total_screen_seconds))

        active = db.get_active_session()
        if active is not None:
            self._current_app_label.setText(active.app_name)
            elapsed = time_utils.seconds_between(active.start_time, time_utils.utc_now_iso())
            self._current_app_timer_label.setText(time_utils.format_duration_hms(elapsed))
        else:
            self._current_app_label.setText("Idle")
            self._current_app_timer_label.setText("00:00:00")

    def _open_dashboard(self) -> None:
        """Open the Dashboard window (lazy import per §6)."""
        from ui.dashboard.dashboard_window import DashboardWindow  # lazy: avoid UI import cycle

        window = DashboardWindow()
        window.show()
        window.raise_()
        window.activateWindow()

    def _restore_position(self) -> None:
        """Move the widget to its last saved position from settings.json."""
        x = settings_store.get_value("widget_x")
        y = settings_store.get_value("widget_y")
        self.move(int(x), int(y))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin a drag when the left mouse button is pressed anywhere on the widget."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Move the widget while dragging."""
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """End a drag and persist the final position to settings.json."""
        if self._drag_offset is not None:
            self._drag_offset = None
            settings_store.set_value("widget_x", self.pos().x())
            settings_store.set_value("widget_y", self.pos().y())

    def contextMenuEvent(self, event) -> None:
        """Right-click menu: Open Dashboard / Hide Widget, per §11."""
        menu = QMenu(self)
        open_action = menu.addAction("Open Dashboard")
        hide_action = menu.addAction("Hide Widget")

        chosen = menu.exec(event.globalPos())
        if chosen == open_action:
            self._open_dashboard()
        elif chosen == hide_action:
            self.hide()
            settings_store.set_value("widget_visible", False)
