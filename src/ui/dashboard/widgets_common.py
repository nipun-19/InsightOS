"""Shared small UI components used across Dashboard tabs/views (§6).

Purely presentational — rendering only, no DB writes, no business logic.
Kept here so today_view.py and history_view.py don't duplicate layout code
(§22 rule 9: no duplicated logic).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from utils import time_utils


class DurationBarRow(QWidget):
    """A single "app name — duration bar — duration text" row.

    Used by the Top Apps list on both the Today tab and History sub-views.
    """

    def __init__(self, app_name: str, seconds: int, max_seconds: int, parent: QWidget | None = None) -> None:
        """Build one row scaled relative to the largest value in its list.

        Args:
            app_name: Executable name to display, e.g. "chrome.exe".
            seconds: This row's total duration in seconds.
            max_seconds: The largest duration among sibling rows, used to
                scale the progress bar to 0-100. Must be >= seconds.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        name_label = QLabel(app_name)
        name_label.setMinimumWidth(140)

        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setMaximum(max(max_seconds, 1))
        bar.setValue(min(seconds, max_seconds))

        duration_label = QLabel(time_utils.format_duration(seconds))
        duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        duration_label.setMinimumWidth(70)

        layout.addWidget(name_label)
        layout.addWidget(bar, stretch=1)
        layout.addWidget(duration_label)


class TopAppsList(QWidget):
    """A vertical stack of DurationBarRow entries, sorted by duration descending."""

    def __init__(self, app_usages: list, parent: QWidget | None = None) -> None:
        """Build the list from a sequence of AppUsage-like objects.

        Args:
            app_usages: Items with `.app_name` and `.total_seconds`
                attributes (core.models.AppUsage), already sorted
                descending by the caller (database.get_top_apps() does this).
            parent: Optional parent widget.
        """
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if not app_usages:
            layout.addWidget(QLabel("No activity recorded yet."))
            return

        max_seconds = max(usage.total_seconds for usage in app_usages)
        for usage in app_usages:
            layout.addWidget(DurationBarRow(usage.app_name, usage.total_seconds, max_seconds))


class StatCard(QWidget):
    """A labeled headline stat, e.g. "Total Screen Time" / "3h 42m"."""

    def __init__(self, caption: str, value_text: str, parent: QWidget | None = None) -> None:
        """Build a small caption-over-value stat block.

        Args:
            caption: Small label above the value, e.g. "Total Screen Time".
            value_text: The large display value, e.g. "3h 42m".
            parent: Optional parent widget.
        """
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        caption_label = QLabel(caption)
        self.value_label = QLabel(value_text)
        value_font = self.value_label.font()
        value_font.setPointSize(value_font.pointSize() + 6)
        value_font.setBold(True)
        self.value_label.setFont(value_font)

        layout.addWidget(caption_label)
        layout.addWidget(self.value_label)

    def set_value(self, value_text: str) -> None:
        """Update the displayed value text.

        Args:
            value_text: New large display value.

        Returns:
            None.
        """
        self.value_label.setText(value_text)
