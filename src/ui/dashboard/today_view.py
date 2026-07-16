"""The Today tab: total screen time, current app, top apps, daily timeline (§12).

Rendering only — every value is read via core/database.py. The refresh
timer runs only while this widget is visible, per §12's CPU-budget rule
("The refresh timer pauses when the window is minimized or not visible").
"""

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import config
from core import database as db
from core.models import AppUsage
from ui.dashboard.widgets_common import StatCard, TopAppsList
from utils import time_utils

# A small fixed palette so the same app always gets the same timeline color
# within a single render pass (purely cosmetic, no persistence needed).
_SEGMENT_COLORS = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B2",
    "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD",
]


class DailyTimeline(QWidget):
    """A horizontal strip of colored segments, one per app session (§12)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create an empty timeline; call set_sessions() to populate it."""
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(1)
        self.setFixedHeight(28)
        self._app_colors: dict[str, str] = {}

    def set_sessions(self, sessions: list) -> None:
        """Rebuild the strip from a list of closed AppSession rows.

        Args:
            sessions: AppSession rows for the day, chronological. Sessions
                with no duration yet (the live active one) are skipped —
                the caller may render it separately if desired.

        Returns:
            None.
        """
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        closed = [s for s in sessions if s.duration_seconds is not None and s.duration_seconds > 0]
        if not closed:
            placeholder = QLabel("No activity yet today.")
            self._layout.addWidget(placeholder)
            return

        for session in closed:
            color = self._color_for(session.app_name)
            segment = QFrame()
            segment.setFrameShape(QFrame.Shape.NoFrame)
            segment.setToolTip(f"{session.app_name} — {time_utils.format_duration(session.duration_seconds)}")
            palette = segment.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor(color))
            segment.setAutoFillBackground(True)
            segment.setPalette(palette)
            self._layout.addWidget(segment, stretch=max(session.duration_seconds, 1))

    def _color_for(self, app_name: str) -> str:
        """Return a stable color for an app name, assigning a new one if needed."""
        if app_name not in self._app_colors:
            index = len(self._app_colors) % len(_SEGMENT_COLORS)
            self._app_colors[app_name] = _SEGMENT_COLORS[index]
        return self._app_colors[app_name]


class TodayView(QWidget):
    """The Dashboard's Today tab: stats, top apps, and the daily timeline."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the tab layout and prepare (but do not start) the refresh timer."""
        super().__init__(parent)
        layout = QVBoxLayout(self)

        stats_row = QHBoxLayout()
        self._total_card = StatCard("Total Screen Time", "0m")
        self._current_app_card = StatCard("Current App", "Idle")
        stats_row.addWidget(self._total_card)
        stats_row.addWidget(self._current_app_card)
        layout.addLayout(stats_row)

        layout.addWidget(QLabel("Top Apps Today"))
        self._top_apps_container = QVBoxLayout()
        layout.addLayout(self._top_apps_container)

        layout.addWidget(QLabel("Daily Timeline"))
        self._timeline = DailyTimeline()
        layout.addWidget(self._timeline)

        layout.addStretch(1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(config.DASHBOARD_REFRESH_INTERVAL_SECONDS * 1000)
        self._refresh_timer.timeout.connect(self.refresh)

    def showEvent(self, event) -> None:
        """Start refreshing and refresh immediately when the tab becomes visible."""
        super().showEvent(event)
        self.refresh()
        self._refresh_timer.start()

    def hideEvent(self, event) -> None:
        """Stop refreshing while the tab is hidden, per the §12 CPU budget."""
        super().hideEvent(event)
        self._refresh_timer.stop()

    def refresh(self) -> None:
        """Re-read today's data from the database and update every section.

        Returns:
            None.
        """
        today = time_utils.today_str()
        summary = db.get_today_summary(today)
        active = db.get_active_session()

        self._total_card.set_value(time_utils.format_duration(summary.total_screen_seconds))
        self._current_app_card.set_value(active.app_name if active else "Idle")

        self._refresh_top_apps(today, active)

        sessions = db.get_sessions_for_date(today)
        self._timeline.set_sessions(sessions)

    def _refresh_top_apps(self, today: str, active) -> None:
        """Rebuild the Top Apps list, adding the active session's live elapsed time.

        database.get_top_apps() only counts closed sessions; the currently
        active session (if any) is topped up here with its live elapsed
        time so "today" figures don't lag behind by a full session.
        """
        top_apps = db.get_top_apps([today], limit=config.TOP_APPS_COUNT)

        if active is not None:
            elapsed = time_utils.seconds_between(active.start_time, time_utils.utc_now_iso())
            top_apps = self._merge_live_elapsed(top_apps, active.app_name, elapsed)

        while self._top_apps_container.count():
            item = self._top_apps_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._top_apps_container.addWidget(TopAppsList(top_apps))

    @staticmethod
    def _merge_live_elapsed(top_apps: list[AppUsage], app_name: str, elapsed: int) -> list[AppUsage]:
        """Add live elapsed seconds to an app's entry (or insert one), re-sorted."""
        merged = {usage.app_name: usage.total_seconds for usage in top_apps}
        merged[app_name] = merged.get(app_name, 0) + elapsed
        combined = [AppUsage(app_name=name, total_seconds=seconds) for name, seconds in merged.items()]
        combined.sort(key=lambda usage: usage.total_seconds, reverse=True)
        return combined[: config.TOP_APPS_COUNT]
