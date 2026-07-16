"""The Dashboard window shell: a tab container for Today / History (§12).

Per §9, Dashboard windows are destroyed on close (opened infrequently) —
this window sets WA_DeleteOnClose so Qt frees it fully rather than just
hiding it, unlike the Desktop Widget. Per §4/§12, closing this window must
never affect the Tracker: this class contains no tracker or DB-write code
at all, only tab wiring.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget, QWidget

import config
from ui.dashboard.history_view import HistoryView
from ui.dashboard.today_view import TodayView


class DashboardWindow(QTabWidget):
    """Top-level Dashboard window containing the Today and History tabs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the window, its two tabs, and set close-to-destroy behavior."""
        super().__init__(parent)
        self.setWindowTitle(config.APP_NAME)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(640, 480)

        self.addTab(TodayView(), "Today")
        self.addTab(HistoryView(), "History")
