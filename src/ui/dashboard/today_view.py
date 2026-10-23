"""The Today tab: total screen time, current app, top apps, daily timeline (§12).

Rendering only — every value is read via core/database.py. The refresh
timer runs only while this widget is visible, per §12's CPU-budget rule
("The refresh timer pauses when the window is minimized or not visible").
"""

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src import config
from src.core import database as db
from src.core.models import AppUsage
from src.ui.dashboard.widgets_common import StatCard, TopAppsList
from src.ui.theme import colors_for, current_theme
from src.utils import time_utils

if TYPE_CHECKING:
    from src.core.tracker import Tracker

_SEGMENT_COLORS = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B2",
    "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD",
]


class DailyTimeline(QWidget):
    """A horizontal strip of colored segments, one per app session (§12)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self.setFixedHeight(32)
        self._app_colors: dict[str, str] = {}

    def apply_theme(self, theme: str) -> None:
        colors = colors_for(theme)
        for label in self.findChildren(QLabel):
            label.setStyleSheet(
                f"QLabel {{ color: {colors['muted_text']}; font-size: 11px; font-style: italic; }}"
            )

    def set_sessions(self, sessions: list) -> None:
        normalized = tuple((s.app_name, s.duration_seconds or 0, s.start_time) for s in sessions)
        if getattr(self, "_last_sessions_key", None) == normalized:
            return
        self._last_sessions_key = normalized

        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        closed = [s for s in sessions if s.duration_seconds is not None and s.duration_seconds > 0]
        if not closed:
            placeholder = QLabel("No activity yet today.")
            colors = colors_for(current_theme())
            placeholder.setStyleSheet(
                f"QLabel {{ color: {colors['muted_text']}; font-size: 11px; font-style: italic; }}"
            )
            self._layout.addWidget(placeholder, alignment=Qt.AlignmentFlag.AlignLeft)
            return

        for session in closed:
            color = self._color_for(session.app_name)
            segment = QFrame()
            segment.setFrameShape(QFrame.Shape.NoFrame)
            segment.setFixedHeight(10)
            segment.setStyleSheet(f"QFrame {{ background-color: {color}; border-radius: 999px; }}")
            segment.setToolTip(f"{session.app_name} — {time_utils.format_duration(session.duration_seconds)}")
            self._layout.addWidget(segment, stretch=max(session.duration_seconds, 1))

    def _color_for(self, app_name: str) -> str:
        if app_name not in self._app_colors:
            index = len(self._app_colors) % len(_SEGMENT_COLORS)
            self._app_colors[app_name] = _SEGMENT_COLORS[index]
        return self._app_colors[app_name]


class TodayView(QWidget):
    """The Dashboard's Today tab: stats, top apps, and the daily timeline."""

    def __init__(self, parent: QWidget | None = None, tracker: "Tracker | None" = None) -> None:
        super().__init__(parent)
        self._tracker = tracker
        self.setObjectName("todayView")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        hero_card = QWidget(self)
        self._hero_card = hero_card
        hero_card.setObjectName("heroCard")
        hero_layout = QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(4)

        title_label = QLabel("Today at a glance")
        self._title_label = title_label
        subtitle_label = QLabel("A calm snapshot of active time, current activity, and top apps.")
        self._subtitle_label = subtitle_label
        hero_layout.addWidget(title_label)
        hero_layout.addWidget(subtitle_label)
        layout.addWidget(hero_card)

        primary_stats_row = QHBoxLayout()
        primary_stats_row.setSpacing(10)
        self._total_card = StatCard("Active time", "0m")
        self._idle_card = StatCard("Idle time", "0m")
        self._session_count_card = StatCard("Sessions", "0")
        self._longest_session_card = StatCard("Longest session", "0m")
        self._current_app_card = StatCard("Current application", "Idle")
        primary_stats_row.addWidget(self._total_card)
        primary_stats_row.addWidget(self._idle_card)
        layout.addLayout(primary_stats_row)

        secondary_stats_row = QHBoxLayout()
        secondary_stats_row.setSpacing(10)
        secondary_stats_row.addWidget(self._session_count_card)
        secondary_stats_row.addWidget(self._longest_session_card)
        secondary_stats_row.addWidget(self._current_app_card)
        layout.addLayout(secondary_stats_row)

        section_title = QLabel("Top applications")
        layout.addWidget(section_title)
        self._top_apps_container = QVBoxLayout()
        self._top_apps_container.setSpacing(8)
        layout.addLayout(self._top_apps_container)

        timeline_title = QLabel("Daily timeline")
        layout.addWidget(timeline_title)
        self._section_labels = (section_title, timeline_title)
        self._timeline = DailyTimeline()
        layout.addWidget(self._timeline)

        layout.addStretch(1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(max(10, config.DASHBOARD_REFRESH_INTERVAL_SECONDS) * 1000)
        self._refresh_timer.timeout.connect(self.refresh)
        self._last_refresh_signature: tuple[int, tuple[tuple[str, int], ...], str] | None = None
        self.apply_theme(current_theme())

    def apply_theme(self, theme: str) -> None:
        colors = colors_for(theme)
        self.setStyleSheet(
            f"QWidget#todayView {{ background-color: {colors['surface']}; }}"
        )
        self._hero_card.setStyleSheet(
            f"QWidget#heroCard {{ background-color: {colors['raised_surface']}; border: 1px solid {colors['border']}; border-radius: 18px; }}"
        )
        self._title_label.setStyleSheet(
            f"QLabel {{ color: {colors['text']}; font-size: 16px; font-weight: 700; }}"
        )
        self._subtitle_label.setStyleSheet(
            f"QLabel {{ color: {colors['muted_text']}; font-size: 11px; }}"
        )
        for label in self._section_labels:
            label.setStyleSheet(
                f"QLabel {{ color: {colors['muted_text']}; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.1px; }}"
            )
        for card in (
            self._total_card,
            self._idle_card,
            self._session_count_card,
            self._longest_session_card,
            self._current_app_card,
        ):
            card.apply_theme(theme)
        for apps_list in self.findChildren(TopAppsList):
            apps_list.apply_theme(theme)
        self._timeline.apply_theme(theme)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
        self._refresh_timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._refresh_timer.stop()

    def refresh(self) -> None:
        today = time_utils.today_str()
        summary = db.get_today_summary(today)
        active = db.get_active_session()
        sessions = db.get_sessions_for_dates([today])
        top_apps = self._collect_top_apps(today, active)
        stats = db.get_history_stats([today])
        current_app, current_elapsed = self._current_session_snapshot(active)
        longest_seconds = max(stats.get("longest_session_seconds", 0), current_elapsed)

        signature = (
            summary.total_screen_seconds,
            summary.total_idle_seconds,
            stats.get("total_sessions", 0),
            longest_seconds,
            tuple((usage.app_name, usage.total_seconds) for usage in top_apps),
            current_app or "Idle",
        )
        if self._last_refresh_signature == signature:
            return
        self._last_refresh_signature = signature

        self._total_card.set_value(time_utils.format_duration(summary.total_screen_seconds))
        self._idle_card.set_value(time_utils.format_duration(summary.total_idle_seconds))
        self._session_count_card.set_value(str(stats.get("total_sessions", 0)))
        self._longest_session_card.set_value(time_utils.format_duration(longest_seconds))
        self._current_app_card.set_value(current_app or "Idle")

        self._refresh_top_apps(top_apps)
        self._timeline.set_sessions(sessions)

    def _collect_top_apps(self, today: str, active) -> list[AppUsage]:
        top_apps = [AppUsage(app_name=name, total_seconds=seconds) for name, seconds in db.get_top_apps([today], limit=config.TOP_APPS_LIMIT)]
        if active is not None:
            _, elapsed = self._current_session_snapshot(active)
            top_apps = self._merge_live_elapsed(top_apps, active.app_name, elapsed)
        return top_apps

    def _current_session_snapshot(self, active) -> tuple[str | None, int]:
        if self._tracker is not None:
            app_name, elapsed = self._tracker.current_session_snapshot()
            return app_name, int(elapsed)
        if active is None:
            return None, 0
        return active.app_name, time_utils.seconds_between(active.start_time, time_utils.utc_now_iso())

    def _refresh_top_apps(self, top_apps: list[AppUsage]) -> None:
        while self._top_apps_container.count():
            item = self._top_apps_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._top_apps_container.addWidget(TopAppsList(top_apps))

    @staticmethod
    def _merge_live_elapsed(top_apps: list[AppUsage], app_name: str, elapsed: int) -> list[AppUsage]:
        merged = {usage.app_name: usage.total_seconds for usage in top_apps}
        merged[app_name] = merged.get(app_name, 0) + elapsed
        combined = [AppUsage(app_name=name, total_seconds=seconds) for name, seconds in merged.items()]
        combined.sort(key=lambda usage: usage.total_seconds, reverse=True)
        return combined[: config.TOP_APPS_LIMIT]
