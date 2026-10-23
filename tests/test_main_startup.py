import sys

import src.config as config
import src.core.platform_win as platform_win
from main import _set_process_priority


def test_set_process_priority_uses_supported_config_name(monkeypatch) -> None:
    monkeypatch.setattr(config, "PROCESS_PRIORITY_BELOW_NORMAL", None, raising=False)
    monkeypatch.setattr(config, "PROCESS_PRIORITY_CLASS", "BELOW_NORMAL", raising=True)
    monkeypatch.setattr(sys, "platform", "win32")

    called = False

    def fake_set_priority() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(platform_win, "set_process_priority_below_normal", fake_set_priority, raising=False)

    _set_process_priority()

    assert called
