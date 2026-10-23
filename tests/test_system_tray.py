from PySide6.QtWidgets import QApplication

from src.ui.system_tray import SystemTray


def test_system_tray_uses_a_valid_icon_when_configured_path_is_missing() -> None:
    app = QApplication.instance() or QApplication([])
    tray = SystemTray(app, lambda: None)
    try:
        assert not tray.icon().isNull()
    finally:
        tray.hide()
        app.quit()
