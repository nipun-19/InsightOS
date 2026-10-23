import re
import sys
from pathlib import Path

from src import config
from src.core import platform_win
from src.ui.desktop_widget import DesktopWidget
from src.utils import settings_store
from main import _sync_autostart_from_settings


def test_per_user_installer_removes_only_insightos_run_value_on_uninstall() -> None:
    installer_script = config.BASE_DIR / "build" / "InsightOS.iss"
    content = installer_script.read_text(encoding="utf-8")
    code_section = content.split("[Code]", maxsplit=1)[1]
    uninstall_hook = re.search(
        r"procedure CurUninstallStepChanged\(CurUninstallStep: TUninstallStep\);"
        r"(.*?)\nend;",
        code_section,
        flags=re.DOTALL,
    )

    assert "PrivilegesRequired=lowest" in content
    assert r"DefaultDirName={localappdata}\Programs\InsightOS" in content
    assert "{userprograms}" in content
    assert "{userdesktop}" in content
    assert uninstall_hook is not None
    normalized_hook = re.sub(r"\s+", " ", uninstall_hook.group(1)).strip()
    assert normalized_hook == (
        "begin if CurUninstallStep = usUninstall then RegDeleteValue("
        " HKEY_CURRENT_USER, "
        "'Software\\Microsoft\\Windows\\CurrentVersion\\Run', 'InsightOS');"
    )
    assert code_section.count("RegDeleteValue(") == 1
    assert "RegDeleteKey(" not in code_section
    assert "DelTree(" not in content
    assert "[UninstallDelete]" not in content
    assert r"{localappdata}\InsightOS" not in content


def test_runtime_data_dir_respects_explicit_override(monkeypatch, tmp_path):
    override = tmp_path / "insightos-runtime-data"
    monkeypatch.setenv("INSIGHTOS_DATA_DIR", str(override))
    assert config.resolve_user_data_dir() == override
    assert config.DATA_DIR == override


def test_autostart_uses_installed_executable_when_frozen(monkeypatch):
    monkeypatch.setattr(platform_win.sys, "frozen", True, raising=False)
    monkeypatch.setattr(platform_win.sys, "executable", r"C:\\Program Files\\InsightOS\\InsightOS.exe", raising=False)

    command = platform_win._autostart_command()

    assert command.startswith('"C:\\Program Files\\InsightOS\\InsightOS.exe"')
    assert "main.py" not in command.lower()


class _FakeRegistry:
    HKEY_CURRENT_USER = object()
    KEY_ALL_ACCESS = 0xF003F
    REG_SZ = 1

    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.opened: tuple[object, str, int, int] | None = None

    def OpenKey(self, root, key_path, reserved, access):
        self.opened = (root, key_path, reserved, access)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def SetValueEx(self, key, name, reserved, value_type, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def _install_fake_registry(monkeypatch, values: dict[str, str]) -> _FakeRegistry:
    registry = _FakeRegistry(values)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(platform_win, "_autostart_command", lambda: '"C:\\InsightOS.exe"')
    return registry


def test_saved_autostart_enabled_registers_only_insightos(monkeypatch, tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    original_path = config.SETTINGS_FILE_PATH
    values = {"OtherApp": '"C:\\OtherApp.exe"'}
    registry = _install_fake_registry(monkeypatch, values)

    try:
        config.SETTINGS_FILE_PATH = settings_path
        DesktopWidget._set_auto_start(None, True)

        assert registry.opened == (
            _FakeRegistry.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            _FakeRegistry.KEY_ALL_ACCESS,
        )
        assert values == {
            "OtherApp": '"C:\\OtherApp.exe"',
            "InsightOS": '"C:\\InsightOS.exe"',
        }
        assert settings_store.get_value("widget_auto_start") is True
    finally:
        config.SETTINGS_FILE_PATH = original_path


def test_saved_autostart_disabled_removes_only_insightos(monkeypatch, tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    original_path = config.SETTINGS_FILE_PATH
    values = {
        "OtherApp": '"C:\\OtherApp.exe"',
        "InsightOS": '"C:\\InsightOS.exe"',
    }
    _install_fake_registry(monkeypatch, values)

    try:
        config.SETTINGS_FILE_PATH = settings_path
        DesktopWidget._set_auto_start(None, False)

        assert values == {"OtherApp": '"C:\\OtherApp.exe"'}
        assert settings_store.get_value("widget_auto_start") is False
    finally:
        config.SETTINGS_FILE_PATH = original_path


def test_uninstall_preserves_opt_in_setting_and_reinstall_restores_run_value(
    monkeypatch, tmp_path
) -> None:
    settings_path = tmp_path / "settings.json"
    original_path = config.SETTINGS_FILE_PATH
    values = {
        "OtherApp": '"C:\\OtherApp.exe"',
        "InsightOS": '"C:\\OldInsightOS.exe"',
    }
    _install_fake_registry(monkeypatch, values)

    try:
        config.SETTINGS_FILE_PATH = settings_path
        settings_store.set_value("widget_auto_start", True)

        # Model the narrowly scoped uninstaller operation without executing it.
        del values["InsightOS"]

        assert settings_store.get_value("widget_auto_start") is True
        assert values == {"OtherApp": '"C:\\OtherApp.exe"'}

        # Reinstall's first application startup reconciles the preserved opt-in.
        _sync_autostart_from_settings()

        assert values == {
            "OtherApp": '"C:\\OtherApp.exe"',
            "InsightOS": '"C:\\InsightOS.exe"',
        }
        assert settings_store.get_value("widget_auto_start") is True
    finally:
        config.SETTINGS_FILE_PATH = original_path


def test_uninstall_and_reinstall_keep_disabled_autostart_disabled(
    monkeypatch, tmp_path
) -> None:
    settings_path = tmp_path / "settings.json"
    original_path = config.SETTINGS_FILE_PATH
    values = {
        "OtherApp": '"C:\\OtherApp.exe"',
        "InsightOS": '"C:\\OldInsightOS.exe"',
    }
    _install_fake_registry(monkeypatch, values)

    try:
        config.SETTINGS_FILE_PATH = settings_path
        settings_store.set_value("widget_auto_start", False)

        # The installer hook removes only InsightOS; settings remain separate.
        del values["InsightOS"]

        assert settings_store.get_value("widget_auto_start") is False
        assert values == {"OtherApp": '"C:\\OtherApp.exe"'}

        # First startup after reinstall must not recreate an opted-out entry.
        _sync_autostart_from_settings()

        assert values == {"OtherApp": '"C:\\OtherApp.exe"'}
        assert settings_store.get_value("widget_auto_start") is False
    finally:
        config.SETTINGS_FILE_PATH = original_path
