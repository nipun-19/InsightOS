from PySide6.QtWidgets import QApplication

from src.ui.settings_dialog import SettingsDialog


def test_settings_dialog_constructs_with_expected_title() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog()
    try:
        assert dialog.windowTitle() == "InsightOS Settings"
    finally:
        dialog.close()
        app.quit()
