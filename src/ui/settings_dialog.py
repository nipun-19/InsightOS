"""A polished settings experience for InsightOS.

This stays within the UI-only scope of the Phase D polish: it presents
existing settings through a premium, Windows-style surface without changing
tracker, database, or analytics behavior.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src import config
from src.core import platform_win
from src.ui.theme import colors_for, current_theme
from src.utils import settings_store


class SettingsDialog(QDialog):
    """Modern settings dialog with grouped, premium styling."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("InsightOS Settings")
        self.setModal(True)
        self.resize(720, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header = QLabel("Preferences")
        self._header_label = header
        layout.addWidget(header)

        subtitle = QLabel("Adjust how InsightOS feels on your desktop while keeping your usage tracking intact.")
        subtitle.setWordWrap(True)
        self._subtitle_label = subtitle
        layout.addWidget(subtitle)

        content = QFrame(self)
        content.setObjectName("contentFrame")
        content.setStyleSheet("QFrame#contentFrame { background: transparent; }")
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(12)

        appearance_group = QGroupBox("Appearance")
        appearance_layout = QFormLayout(appearance_group)
        appearance_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self._widget_toggle = QCheckBox("Show desktop widget")
        self._widget_toggle.setChecked(bool(settings_store.get_value("widget_enabled")))
        appearance_layout.addRow(self._widget_toggle)

        self._compact_toggle = QCheckBox("Compact widget layout")
        self._compact_toggle.setChecked(bool(settings_store.get_value("widget_compact_mode")))
        appearance_layout.addRow(self._compact_toggle)

        self._opacity_combo = QComboBox()
        self._opacity_combo.addItems(["80%", "90%", "96%", "100%"])
        opacity_value = float(settings_store.get_value("widget_opacity"))
        if abs(opacity_value - 0.80) < 1e-6:
            self._opacity_combo.setCurrentIndex(0)
        elif abs(opacity_value - 0.90) < 1e-6:
            self._opacity_combo.setCurrentIndex(1)
        elif abs(opacity_value - 0.96) < 1e-6:
            self._opacity_combo.setCurrentIndex(2)
        else:
            self._opacity_combo.setCurrentIndex(3)
        appearance_layout.addRow("Widget opacity", self._opacity_combo)

        content_layout.addWidget(appearance_group)

        behavior_group = QGroupBox("Behavior")
        behavior_layout = QFormLayout(behavior_group)
        behavior_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self._autostart_toggle = QCheckBox("Start with Windows")
        self._autostart_toggle.setChecked(bool(settings_store.get_value("widget_auto_start")))
        behavior_layout.addRow(self._autostart_toggle)

        content_layout.addWidget(behavior_group)

        layout.addWidget(content)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._apply_button_styles(buttons)
        self.apply_theme(current_theme())

    def apply_theme(self, theme: str) -> None:
        colors = colors_for(theme)
        self.setStyleSheet(
            f"QDialog {{ background-color: {colors['surface']}; }}"
            f"QGroupBox {{ border: 1px solid {colors['border']}; border-radius: 14px; margin-top: 10px; background-color: {colors['raised_surface']}; padding: 10px; color: {colors['text']}; }}"
            f"QGroupBox:title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; color: {colors['text']}; font-weight: 600; }}"
            f"QLabel, QCheckBox {{ color: {colors['text']}; }}"
            f"QComboBox {{ color: {colors['text']}; padding: 6px 8px; border: 1px solid {colors['border']}; border-radius: 8px; background-color: {colors['field']}; }}"
            "QPushButton { padding: 8px 14px; border-radius: 999px; background-color: #2563eb; color: white; border: none; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
            "QPushButton:pressed { background-color: #1e40af; }"
        )
        self._header_label.setStyleSheet(
            f"QLabel {{ color: {colors['text']}; font-size: 20px; font-weight: 700; }}"
        )
        self._subtitle_label.setStyleSheet(
            f"QLabel {{ color: {colors['muted_text']}; font-size: 11px; }}"
        )

    def _apply_button_styles(self, buttons: QDialogButtonBox) -> None:
        for button in buttons.buttons():
            button.setCursor(Qt.CursorShape.PointingHandCursor)

    def accept(self) -> None:  # noqa: PLR0912
        settings_store.set_value("widget_enabled", self._widget_toggle.isChecked())
        settings_store.set_value("widget_compact_mode", self._compact_toggle.isChecked())
        settings_store.set_value("widget_auto_start", self._autostart_toggle.isChecked())
        if config.APP_NAME:
            try:
                platform_win.set_startup_entry(self._autostart_toggle.isChecked())
            except Exception:  # noqa: BLE001
                pass

        opacity_map = {0: 0.80, 1: 0.90, 2: 0.96, 3: 1.00}
        settings_store.set_value("widget_opacity", opacity_map.get(self._opacity_combo.currentIndex(), 0.96))
        super().accept()


if __name__ == "__main__":
    app = QApplication([])
    dlg = SettingsDialog()
    dlg.show()
    app.exec()
