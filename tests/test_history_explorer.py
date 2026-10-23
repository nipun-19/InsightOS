from pathlib import Path
import csv
import json

from PySide6.QtWidgets import QApplication

from src.core import database as db
from src.core.models import AppSession
from src.ui.dashboard.history_view import HistoryView


def test_history_view_filters_sessions_by_query_and_sorting() -> None:
    app = QApplication.instance() or QApplication([])
    view = HistoryView()
    try:
        sessions = [
            AppSession(app_name="code.exe", start_time="2024-01-01T10:00:00+00:00", date="2024-01-01", end_time="2024-01-01T11:00:00+00:00", duration_seconds=3600),
            AppSession(app_name="msedge.exe", start_time="2024-01-01T11:30:00+00:00", date="2024-01-01", end_time="2024-01-01T11:50:00+00:00", duration_seconds=1200),
        ]
        filtered = view._filter_sessions(sessions, query="code", sort_order="alphabetical")
        assert len(filtered) == 1
        assert filtered[0].app_name == "code.exe"
    finally:
        view.close()
        app.quit()


def test_export_history_writes_csv_and_json(tmp_path: Path) -> None:
    db.init_db()
    session_id = db.open_app_session("code.exe", "Visual Studio Code", "2024-01-02T09:00:00+00:00", "2024-01-02")
    db.close_app_session(session_id, "2024-01-02T09:45:00+00:00")

    csv_path = tmp_path / "history.csv"
    json_path = tmp_path / "history.json"

    db.export_history_csv(["2024-01-02"], str(csv_path))
    db.export_history_json(["2024-01-02"], str(json_path))

    assert csv_path.exists()
    assert json_path.exists()

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        assert rows[0]["app_name"] == "code.exe"

    with json_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
        assert payload["sessions"][0]["app_name"] == "code.exe"
