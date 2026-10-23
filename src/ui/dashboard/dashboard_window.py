"""The Dashboard window shell: a tab container for Today / History (§12).

Per §9, Dashboard windows are destroyed on close (opened infrequently) —
this window sets WA_DeleteOnClose so Qt frees it fully rather than just
hiding it, unlike the Desktop Widget. Per §4/§12, closing this window must
never affect the Tracker: this class contains no tracker or DB-write code
at all, only tab wiring.
"""

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget, QWidget

from src import config
from src.ui.dashboard.history_view import HistoryView
from src.ui.dashboard.today_view import TodayView
from src.ui.startup_state import StartupStateStore
from src.ui.theme import colors_for, current_theme

if TYPE_CHECKING:
    from src.core.tracker import Tracker


class DashboardWindow(QTabWidget):
    """Top-level Dashboard window containing the Today and History tabs."""

    def __init__(self, parent: QWidget | None = None, tracker: "Tracker | None" = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{config.APP_NAME} • Dashboard")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(760, 560)
        self.setDocumentMode(True)

        self.addTab(TodayView(tracker=tracker), "Today")
        self.addTab(HistoryView(), "History")
        self.currentChanged.connect(self._persist_state)
        self._restore_state()
        self.apply_theme(current_theme())

    def apply_theme(self, theme: str) -> None:
        colors = colors_for(theme)
        self.setStyleSheet(
            f"QTabWidget {{ background-color: {colors['surface']}; color: {colors['text']}; }}"
            f"QTabWidget::pane {{ border: 1px solid {colors['border']}; border-radius: 16px; background-color: {colors['surface']}; padding: 2px; }}"
            f"QTabBar::tab {{ background: transparent; color: {colors['muted_text']}; padding: 8px 14px; margin-right: 6px; border-radius: 999px; }}"
            "QTabBar::tab:selected { background-color: #2563eb; color: white; font-weight: 600; }"
            "QTabBar::tab:hover { background-color: rgba(37, 99, 235, 0.10); color: #2563eb; }"
        )
        for index in range(self.count()):
            view = self.widget(index)
            apply_theme = getattr(view, "apply_theme", None)
            if callable(apply_theme):
                apply_theme(theme)

    def _restore_state(self) -> None:
        state = StartupStateStore().restore_dashboard_state()
        self.setCurrentIndex(min(max(int(state.get("tab_index", 0)), 0), self.count() - 1))
        history_view = self.widget(1)
        if isinstance(history_view, HistoryView):
            history_view.set_range(state.get("history_range", "Today"))
            history_view.set_query(state.get("history_query", ""))
            history_view.set_sort(state.get("history_sort", "Newest"))

    def _persist_state(self, index: int) -> None:
        history_view = self.widget(1)
        if not isinstance(history_view, HistoryView):
            return
        StartupStateStore().remember_dashboard_state(
            index,
            history_view.selected_range(),
            history_view.current_query(),
            history_view.current_sort(),
        )
