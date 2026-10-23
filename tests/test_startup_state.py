from pathlib import Path

from src.ui.startup_state import StartupStateStore


def test_startup_state_store_round_trips_widget_and_dashboard_state(tmp_path: Path) -> None:
    store = StartupStateStore(path=tmp_path / "startup_state.json")

    store.remember_widget((11, 22, 33, 44), True, True, 0.8)
    store.remember_window("Dashboard", (1, 2, 3, 4))
    store.remember_dashboard_state(1, "Yesterday", "code", "Longest")

    widget_state = store.restore_widget()
    dashboard_state = store.restore_dashboard_state()

    assert widget_state["geometry"] == (11, 22, 33, 44)
    assert widget_state["visible"] is True
    assert widget_state["compact"] is True
    assert widget_state["opacity"] == 0.8
    assert dashboard_state == {
        "tab_index": 1,
        "history_range": "Yesterday",
        "history_query": "code",
        "history_sort": "Longest",
    }


def test_startup_state_store_recovers_from_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "startup_state.json"
    path.write_text("{not valid json", encoding="utf-8")

    state = StartupStateStore(path=path)

    assert state.load() == {}
    assert state.restore_widget()["geometry"] != ()
    assert state.restore_dashboard_state()["tab_index"] == 0


def test_startup_state_store_rejects_invalid_geometry_payloads(tmp_path: Path) -> None:
    path = tmp_path / "startup_state.json"
    path.write_text('{"widget": {"geometry": [1, 2, "bad", 4]}}', encoding="utf-8")

    state = StartupStateStore(path=path)
    widget_state = state.restore_widget()

    assert widget_state["geometry"][0] > 0
    assert len(widget_state["geometry"]) == 4
