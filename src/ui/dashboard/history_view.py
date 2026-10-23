"""History dashboard view with browsing, search, filtering, and export support."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src import config
from src.core import database as db
from src.core.models import AppSession
from src.ui.theme import colors_for, current_theme
from src.utils import time_utils


class HistoryView(QWidget):
    """Read-only history explorer surface for InsightOS."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("historyView")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        header_card = QWidget(self)
        self._header_card = header_card
        header_card.setObjectName("headerCard")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setSpacing(8)

        title = QLabel("History explorer")
        self._title_label = title
        subtitle = QLabel("Browse activity by day, search sessions, and inspect the raw facts recorded by InsightOS.")
        self._subtitle_label = subtitle
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header_card)

        controls = QWidget(self)
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)

        self._range_combo = QComboBox()
        self._range_combo.addItems(["Today", "Yesterday", "Last 7 Days", "Last 30 Days"])
        self._range_combo.currentIndexChanged.connect(self._refresh)
        controls_layout.addWidget(self._range_combo)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search sessions")
        self._search_box.textChanged.connect(self._refresh)
        controls_layout.addWidget(self._search_box, stretch=1)

        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["Newest", "Alphabetical", "Longest", "Shortest"])
        self._sort_combo.currentIndexChanged.connect(self._refresh)
        controls_layout.addWidget(self._sort_combo)
        layout.addWidget(controls)

        self._stats_label = QLabel("")
        layout.addWidget(self._stats_label)

        self._scroll = QScrollArea(self)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._content = QWidget(self._scroll)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(8)
        self._scroll.setWidget(self._content)
        layout.addWidget(self._scroll, stretch=1)

        self._refresh()
        self.apply_theme(current_theme())

    def apply_theme(self, theme: str) -> None:
        colors = colors_for(theme)
        self.setStyleSheet(
            f"QWidget#historyView {{ background-color: {colors['surface']}; }}"
            f"QComboBox, QLineEdit {{ color: {colors['text']}; background-color: {colors['field']}; border: 1px solid {colors['border']}; border-radius: 8px; padding: 6px 8px; }}"
            f"QScrollArea {{ background-color: {colors['surface']}; }}"
        )
        self._header_card.setStyleSheet(
            f"QWidget#headerCard {{ background-color: {colors['raised_surface']}; border: 1px solid {colors['border']}; border-radius: 16px; }}"
        )
        self._title_label.setStyleSheet(
            f"QLabel {{ color: {colors['text']}; font-size: 16px; font-weight: 700; }}"
        )
        self._subtitle_label.setStyleSheet(
            f"QLabel {{ color: {colors['muted_text']}; font-size: 11px; }}"
        )
        self._stats_label.setStyleSheet(
            f"QLabel {{ color: {colors['muted_text']}; font-size: 11px; font-weight: 600; }}"
        )
        for label in self.findChildren(QLabel):
            if label.objectName() == "sessionTitle":
                label.setStyleSheet(
                    f"QLabel {{ color: {colors['text']}; font-size: 12px; font-weight: 600; }}"
                )
            elif label.objectName() == "sessionDetail" or label.objectName() == "historyPlaceholder":
                label.setStyleSheet(
                    f"QLabel {{ color: {colors['muted_text']}; font-size: 11px; }}"
                )
        for row in self.findChildren(QWidget, "sessionRow"):
            row.setStyleSheet(
                f"QWidget#sessionRow {{ background-color: {colors['raised_surface']}; border: 1px solid {colors['border']}; border-radius: 12px; }}"
            )

    def selected_range(self) -> str:
        return self._range_combo.currentText()

    def current_query(self) -> str:
        return self._search_box.text()

    def current_sort(self) -> str:
        return self._sort_combo.currentText()

    def set_range(self, value: str) -> None:
        index = self._range_combo.findText(value)
        if index >= 0:
            self._range_combo.setCurrentIndex(index)

    def set_query(self, value: str) -> None:
        self._search_box.setText(value)

    def set_sort(self, value: str) -> None:
        index = self._sort_combo.findText(value)
        if index >= 0:
            self._sort_combo.setCurrentIndex(index)

    def _refresh(self) -> None:
        dates = self._selected_dates()
        sessions = db.search_sessions(self._search_box.text(), dates)
        sessions = self._filter_sessions(sessions, self._search_box.text(), self._sort_combo.currentText())
        self._render_sessions(sessions, dates)

    def _selected_dates(self) -> list[str]:
        selection = self._range_combo.currentText()
        today = time_utils.today_str()
        if selection == "Today":
            return [today]
        if selection == "Yesterday":
            return [time_utils.previous_day_str(today, 1)]
        if selection == "Last 7 Days":
            return [time_utils.previous_day_str(today, offset) for offset in range(6, -1, -1)]
        if selection == "Last 30 Days":
            return [time_utils.previous_day_str(today, offset) for offset in range(29, -1, -1)]
        return [today]

    def _filter_sessions(self, sessions: list[AppSession], query: str, sort_order: str) -> list[AppSession]:
        search_text = (query or "").strip().lower()
        filtered = list(sessions)
        if search_text:
            filtered = [session for session in filtered if search_text in session.app_name.lower() or (session.window_title or "").lower().find(search_text) >= 0]
        if sort_order == "Alphabetical":
            filtered.sort(key=lambda item: item.app_name.lower())
        elif sort_order == "Longest":
            filtered.sort(key=lambda item: (item.duration_seconds or 0), reverse=True)
        elif sort_order == "Shortest":
            filtered.sort(key=lambda item: (item.duration_seconds or 0))
        else:
            filtered.sort(key=lambda item: item.start_time, reverse=True)
        return filtered

    def _render_sessions(self, sessions: list[AppSession], dates: list[str]) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        stats = db.get_history_stats(dates)
        self._stats_label.setText(
            f"{stats.get('total_sessions', 0)} sessions • {time_utils.format_duration(stats.get('total_seconds', 0))} tracked • {stats.get('unique_apps', 0)} apps"
        )

        if not sessions:
            empty = QLabel("No sessions matched the current filters.")
            empty.setObjectName("historyPlaceholder")
            colors = colors_for(current_theme())
            empty.setStyleSheet(
                f"QLabel {{ color: {colors['muted_text']}; font-size: 11px; font-style: italic; }}"
            )
            self._content_layout.addWidget(empty)
            return

        colors = colors_for(current_theme())
        for session in sessions:
            row = QWidget(self._content)
            row.setObjectName("sessionRow")
            row.setStyleSheet(
                f"QWidget#sessionRow {{ background-color: {colors['raised_surface']}; border: 1px solid {colors['border']}; border-radius: 12px; }}"
            )
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(4)

            title = QLabel(f"{time_utils.format_iso_time(session.start_time)} • {session.app_name}")
            title.setObjectName("sessionTitle")
            title.setStyleSheet(
                f"QLabel {{ color: {colors['text']}; font-size: 12px; font-weight: 600; }}"
            )
            detail = QLabel(f"{time_utils.format_duration(session.duration_seconds or 0)} • {session.window_title or 'No title recorded'}")
            detail.setObjectName("sessionDetail")
            detail.setStyleSheet(
                f"QLabel {{ color: {colors['muted_text']}; font-size: 11px; }}"
            )
            detail.setWordWrap(True)
            row_layout.addWidget(title)
            row_layout.addWidget(detail)
            self._content_layout.addWidget(row)
