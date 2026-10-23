# desktop_widget.py
"""Desktop-native widget for InsightOS.

The widget is intentionally read-only and only renders data from the
existing database layer. It uses desktop-friendly window flags so it stays
out of the way of active applications while remaining visible on the
desktop surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import QApplication, QLabel, QHBoxLayout, QMenu, QToolButton, QVBoxLayout, QWidget

from src import config
from src.core import database as db
from src.core import platform_win
from src.ui.startup_state import StartupStateStore
from src.ui.theme import colors_for, current_theme
from src.utils import settings_store, time_utils
from src.utils.logger import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from src.core.tracker import Tracker


class CircularProgressWidget(QWidget):
    """A complete circular ring showing today's total tracked time."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._value = 0
        self._target = 1
        self._theme = current_theme()
        self._value_label = QLabel("0m", self)
        self._caption_label = QLabel("TODAY", self)
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_label.setStyleSheet(
            "QLabel { font-size: 18px; font-weight: 700; margin: 0px; padding: 0px; }"
        )
        self._caption_label.setStyleSheet(
            "QLabel { font-size: 7px; text-transform: uppercase; letter-spacing: 0.12em; font-weight: 700; margin: 0px; padding: 0px; }"
        )
        self.apply_theme(self._theme)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        ring_size = min(self.width(), max(0, self.height() - 14))
        ring_left = (self.width() - ring_size) // 2
        self._value_label.setGeometry(ring_left, 0, ring_size, ring_size)
        self._caption_label.setGeometry(0, ring_size, self.width(), self.height() - ring_size)
        super().resizeEvent(event)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        colors = colors_for(theme)
        self._value_label.setStyleSheet(
            f"QLabel {{ color: {colors['text']}; font-size: 18px; font-weight: 700; margin: 0px; padding: 0px; }}"
        )
        self._caption_label.setStyleSheet(
            f"QLabel {{ color: {colors['muted_text']}; font-size: 7px; text-transform: uppercase; letter-spacing: 0.12em; font-weight: 700; margin: 0px; padding: 0px; }}"
        )
        self.update()

    def set_value(self, value: int, target: int) -> None:
        """Update the ring state."""
        self._value = max(0, value)
        self._target = max(1, target)
        self._value_label.setText(time_utils.format_duration(value))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = self._ring_rect()

        base_pen = painter.pen()
        base_pen.setWidth(6)
        base_pen.setColor(QColor(148, 163, 184, 105 if self._theme == "dark" else 90))
        base_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        base_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(base_pen)
        painter.drawEllipse(rect)
        accent_pen = painter.pen()
        accent_pen.setWidth(6)
        accent_pen.setColor(QColor(37, 99, 235))
        accent_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        accent_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(accent_pen)
        painter.drawEllipse(rect)

    def _ring_rect(self) -> QRect:
        ring_size = min(self.width(), max(0, self.height() - 14))
        left = (self.width() - ring_size) // 2
        return QRect(left, 0, ring_size, ring_size).adjusted(8, 8, -8, -8)


class TopAppRow(QWidget):
    """A compact app row for the top applications list."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._icon_label = QLabel("•", self)
        self._name_label = QLabel("No activity yet", self)
        self._time_label = QLabel("0m", self)
        self._display_text = "No activity yet • 0m"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._icon_label.setFixedSize(12, 12)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet(
            "QLabel { background: rgba(37, 99, 235, 0.12); color: #2563EB; border-radius: 6px; font-size: 8px; font-weight: 700; }"
        )
        self._name_label.setStyleSheet(
            "QLabel { color: #0F172A; font-size: 11px; font-weight: 600; margin: 0px; padding: 0px; }"
        )
        self._time_label.setStyleSheet(
            "QLabel { color: #475569; font-size: 10px; font-weight: 600; margin: 0px; padding: 0px; }"
        )
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.apply_theme(current_theme())

        layout.addWidget(self._icon_label)
        layout.addWidget(self._name_label, stretch=1)
        layout.addWidget(self._time_label)

    def apply_theme(self, theme: str) -> None:
        colors = colors_for(theme)
        self._icon_label.setStyleSheet(
            "QLabel { background: rgba(37, 99, 235, 0.12); color: #2563EB; border-radius: 6px; font-size: 8px; font-weight: 700; }"
        )
        self._name_label.setStyleSheet(
            f"QLabel {{ color: {colors['text']}; font-size: 11px; font-weight: 600; margin: 0px; padding: 0px; }}"
        )
        self._time_label.setStyleSheet(
            f"QLabel {{ color: {colors['muted_text']}; font-size: 10px; font-weight: 600; margin: 0px; padding: 0px; }}"
        )

    def set_app(self, app_name: str, duration: str) -> None:
        self._name_label.setText(app_name)
        self._time_label.setText(duration)
        self._display_text = f"{app_name} • {duration}"

    def setText(self, text: str) -> None:
        self._display_text = text
        if " • " in text:
            name, duration = text.split(" • ", 1)
            self._name_label.setText(name)
            self._time_label.setText(duration)
        else:
            self._name_label.setText(text)
            self._time_label.setText("")

    def text(self) -> str:
        return self._display_text


class NavigationButton(QToolButton):
    """A simple line-style navigation icon."""

    def __init__(self, icon: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._icon = icon
        self._theme = current_theme()
        self._active = False
        self.setFixedHeight(28)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        accessible_name = {
            "analytics": "Open analytics dashboard",
            "add": "Open settings",
            "settings": "Open settings",
            "focus": "Toggle compact focus view",
        }[icon]
        self.setAccessibleName(accessible_name)
        self.setToolTip(accessible_name)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        idle_color = QColor(203, 213, 225) if self._theme == "dark" else QColor(71, 85, 105)
        color = QColor(37, 99, 235) if self._active else idle_color
        painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

        rect = self.rect().adjusted(0, 0, -1, -1)
        cx, cy = rect.center().x(), rect.center().y()
        size = 18
        left = cx - size / 2
        top = cy - size / 2
        if self.isDown() or self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(37, 99, 235, 24))
            painter.drawEllipse(rect.adjusted(3, 1, -3, -1))

        if self._icon == "analytics":
            points = [
                QPoint(int(left + 2), int(cy + 4)),
                QPoint(int(left + 6), int(cy)),
                QPoint(int(left + 10), int(cy + 6)),
                QPoint(int(left + 14), int(cy - 5)),
                QPoint(int(left + 18), int(cy + 2)),
            ]
            painter.drawPolyline(QPolygon(points))
            painter.drawLine(int(left + 2), int(cy + 8), int(left + 18), int(cy + 8))
        elif self._icon == "settings":
            painter.drawEllipse(int(left), int(top), int(size), int(size))
            painter.drawLine(cx, int(top - 2), cx, int(top + 3))
            painter.drawLine(cx, int(top + size - 3), cx, int(top + size + 2))
            painter.drawLine(int(left - 2), cy, int(left + 3), cy)
            painter.drawLine(int(left + size - 3), cy, int(left + size + 2), cy)
        elif self._icon == "focus":
            painter.drawEllipse(int(left), int(top), int(size), int(size))
            painter.drawLine(cx, int(top + 4), cx, int(top + size - 4))
            painter.drawLine(int(left + 4), cy, int(left + size - 4), cy)
        elif self._icon == "add":
            painter.drawLine(cx, int(cy - 6), cx, int(cy + 6))
            painter.drawLine(int(cx - 6), cy, int(cx + 6), cy)

        if self.hasFocus():
            painter.setPen(QPen(QColor(37, 99, 235, 180), 1, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 5, 5)

        painter.end()


class DesktopWidget(QWidget):
    """A desktop-native widget showing today's usage and current activity."""

    def __init__(self, tracker: "Tracker | None" = None) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setWindowOpacity(float(settings_store.get_value("widget_opacity")))
        self.setMouseTracking(True)
        self.setFixedSize(config.WIDGET_WIDTH, config.WIDGET_HEIGHT)
        self._drag_offset: QPoint | None = None
        self._enabled = bool(settings_store.get_value("widget_enabled"))
        self._compact_mode = bool(settings_store.get_value("widget_compact_mode"))
        self._theme = current_theme()
        self._tracker = tracker
        self._desktop_topmost: bool | None = None

        self._build_ui()
        self._restore_position()
        self._apply_layout_mode()
        self._restore_persisted_state()

        self._refresh_counter = 0
        self._last_live_signature: tuple[str, str] | None = None
        self._last_summary_signature: tuple[int, tuple[tuple[str, int], ...], str] | None = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(config.WIDGET_LIVE_REFRESH_INTERVAL_SECONDS * 1000)
        self._refresh_timer.timeout.connect(self._on_refresh_tick)
        self._refresh_timer.start()

        self._visibility_timer = QTimer(self)
        self._visibility_timer.setInterval(config.WIDGET_VISIBILITY_POLL_INTERVAL_MS)
        self._visibility_timer.timeout.connect(self._sync_visibility)
        self._visibility_timer.start()
        self._foreground_hook = platform_win.watch_foreground_changes(self._sync_visibility)

        self._apply_opacity()
        self._refresh_summary()
        self._refresh_live()
        self._sync_visibility()
        logger.info("DesktopWidget initialized: geometry=%s, visible=%s", self.geometry(), self.isVisible())

    def _build_ui(self) -> None:
        self._frame = QWidget(self)
        self._frame.setObjectName("widgetFrame")
        self._frame.setStyleSheet(
            "QWidget#widgetFrame {"
            "background-color: rgba(248, 250, 252, 0.96);"
            "border: 1px solid rgba(15, 23, 42, 0.08);"
            "border-radius: 18px;"
            "}"
        )

        self._layout = QVBoxLayout(self._frame)
        self._layout.setContentsMargins(16, 14, 16, 12)
        self._layout.setSpacing(12)

        header = QWidget(self._frame)
        header.setObjectName("widgetHeader")
        header.setStyleSheet("QWidget#widgetHeader { background: transparent; }")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        logo_path = config.WIDGET_LOGO_PATH
        self._logo_label = QLabel(header)
        self._logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo_label.setContentsMargins(0, 0, 0, 0)
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                self._logo_label.setPixmap(
                    pixmap.scaledToHeight(26, Qt.TransformationMode.SmoothTransformation)
                )
        self._logo_label.setFixedSize(28, 28)
        header_layout.addWidget(self._logo_label)

        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(0)
        brand_label = QLabel("InsightOS", header)
        self._brand_label = brand_label
        brand_label.setStyleSheet("QLabel { color: #0F172A; font-size: 13px; font-weight: 700; margin: 0px; padding: 0px; }")
        self._subtitle_label = QLabel("Today's activity", header)
        self._subtitle_label.setStyleSheet("QLabel { color: #475569; font-size: 7px; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 700; margin: 0px; padding: 0px; }")
        header_text.addWidget(brand_label)
        header_text.addWidget(self._subtitle_label)
        header_layout.addLayout(header_text)
        header_layout.addStretch(1)

        self._menu_button = QToolButton(header)
        self._menu_button.setText("⋮")
        self._menu_button.setAccessibleName("Widget options")
        self._menu_button.setToolTip("Widget options")
        self._menu_button.setAutoRaise(True)
        self._menu_button.setFixedSize(24, 24)
        self._menu_button.clicked.connect(lambda: self._show_widget_menu())
        self._menu_button.setStyleSheet(
            "QToolButton { color: #475569; background: rgba(15, 23, 42, 0.03); border: 1px solid rgba(148, 163, 184, 0.28); border-radius: 12px; font-size: 14px; font-weight: 700; }"
            "QToolButton:hover { color: #0F172A; border-color: rgba(37, 99, 235, 0.35); background: rgba(37, 99, 235, 0.06); }"
        )
        header_layout.addWidget(self._menu_button)
        self._layout.addWidget(header)

        content = QWidget(self._frame)
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        self._progress_container = QWidget(content)
        self._progress_layout = QVBoxLayout(self._progress_container)
        self._progress_layout.setContentsMargins(0, 0, 0, 0)
        self._progress_layout.setSpacing(0)
        self._progress_widget = CircularProgressWidget(self._progress_container)
        self._progress_widget.setFixedSize(90, 90)
        self._progress_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._progress_layout.addWidget(self._progress_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self._progress_container, stretch=0)

        apps_column = QVBoxLayout()
        apps_column.setContentsMargins(0, 0, 0, 0)
        apps_column.setSpacing(6)
        self._top_apps_title = QLabel("Top applications", content)
        self._top_apps_title.setStyleSheet("QLabel { color: #475569; font-size: 7px; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; margin: 0px; padding: 0px; }")
        apps_column.addWidget(self._top_apps_title)

        self._top_apps_list = QWidget(content)
        self._top_apps_list.setObjectName("topAppsList")
        self._top_apps_list.setStyleSheet("QWidget#topAppsList { background: transparent; }")
        self._top_apps_layout = QVBoxLayout(self._top_apps_list)
        self._top_apps_layout.setContentsMargins(0, 0, 0, 0)
        self._top_apps_layout.setSpacing(6)
        self._top_apps_labels: list[TopAppRow] = []
        for _ in range(3):
            row = TopAppRow(self._top_apps_list)
            row.set_app("No activity yet", "0m")
            self._top_apps_layout.addWidget(row)
            self._top_apps_labels.append(row)
        self._activity_name = QLabel("Idle", self)
        self._activity_name.setVisible(False)
        self._activity_time = QLabel("00:00:00", self)
        self._activity_time.setVisible(False)
        apps_column.addWidget(self._top_apps_list)
        apps_column.addStretch(1)
        content_layout.addLayout(apps_column, stretch=1)
        self._layout.addWidget(content)

        divider = QWidget(self._frame)
        self._divider = divider
        divider.setFixedHeight(1)
        divider.setStyleSheet("QWidget { background: rgba(148, 163, 184, 0.22); }")
        self._layout.addWidget(divider)

        nav = QWidget(self._frame)
        nav.setObjectName("navBar")
        nav.setStyleSheet("QWidget#navBar { background: transparent; }")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        self._nav_buttons = [
            NavigationButton("analytics", nav),
            NavigationButton("add", nav),
            NavigationButton("focus", nav),
        ]
        self._nav_buttons[0].set_active(True)
        self._nav_buttons[2].setCheckable(True)
        self._nav_buttons[2].setChecked(self._compact_mode)
        self._nav_buttons[0].clicked.connect(lambda: self._open_dashboard(0))
        self._nav_buttons[1].clicked.connect(lambda: self._open_settings())
        self._nav_buttons[2].clicked.connect(
            lambda checked: self.set_compact_mode(bool(checked))
        )
        for button in self._nav_buttons:
            nav_layout.addWidget(button, stretch=1)
        self._layout.addWidget(nav)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._frame)

        from PySide6.QtWidgets import QGraphicsDropShadowEffect

        effect = QGraphicsDropShadowEffect(self)
        effect.setBlurRadius(18)
        effect.setOffset(0, 5)
        effect.setColor(QColor(15, 23, 42, 30))
        self._frame.setGraphicsEffect(effect)
        self.apply_theme(self._theme)

    def _apply_layout_mode(self) -> None:
        target_height = config.WIDGET_COMPACT_HEIGHT if self._compact_mode else config.WIDGET_HEIGHT
        self.setFixedHeight(target_height)
        self._top_apps_title.setVisible(not self._compact_mode)
        self._top_apps_list.setVisible(not self._compact_mode)
        if self._compact_mode:
            self._progress_widget.setFixedSize(84, 98)
            self._layout.setSpacing(10)
            self._layout.setContentsMargins(12, 12, 12, 12)
        else:
            self._progress_widget.setFixedSize(96, 110)
            self._layout.setSpacing(12)
            self._layout.setContentsMargins(16, 14, 16, 12)

    def _apply_opacity(self) -> None:
        self.setWindowOpacity(float(settings_store.get_value("widget_opacity")))

    def _on_refresh_tick(self) -> None:
        self._refresh_counter += 1
        self._refresh_live()
        if self._refresh_counter % max(1, config.WIDGET_REFRESH_INTERVAL_SECONDS // config.WIDGET_LIVE_REFRESH_INTERVAL_SECONDS) == 0:
            self._refresh_summary()

    def _refresh_summary(self) -> None:
        if not self.isVisible():
            return
        today = time_utils.today_str()
        if self._tracker is not None:
            today_seconds = int(self._tracker.today_screen_total_snapshot(today))
        else:
            summary = db.get_today_summary(today)
            today_seconds = summary.total_screen_seconds
        top_apps = db.get_top_apps([today], limit=3)
        active = db.get_active_session()
        if active is not None:
            tracked_app, elapsed = self._current_session_snapshot()
            if tracked_app != active.app_name:
                elapsed = 0
            top_apps = self._merge_live_elapsed(top_apps, active.app_name, int(elapsed))
        if today_seconds <= 0:
            history_stats = db.get_history_stats([today])
            live_elapsed = int(elapsed) if active is not None and tracked_app == active.app_name else 0
            today_seconds = history_stats.get("total_seconds", 0) + live_elapsed

        signature = (
            today_seconds,
            tuple((name, seconds) for name, seconds in top_apps),
            active.app_name if active else "Idle",
        )
        if self._last_summary_signature == signature:
            return
        self._last_summary_signature = signature

        self._progress_widget.set_value(today_seconds, config.WIDGET_DAILY_TARGET_SECONDS)
        self._set_today_text(_format_widget_duration(today_seconds))

        for row, item in zip(self._top_apps_labels, top_apps, strict=False):
            row.set_app(friendly_app_name(item[0]), _format_widget_duration(item[1]))
        for row in self._top_apps_labels[len(top_apps):]:
            row.set_app("No activity yet", "0m")

    def _refresh_live(self) -> None:
        if not self.isVisible():
            return
        active = db.get_active_session()
        signature = (active.app_name if active else "Idle", time_utils.utc_now_iso()[:19])
        if self._last_live_signature == signature:
            return
        self._last_live_signature = signature
        if active is not None:
            tracked_app, elapsed = self._current_session_snapshot()
            app_name = tracked_app or active.app_name
            self._activity_name.setText(friendly_app_name(app_name))
            self._activity_time.setText(time_utils.format_duration_hms(int(elapsed)))
        else:
            self._activity_name.setText("Idle")
            self._activity_time.setText("00:00:00")

    def _current_session_snapshot(self) -> tuple[str | None, float]:
        if self._tracker is not None:
            return self._tracker.current_session_snapshot()
        active = db.get_active_session()
        if active is None:
            return None, 0.0
        return active.app_name, float(time_utils.seconds_between(active.start_time, time_utils.utc_now_iso()))

    def _set_today_text(self, text: str) -> None:
        self._progress_widget._value_label.setText(text)

    @staticmethod
    def _merge_live_elapsed(top_apps: list[tuple[str, int]], app_name: str, elapsed: int) -> list[tuple[str, int]]:
        merged = {name: seconds for name, seconds in top_apps}
        merged[app_name] = merged.get(app_name, 0) + elapsed
        combined = [(name, seconds) for name, seconds in merged.items()]
        combined.sort(key=lambda item: item[1], reverse=True)
        return combined[:3]

    def _restore_position(self) -> None:
        x = int(settings_store.get_value("widget_x"))
        y = int(settings_store.get_value("widget_y"))
        x, y = self._clamp_position_to_screen(x, y)
        self.move(x, y)

    def _restore_persisted_state(self) -> None:
        state = StartupStateStore().restore_widget()
        geometry = state["geometry"]
        self.setGeometry(*geometry)
        self.set_opacity(float(state.get("opacity", settings_store.get_value("widget_opacity"))))
        self.set_compact_mode(bool(state.get("compact", bool(settings_store.get_value("widget_compact_mode")))))
        if not state.get("visible", True):
            self.hide()
            settings_store.set_value("widget_visible", False)
        else:
            self.show()
            settings_store.set_value("widget_visible", True)

    def _persist_state(self) -> None:
        state_store = StartupStateStore()
        state_store.remember_widget((self.x(), self.y(), self.width(), self.height()), self.isVisible(), self._compact_mode, self.windowOpacity())

    def _clamp_position_to_screen(self, x: int, y: int) -> tuple[int, int]:
        screen = QGuiApplication.screenAt(QPoint(x, y))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return x, y
        geometry = screen.availableGeometry()
        max_x = max(geometry.left(), geometry.right() - self.width())
        max_y = max(geometry.top(), geometry.bottom() - self.height())
        return max(geometry.left(), min(x, max_x)), max(geometry.top(), min(y, max_y))

    def _show_top_level_window(self) -> None:
        """Show the existing top-level widget without recreating or activating its native window."""
        x = int(settings_store.get_value("widget_x")) if settings_store.get_value("widget_x") else config.WIDGET_DEFAULT_X
        y = int(settings_store.get_value("widget_y")) if settings_store.get_value("widget_y") else config.WIDGET_DEFAULT_Y
        clamped_x, clamped_y = self._clamp_position_to_screen(x, y)
        self.move(clamped_x, clamped_y)
        QWidget.show(self)
        logger.debug("DesktopWidget: normal top-level window shown at %s,%s", clamped_x, clamped_y)

    def _sync_visibility(self) -> None:
        if not self._enabled:
            self._set_desktop_topmost(False)
            if self.isVisible():
                self.hide()
            return
        should_show = self._should_show_on_desktop()
        if should_show and not self.isVisible():
            self._fade_in()
        elif not should_show and self.isVisible():
            self._set_desktop_topmost(False)
            self._fade_out()
        elif should_show:
            self._set_desktop_topmost(
                platform_win.is_desktop_or_owned_widget_foreground(int(self.winId()))
            )
        if should_show and not self._refresh_timer.isActive():
            self._refresh_timer.start()
        elif not should_show and self._refresh_timer.isActive():
            self._refresh_timer.stop()

    def _set_desktop_topmost(self, topmost: bool) -> None:
        if self._desktop_topmost is topmost:
            return
        if platform_win.set_window_topmost(int(self.winId()), topmost):
            self._desktop_topmost = topmost
        else:
            logger.warning("Could not update desktop widget z-order (topmost=%s)", topmost)

    def _should_show_on_desktop(self) -> bool:
        return bool(settings_store.get_value("widget_visible"))

    def _fade_in(self) -> None:
        self.show()
        self.setWindowOpacity(0.0)
        animation = QPropertyAnimation(self, b"windowOpacity")
        animation.setDuration(180)
        animation.setStartValue(0.0)
        animation.setEndValue(float(settings_store.get_value("widget_opacity")))
        animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        animation.start()

    def _fade_out(self) -> None:
        animation = QPropertyAnimation(self, b"windowOpacity")
        animation.setDuration(160)
        animation.setStartValue(float(settings_store.get_value("widget_opacity")))
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        animation.finished.connect(self._on_fade_out_finished, Qt.ConnectionType.UniqueConnection)
        animation.start()

    def _on_fade_out_finished(self) -> None:
        self.hide()

    def show(self) -> None:  # noqa: PLR0911
        if not self._enabled:
            return
        settings_store.set_value("widget_visible", True)
        self._show_top_level_window()
        if hasattr(self, "_visibility_timer") and not self._visibility_timer.isActive():
            self._visibility_timer.start()
        if hasattr(self, "_refresh_timer") and not self._refresh_timer.isActive():
            self._refresh_timer.start()
        if hasattr(self, "_visibility_timer") and self._foreground_hook is None:
            self._foreground_hook = platform_win.watch_foreground_changes(self._sync_visibility)
        logger.debug("DesktopWidget.show(): visible=%s, geometry=%s", self.isVisible(), self.geometry())

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        self.apply_theme(self._theme)

    def hide(self) -> None:  # noqa: PLR0911
        if hasattr(self, "_desktop_topmost"):
            self._set_desktop_topmost(False)
        if hasattr(self, "_refresh_timer"):
            self._refresh_timer.stop()
        super().hide()
        logger.debug("DesktopWidget.hide(): visible=%s", self.isVisible())

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._refresh_timer.stop()
        self._visibility_timer.stop()
        if self._foreground_hook is not None:
            platform_win.unwatch_foreground_changes(self._foreground_hook[0])
            self._foreground_hook = None
        self._persist_state()
        super().closeEvent(event)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        settings_store.set_value("widget_enabled", enabled)
        if enabled:
            settings_store.set_value("widget_visible", True)
            self._sync_visibility()
        else:
            self.hide()

    def set_compact_mode(self, compact: bool) -> None:
        self._compact_mode = compact
        settings_store.set_value("widget_compact_mode", compact)
        self._apply_layout_mode()
        if hasattr(self, "_nav_buttons"):
            self._nav_buttons[2].setChecked(compact)

    def set_opacity(self, opacity: float) -> None:
        self._opacity = opacity
        settings_store.set_value("widget_opacity", opacity)
        self._apply_opacity()

    def set_theme(self, theme: str) -> None:
        if theme not in ("light", "dark"):
            raise ValueError(f"Unsupported widget theme: {theme}")
        settings_store.set_value("theme", theme)
        app = QApplication.instance()
        if app is not None:
            for window in app.topLevelWidgets():
                apply_theme = getattr(window, "apply_theme", None)
                if callable(apply_theme):
                    apply_theme(theme)
        else:
            self.apply_theme(theme)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme if theme in ("light", "dark") else "light"
        colors = colors_for(self._theme)
        self._frame.setStyleSheet(
            "QWidget#widgetFrame {"
            f"background-color: {colors['surface']};"
            f"border: 1px solid {colors['border']};"
            "border-radius: 18px;"
            "}"
        )
        self._brand_label.setStyleSheet(
            f"QLabel {{ color: {colors['text']}; font-size: 13px; font-weight: 700; margin: 0px; padding: 0px; }}"
        )
        self._subtitle_label.setStyleSheet(
            f"QLabel {{ color: {colors['muted_text']}; font-size: 7px; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 700; margin: 0px; padding: 0px; }}"
        )
        self._menu_button.setStyleSheet(
            f"QToolButton {{ color: {colors['muted_text']}; background: {colors['raised_surface']}; border: 1px solid {colors['border']}; border-radius: 12px; font-size: 14px; font-weight: 700; }}"
            "QToolButton:hover { color: #2563EB; border-color: rgba(37, 99, 235, 0.45); background: rgba(37, 99, 235, 0.10); }"
        )
        self._top_apps_title.setStyleSheet(
            f"QLabel {{ color: {colors['muted_text']}; font-size: 7px; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; margin: 0px; padding: 0px; }}"
        )
        self._divider.setStyleSheet(
            f"QWidget {{ background: {colors['divider']}; }}"
        )
        self._progress_widget.apply_theme(self._theme)
        for row in self._top_apps_labels:
            row.apply_theme(self._theme)
        for button in self._nav_buttons:
            button.apply_theme(self._theme)
        frame_style = self._frame.style()
        frame_style.unpolish(self._frame)
        frame_style.polish(self._frame)
        self._frame.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            target = event.globalPosition().toPoint() - self._drag_offset
            x, y = self._clamp_position_to_screen(target.x(), target.y())
            self.move(x, y)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            x, y = self._clamp_position_to_screen(self.pos().x(), self.pos().y())
            self.move(x, y)
            settings_store.set_value("widget_x", x)
            settings_store.set_value("widget_y", y)
            self._persist_state()

    def contextMenuEvent(self, event) -> None:
        self._show_widget_menu(event.globalPos())

    def _show_widget_menu(self, position=None) -> None:
        menu = QMenu(self)
        colors = colors_for(self._theme)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {colors['raised_surface']}; color: {colors['text']}; border: 1px solid {colors['border']}; border-radius: 10px; padding: 6px; }}"
            "QMenu::item { padding: 7px 12px; border-radius: 6px; }"
            "QMenu::item:selected { background-color: rgba(37, 99, 235, 0.16); color: #2563EB; }"
        )
        open_action = menu.addAction("Open Dashboard")
        open_action.triggered.connect(lambda _checked=False: self._open_dashboard())
        settings_action = menu.addAction("Settings")
        settings_action.triggered.connect(lambda _checked=False: self._open_settings())
        theme_action = menu.addAction("Dark appearance")
        theme_action.setCheckable(True)
        theme_action.setChecked(self._theme == "dark")
        theme_action.setToolTip("Use the dark widget appearance")
        theme_action.toggled.connect(lambda checked: self.set_theme("dark" if checked else "light"))
        enabled_action = menu.addAction("Enable Widget")
        enabled_action.setCheckable(True)
        enabled_action.setChecked(self._enabled)
        enabled_action.toggled.connect(self.set_enabled)
        compact_action = menu.addAction("Compact Mode")
        compact_action.setCheckable(True)
        compact_action.setChecked(self._compact_mode)
        compact_action.toggled.connect(self.set_compact_mode)
        auto_start_action = menu.addAction("Auto-start with Windows")
        auto_start_action.setCheckable(True)
        auto_start_action.setChecked(bool(settings_store.get_value("widget_auto_start")))
        auto_start_action.toggled.connect(self._set_auto_start)
        opacity_menu = menu.addMenu("Opacity")
        for value in (0.80, 0.90, 0.96, 1.00):
            action = opacity_menu.addAction(f"{int(value * 100)}%")
            action.setCheckable(True)
            action.setChecked(abs(float(settings_store.get_value("widget_opacity")) - value) < 1e-6)
            action.triggered.connect(
                lambda _checked=False, opacity=value: self.set_opacity(opacity)
            )
        menu.addSeparator()
        hide_action = menu.addAction("Hide Widget")
        hide_action.triggered.connect(lambda _checked=False: self._hide_widget_from_menu())

        menu.addSeparator()
        quit_action = menu.addAction("Quit InsightOS")
        quit_action.triggered.connect(lambda _checked=False: self._request_quit())

        if position is None:
            position = self._menu_button.mapToGlobal(self._menu_button.rect().bottomLeft())
        self._exec_widget_menu(menu, position)

    def _set_auto_start(self, enabled: bool) -> None:
        settings_store.set_value("widget_auto_start", enabled)
        platform_win.set_startup_entry(enabled)

    def _exec_widget_menu(self, menu: QMenu, position: QPoint) -> QAction | None:
        return menu.exec(position)

    def _hide_widget_from_menu(self) -> None:
        self.hide()
        settings_store.set_value("widget_visible", False)

    def _request_quit(self) -> None:
        app = QApplication.instance()
        tray = getattr(app, "tray", None) if app is not None else None
        confirm_exit = getattr(tray, "_confirm_exit", None)
        if callable(confirm_exit):
            confirm_exit()
        else:
            logger.warning("Quit requested from widget menu, but no confirmation handler is available")

    def _open_dashboard(self, tab_index: int = 0) -> None:
        from src.ui.dashboard.dashboard_window import DashboardWindow

        app = QApplication.instance()
        window = getattr(app, "dashboard_window", None) if app is not None else None
        if window is None:
            window = DashboardWindow(tracker=self._tracker)
            if app is not None:
                app.dashboard_window = window
        if app is not None and not getattr(window, "_insightos_destroyed_hook", False):
            window.destroyed.connect(lambda _obj=None: setattr(app, "dashboard_window", None))
            window._insightos_destroyed_hook = True
        if 0 <= tab_index < window.count():
            window.setCurrentIndex(tab_index)
        window.show()
        window.raise_()
        window.activateWindow()

    def _open_settings(self) -> None:
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()


def friendly_app_name(app_name: str) -> str:
    """Return a human-friendly app label without leaking executable names."""
    cleaned = app_name.strip()
    if not cleaned:
        return "Unknown"
    cleaned = cleaned.rsplit("\\", 1)[-1]
    cleaned = cleaned.rsplit("/", 1)[-1]
    cleaned = cleaned.lower().removesuffix(".exe")
    cleaned = cleaned.replace("_", " ")
    cleaned = cleaned.replace("-", " ")
    mapping = {
        "msedge": "Microsoft Edge",
        "code": "Visual Studio Code",
        "spotify": "Spotify",
        "chrome": "Google Chrome",
        "firefox": "Mozilla Firefox",
        "explorer": "File Explorer",
        "notepadplusplus": "Notepad++",
        "winword": "Microsoft Word",
        "excel": "Microsoft Excel",
        "powerpnt": "Microsoft PowerPoint",
    }
    if cleaned in mapping:
        return mapping[cleaned]
    return " ".join(part.capitalize() for part in cleaned.split()) or cleaned.title()


def _format_widget_duration(seconds: int) -> str:
    if 0 < seconds < 60:
        return "<1m"
    return time_utils.format_duration(seconds)
