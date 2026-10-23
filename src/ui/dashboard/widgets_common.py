"""Shared small UI components used across Dashboard tabs/views (§6).

Purely presentational — rendering only, no DB writes, no business logic.
Kept here so today_view.py and history_view.py don't duplicate layout code
(§22 rule 9: no duplicated logic).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from src.ui.theme import colors_for, current_theme
from src.utils import time_utils


class DurationBarRow(QWidget):
    """A single "app name — duration bar — duration text" row."""

    def __init__(self, app_name: str, seconds: int, max_seconds: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("durationRow")
        self.setStyleSheet("QWidget#durationRow { background: transparent; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(10)

        name_label = QLabel(app_name)
        name_label.setMinimumWidth(140)
        self._name_label = name_label

        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setMaximum(max(max_seconds, 1))
        bar.setValue(min(seconds, max_seconds))
        bar.setFixedHeight(8)
        self._bar = bar

        duration_label = QLabel(time_utils.format_duration(seconds))
        duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        duration_label.setMinimumWidth(72)
        self._duration_label = duration_label

        layout.addWidget(name_label)
        layout.addWidget(bar, stretch=1)
        layout.addWidget(duration_label)
        self.apply_theme(current_theme())

    def apply_theme(self, theme: str) -> None:
        colors = colors_for(theme)
        self._name_label.setStyleSheet(
            f"QLabel {{ color: {colors['text']}; font-size: 12px; font-weight: 500; }}"
        )
        self._duration_label.setStyleSheet(
            f"QLabel {{ color: {colors['muted_text']}; font-size: 11px; }}"
        )
        self._bar.setStyleSheet(
            f"QProgressBar {{ border: 0; background-color: {colors['divider']}; border-radius: 999px; }}"
            "QProgressBar::chunk { background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4f46e5, stop:1 #2563eb); border-radius: 999px; }"
        )


class TopAppsList(QWidget):
    """A vertical stack of DurationBarRow entries, sorted by duration descending."""

    def __init__(self, app_usages: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        if not app_usages:
            placeholder = QLabel("No activity recorded yet.")
            colors = colors_for(current_theme())
            placeholder.setStyleSheet(
                f"QLabel {{ color: {colors['muted_text']}; font-size: 11px; font-style: italic; }}"
            )
            layout.addWidget(placeholder)
            return

        max_seconds = max(usage.total_seconds for usage in app_usages)
        for usage in app_usages:
            layout.addWidget(DurationBarRow(usage.app_name, usage.total_seconds, max_seconds))

    def apply_theme(self, theme: str) -> None:
        for row in self.findChildren(DurationBarRow):
            row.apply_theme(theme)


class StatCard(QWidget):
    """A labeled headline stat, e.g. \"Total Screen Time\" / \"3h 42m\"."""

    def __init__(self, caption: str, value_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statCard")
        self._theme = current_theme()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        caption_label = QLabel(caption)
        self._caption_label = caption_label
        self.value_label = QLabel(value_text)

        layout.addWidget(caption_label)
        layout.addWidget(self.value_label)
        self.apply_theme(self._theme)

    def apply_theme(self, theme: str) -> None:
        colors = colors_for(theme)
        self.setStyleSheet(
            f"QWidget#statCard {{ background-color: {colors['raised_surface']}; border: 1px solid {colors['border']}; border-radius: 16px; }}"
        )
        self._caption_label.setStyleSheet(
            f"QLabel {{ color: {colors['muted_text']}; font-size: 10px; text-transform: uppercase; letter-spacing: 1.2px; }}"
        )
        self.value_label.setStyleSheet(
            f"QLabel {{ color: {colors['text']}; font-size: 18px; font-weight: 700; }}"
        )

    def set_value(self, value_text: str) -> None:
        self.value_label.setText(value_text)
