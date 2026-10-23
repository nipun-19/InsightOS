"""Lightweight toast notifications for InsightOS UI feedback."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel, QWidget


class ToastWidget(QWidget):
    """A small, dismissible notification overlay."""

    def __init__(self, title: str, body: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(
            "QWidget { background-color: rgba(15, 23, 42, 0.92); border-radius: 12px; padding: 10px; }"
            "QLabel { color: white; }"
        )
        self._layout = QWidget(self)
        self._layout.setStyleSheet("background: transparent;")

        from PySide6.QtWidgets import QVBoxLayout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        title_label = QLabel(title)
        title_label.setStyleSheet("QLabel { color: white; font-weight: 700; }")
        body_label = QLabel(body)
        body_label.setWordWrap(True)
        body_label.setStyleSheet("QLabel { color: rgba(255,255,255,0.86); font-size: 11px; }")
        layout.addWidget(title_label)
        layout.addWidget(body_label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)

    def show(self) -> None:  # noqa: PLR0913
        super().show()
        self._timer.start(2200)


def show_toast(title: str, body: str) -> None:
    """Display a toast notification anchored to the current desktop."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtCore import QPoint

    widget = ToastWidget(title, body)
    desktop = QGuiApplication.primaryScreen().availableGeometry()
    x = desktop.right() - 320
    y = desktop.bottom() - 120
    widget.move(max(desktop.left(), x), max(desktop.top(), y))
    widget.resize(260, 70)
    widget.show()
