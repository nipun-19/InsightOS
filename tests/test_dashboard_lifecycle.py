from PySide6.QtWidgets import QApplication

from src.ui.dashboard.dashboard_window import DashboardWindow


def test_dashboard_window_can_show_and_close_without_crashing() -> None:
    app = QApplication.instance() or QApplication([])
    window = DashboardWindow()
    try:
        window.show()
        assert window.isVisible()
    finally:
        window.close()
        app.quit()
