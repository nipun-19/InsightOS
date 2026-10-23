from pathlib import Path

from src import config
from src.utils import settings_store


def test_settings_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    original = config.SETTINGS_FILE_PATH
    try:
        config.SETTINGS_FILE_PATH = path
        settings_store.set_value("widget_visible", False)
        settings_store.set_value("widget_x", 77)
        settings_store.set_value("widget_y", 88)

        loaded = settings_store.load_settings()
        assert loaded["widget_visible"] is False
        assert loaded["widget_x"] == 77
        assert loaded["widget_y"] == 88
    finally:
        config.SETTINGS_FILE_PATH = original


def test_settings_load_recovers_from_missing_and_malformed_data(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    original = config.SETTINGS_FILE_PATH
    try:
        config.SETTINGS_FILE_PATH = path
        path.write_text("{not valid json}", encoding="utf-8")
        assert settings_store.load_settings()["widget_visible"] is True

        path.write_text('{"widget_visible": false, "widget_x": "bad"}', encoding="utf-8")
        loaded = settings_store.load_settings()
        assert loaded["widget_visible"] is False
        assert loaded["widget_x"] == "bad"
    finally:
        config.SETTINGS_FILE_PATH = original


def test_settings_write_is_atomic_and_safe_for_corrupt_files(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    original = config.SETTINGS_FILE_PATH
    try:
        config.SETTINGS_FILE_PATH = path
        path.write_text('{"widget_visible": true}', encoding="utf-8")
        settings_store.save_settings({"widget_visible": False, "widget_x": 12, "widget_y": 21})
        loaded = settings_store.load_settings()
        assert loaded["widget_visible"] is False
        assert loaded["widget_x"] == 12
        assert loaded["widget_y"] == 21
    finally:
        config.SETTINGS_FILE_PATH = original
