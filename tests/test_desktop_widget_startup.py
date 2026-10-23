import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPalette
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QWidget

from src import config
from src.ui.desktop_widget import DesktopWidget
from src.ui.startup_state import StartupStateStore
from src.utils import settings_store


def test_desktop_widget_can_fade_out_without_connect_warnings() -> None:
    app = QApplication.instance() or QApplication([])
    widget = DesktopWidget()
    try:
        widget._fade_out()
    finally:
        widget.close()
        app.quit()


@pytest.mark.parametrize(
    ("theme", "surface"),
    (("dark", "#171c26"), ("light", "#f8fafc")),
)
def test_widget_renders_persisted_theme_before_display(
    monkeypatch, tmp_path, theme: str, surface: str
) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "SETTINGS_FILE_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(config, "STARTUP_STATE_FILE_PATH", tmp_path / "startup_state.json")
    settings_store.set_value("theme", theme)
    settings_store.set_value("widget_visible", False)
    StartupStateStore().remember_widget(
        (config.WIDGET_DEFAULT_X, config.WIDGET_DEFAULT_Y, config.WIDGET_WIDTH, config.WIDGET_HEIGHT),
        False,
        False,
        0.96,
    )
    widget = DesktopWidget()
    try:
        assert widget._theme == theme
        assert settings_store.get_value("theme") == theme

        QWidget.show(widget)
        app.processEvents()
        assert widget._frame.palette().color(QPalette.ColorRole.Window).name() == surface
        image = widget._frame.grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
        y = round(widget._frame.layout().contentsMargins().top() * image.devicePixelRatioF() / 2)
        assert image.pixelColor(image.width() // 2, y).name() == surface

        widget.hide()
        widget._on_refresh_tick()
        assert widget._theme == theme
        assert widget._frame.palette().color(QPalette.ColorRole.Window).name() == surface
        assert settings_store.get_value("theme") == theme
    finally:
        widget.close()
        app.quit()
