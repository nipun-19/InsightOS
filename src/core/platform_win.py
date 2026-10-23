"""Windows-only helpers for desktop-shell widget integration."""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Optional

from src import config
from src.utils.logger import get_logger

logger = get_logger(__name__)

_USER32 = ctypes.windll.user32

# Helper to match LONG_PTR size on the current platform
_PTR_SIZE = ctypes.sizeof(ctypes.c_void_p)

# Explicit ctypes prototypes for pointer-sized window APIs.
_USER32.GetWindowLongPtrW.restype = ctypes.c_longlong if _PTR_SIZE == 8 else ctypes.c_long
_USER32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_USER32.SetWindowLongPtrW.restype = ctypes.c_longlong if _PTR_SIZE == 8 else ctypes.c_long
_USER32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong if _PTR_SIZE == 8 else ctypes.c_long]
_USER32.SetParent.restype = wintypes.HWND
_USER32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
_USER32.SetWindowPos.restype = wintypes.BOOL
_USER32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
_USER32.SetWinEventHook.restype = wintypes.HANDLE
_USER32.UnhookWinEvent.restype = wintypes.BOOL
_USER32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
_USER32.GetForegroundWindow.restype = wintypes.HWND
_USER32.GetForegroundWindow.argtypes = []
_USER32.GetParent.restype = wintypes.HWND
_USER32.GetParent.argtypes = [wintypes.HWND]
_USER32.GetClassNameW.restype = ctypes.c_int
_USER32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_USER32.GetWindow.restype = wintypes.HWND
_USER32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_USER32.IsWindowVisible.restype = wintypes.BOOL
_USER32.IsWindowVisible.argtypes = [wintypes.HWND]
_USER32.GetParent.restype = wintypes.HWND
_USER32.GetParent.argtypes = [wintypes.HWND]
_USER32.GetWindowRect.restype = wintypes.BOOL
_USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_USER32.MonitorFromWindow.restype = wintypes.HMONITOR
_USER32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_KERNEL32 = ctypes.windll.kernel32
_KERNEL32.OpenProcess.restype = wintypes.HANDLE
_KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_KERNEL32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_KERNEL32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_KERNEL32.CloseHandle.restype = wintypes.BOOL
_KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
_KERNEL32.GetTickCount64.restype = ctypes.c_ulonglong

_WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.HWND,
    ctypes.c_long,
    ctypes.c_long,
    wintypes.DWORD,
    wintypes.DWORD,
)
_USER32.SetWinEventHook.argtypes = [
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HMODULE,
    _WINEVENTPROC,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
]
_EVENT_SYSTEM_FOREGROUND = 0x0003
_WINEVENT_OUTOFCONTEXT = 0x0000


def _pack_long_ptr(value: int):
    if _PTR_SIZE == 8:
        return ctypes.c_longlong(value)
    return ctypes.c_long(value)

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_CLIPSIBLINGS = 0x04000000
WS_CLIPCHILDREN = 0x02000000
WS_VISIBLE = 0x10000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_POPUP = 0x80000000
WS_OVERLAPPED = 0x00000000
WS_SYSMENU = 0x00080000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000

HWND_TOP = 0
HWND_BOTTOM = 1
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

GW_OWNER = 4
SWP_NOACTIVATE = 0x0010
SWP_NOSENDCHANGING = 0x0400
SWP_NOOWNERZORDER = 0x0200
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001

WM_POWERBROADCAST = 0x0210
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_WTSSESSION_CHANGE = 0x02B1
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMECRITICAL = 0x0006
PBT_APMRESUMEAUTOMATIC = 0x0000
PBT_APMRESUMESUSPEND = 0x0007
WTS_SESSION_LOGON = 0x00000001
WTS_SESSION_LOGOFF = 0x00000000


class _WindowInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcWindow", wintypes.RECT),
        ("rcClient", wintypes.RECT),
        ("dwStyle", wintypes.DWORD),
        ("dwExStyle", wintypes.DWORD),
        ("dwWindowStatus", wintypes.DWORD),
        ("cxWindowBorders", wintypes.UINT),
        ("cyWindowBorders", wintypes.UINT),
        ("atomWindowType", wintypes.ATOM),
        ("wCreatorVersion", wintypes.USHORT),
    ]


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwTime", wintypes.DWORD)]


def get_shell_window() -> Optional[int]:
    """Return the shell desktop window handle if available."""
    try:
        return _USER32.GetShellWindow()
    except Exception:  # noqa: BLE001
        return None


def get_desktop_window() -> Optional[int]:
    """Return the desktop window handle if available."""
    try:
        return _USER32.GetDesktopWindow()
    except Exception:  # noqa: BLE001
        return None


def get_foreground_window() -> Optional[int]:
    """Return the current foreground window handle if available."""
    try:
        return _USER32.GetForegroundWindow()
    except Exception:  # noqa: BLE001
        return None


def is_desktop_or_owned_widget_foreground(widget_hwnd: int) -> bool:
    """Return whether the desktop or this widget's owned popup is foreground."""
    hwnd = get_foreground_window()
    if not hwnd:
        return False
    if get_window_class_name(hwnd) in _DESKTOP_FOREGROUND_CLASSES:
        return True

    owner = _USER32.GetWindow(hwnd, GW_OWNER)
    while owner:
        if owner == widget_hwnd:
            return True
        owner = _USER32.GetWindow(owner, GW_OWNER)
    return hwnd == widget_hwnd


def set_window_topmost(hwnd: int, topmost: bool) -> bool:
    """Change a window's z-order without moving, resizing, or activating it."""
    insert_after = HWND_TOPMOST if topmost else HWND_NOTOPMOST
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER
    return bool(_USER32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags))


def watch_foreground_changes(
    on_foreground_change: Callable[[], None],
) -> tuple[int, object] | None:
    """Subscribe to foreground-window changes on the calling thread."""
    def _on_event(
        _hook: int,
        event: int,
        _hwnd: int,
        _object_id: int,
        _child_id: int,
        _event_thread: int,
        _event_time: int,
    ) -> None:
        if event == _EVENT_SYSTEM_FOREGROUND:
            try:
                on_foreground_change()
            except Exception:  # noqa: BLE001
                logger.exception("Foreground-window callback failed")

    callback = _WINEVENTPROC(_on_event)
    hook = _USER32.SetWinEventHook(
        _EVENT_SYSTEM_FOREGROUND,
        _EVENT_SYSTEM_FOREGROUND,
        None,
        callback,
        0,
        0,
        _WINEVENT_OUTOFCONTEXT,
    )
    if not hook:
        logger.warning("Could not subscribe to foreground-window changes")
        return None
    return int(hook), callback


def unwatch_foreground_changes(hook: int) -> bool:
    """Release a foreground-window subscription."""
    success = bool(_USER32.UnhookWinEvent(hook))
    if not success:
        logger.warning("Could not release foreground-window hook %s", hook)
    return success


def desktop_attachment_disabled() -> bool:
    """Whether shell attachment is explicitly disabled for debugging/fallback mode."""
    value = os.getenv("INSIGHTOS_DISABLE_DESKTOP_ATTACHMENT", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def get_idle_seconds() -> int:
    """Estimate idle time in seconds using the last-input timestamp."""
    if sys.platform != "win32":
        return 0
    try:
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(_LastInputInfo)
        if not _USER32.GetLastInputInfo(ctypes.byref(info)):
            return 0
        now_ms = int(_KERNEL32.GetTickCount64())
        return max(0, (now_ms - info.dwTime) // 1000)
    except Exception:  # noqa: BLE001
        return 0


_IGNORED_SHELL_CLASSES = {
    "Progman",
    "WorkerW",
    "SHELLDLL_DefView",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "ApplicationManager_DesktopShellWindow",
    "XamlExplorerHostIslandWindow",
}
_IGNORED_SHELL_PROCESSES = {
    "dwm.exe",
    "explorer.exe",
    "runtimebroker.exe",
    "shellexperiencehost.exe",
}
_DESKTOP_FOREGROUND_CLASSES = {
    "Progman",
    "WorkerW",
    "SHELLDLL_DefView",
}


def _is_desktop_shell_window(hwnd: int) -> bool:
    """Return whether this foreground HWND is a shell-only desktop surface, not user activity."""
    try:
        class_name = get_window_class_name(hwnd)
        if class_name in _IGNORED_SHELL_CLASSES:
            return True
        if not class_name:
            return False
        parent = _USER32.GetParent(hwnd)
        if parent:
            parent_class = get_window_class_name(parent)
            if parent_class in _IGNORED_SHELL_CLASSES:
                # A real Explorer window can sit under a WorkerW shell container, so
                # only reject the desktop shell surfaces themselves; genuine explorer
                # windows are allowed through here and filtered by the process check.
                return not _is_real_file_explorer_window(hwnd, None, class_name)
        return False
    except Exception:  # noqa: BLE001
        return False


def _is_real_file_explorer_window(hwnd: int, app_name: str | None, class_name: str | None) -> bool:
    """Return True only for genuine File Explorer windows, not desktop shell surfaces."""
    if app_name is not None and app_name.lower() != "explorer.exe":
        return False
    return class_name == "CabinetWClass"


def get_foreground_app() -> tuple[str | None, str | None]:
    """Return the current foreground application's name and window title."""
    if sys.platform != "win32":
        return None, None
    try:
        hwnd = get_foreground_window()
        if not hwnd:
            logger.debug("foreground detection: no foreground hwnd")
            return None, None

        title_buffer = ctypes.create_unicode_buffer(512)
        _USER32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        title = title_buffer.value or None
        class_name = get_window_class_name(hwnd)
        logger.debug("foreground check: hwnd=0x%x class=%s title=%r", hwnd, class_name or "", (title[:80] if title else ""))

        if _is_desktop_shell_window(hwnd):
            logger.info("foreground rejected as shell-only: hwnd=0x%x class=%s title=%r", hwnd, class_name or "", (title[:80] if title else ""))
            return None, None

        process_id = wintypes.DWORD()
        if not _USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id)):
            logger.info("foreground rejected: unable to resolve process for hwnd=0x%x title=%r", hwnd, (title[:80] if title else ""))
            return None, title

        process_handle = _KERNEL32.OpenProcess(0x1000, False, process_id.value)
        if not process_handle:
            logger.info("foreground rejected: OpenProcess failed for hwnd=0x%x title=%r", hwnd, (title[:80] if title else ""))
            return None, title
        try:
            path_buffer = ctypes.create_unicode_buffer(1024)
            path_length = wintypes.DWORD(len(path_buffer))
            if not _KERNEL32.QueryFullProcessImageNameW(
                process_handle, 0, path_buffer, ctypes.byref(path_length)
            ):
                logger.info("foreground rejected: QueryFullProcessImageNameW failed for hwnd=0x%x title=%r", hwnd, (title[:80] if title else ""))
                return None, title
            app_name = os.path.basename(path_buffer.value)
            if app_name.lower() in _IGNORED_SHELL_PROCESSES and not _is_real_file_explorer_window(hwnd, app_name, class_name):
                logger.info("foreground rejected as shell-only process: hwnd=0x%x class=%s process=%s title=%r", hwnd, class_name or "", app_name, (title[:80] if title else ""))
                return None, None
            logger.info("foreground accepted: hwnd=0x%x class=%s process=%s title=%r", hwnd, class_name or "", app_name, (title[:80] if title else ""))
            return app_name or None, title
        finally:
            _KERNEL32.CloseHandle(process_handle)
    except Exception:  # noqa: BLE001
        logger.exception("foreground detection failed")
        return None, None


def get_window_class_name(hwnd: int) -> str:
    """Return the class name for a window handle."""
    buffer = ctypes.create_unicode_buffer(256)
    try:
        _USER32.GetClassNameW(hwnd, buffer, len(buffer))
    except Exception:  # noqa: BLE001
        return ""
    return buffer.value


def find_desktop_shell_parent() -> int:
    """Find the actual desktop shell surface, preferring a real WorkerW shell over Progman."""
    shell = get_shell_window()
    desktop = get_desktop_window()

    shell_candidates: list[int] = []
    worker_candidates: list[int] = []

    def _enum_cb(hwnd: int, _lparam: int) -> bool:
        if not hwnd or not _USER32.IsWindow(hwnd):
            return True
        class_name = get_window_class_name(hwnd)
        if class_name == "WorkerW":
            worker_candidates.append(hwnd)
        elif class_name in {"Progman", "SHELLDLL_DefView"}:
            shell_candidates.append(hwnd)
        return True

    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(_enum_cb)
    try:
        _USER32.EnumWindows(callback, 0)
    except Exception:  # noqa: BLE001
        logger.debug("EnumWindows failed while finding desktop shell parent", exc_info=True)

    def _window_size(hwnd: int) -> int:
        rect = wintypes.RECT()
        if not _USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return 0
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        return max(0, width * height)

    if worker_candidates:
        worker_candidates.sort(key=_window_size, reverse=True)
        for candidate in worker_candidates:
            if _window_size(candidate) > 0:
                return candidate
        return worker_candidates[0]

    if shell and get_window_class_name(shell) in {"Progman", "WorkerW", "SHELLDLL_DefView"}:
        return shell

    if shell_candidates:
        return shell_candidates[0]

    if desktop:
        return desktop

    return 0


def validate_window_attachment(hwnd: int, parent_hwnd: int) -> bool:
    """Validate that the HWND is a real usable desktop child with sane geometry and visibility."""
    if not hwnd or not parent_hwnd:
        return False

    try:
        if not _USER32.IsWindow(hwnd):
            return False
        if not _USER32.IsWindowVisible(hwnd):
            return False

        parent = _USER32.GetParent(hwnd)
        if parent != parent_hwnd:
            return False

        parent_class = get_window_class_name(parent_hwnd)
        if parent_class not in {"WorkerW", "Progman", "SHELLDLL_DefView"}:
            return False

        rect = wintypes.RECT()
        if not _USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return False

        if not _USER32.MonitorFromWindow(hwnd, 2):
            return False

        style = _USER32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        if style == 0:
            return False

        ex_style = _USER32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if not ex_style:
            return False

        desktop_rect = wintypes.RECT()
        desktop_hwnd = get_desktop_window()
        if desktop_hwnd and _USER32.GetWindowRect(desktop_hwnd, ctypes.byref(desktop_rect)):
            if rect.right > desktop_rect.right or rect.bottom > desktop_rect.bottom:
                return False

        return True
    except Exception:  # noqa: BLE001
        logger.warning("attach_widget_to_desktop validation failed for hwnd=0x%x", hwnd, exc_info=True)
        return False


def attach_widget_to_desktop(hwnd: int) -> bool:
    """Reparent the widget to the desktop shell only if the resulting HWND is valid."""
    if not hwnd:
        logger.warning("attach_widget_to_desktop: invalid hwnd (0)")
        return False

    if desktop_attachment_disabled():
        logger.info("attach_widget_to_desktop: disabled via INSIGHTOS_DISABLE_DESKTOP_ATTACHMENT")
        return False

    target = find_desktop_shell_parent()
    if not target:
        logger.warning("attach_widget_to_desktop: could not determine a valid desktop shell window")
        return False

    try:
        before_style = _USER32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        before_ex = _USER32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        is_visible_before = _USER32.IsWindowVisible(hwnd)
        parent_before = _USER32.GetParent(hwnd)

        logger.debug(
            "attach_widget_to_desktop: hwnd=0x%x, target=0x%x, before: parent=0x%x, visible=%s, style=0x%x, ex=0x%x",
            hwnd, target, parent_before, bool(is_visible_before), before_style or 0, before_ex or 0,
        )

        current_parent = _USER32.GetParent(hwnd)
        if current_parent == target and validate_window_attachment(hwnd, target):
            logger.info("attach_widget_to_desktop: already attached and valid")
            return True
        if current_parent == target and not validate_window_attachment(hwnd, target):
            logger.warning("attach_widget_to_desktop: stale invalid attachment for hwnd=0x%x under target=0x%x; rolling back to top-level", hwnd, target)
            _USER32.SetParent(hwnd, 0)

        res_parent = _USER32.SetParent(hwnd, target)
        if not res_parent:
            logger.warning("attach_widget_to_desktop: SetParent failed (returned NULL)")
            return False

        style = _USER32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        style = style & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        style = style | WS_CHILD | WS_CLIPSIBLINGS | WS_CLIPCHILDREN | WS_VISIBLE
        res_style = _USER32.SetWindowLongPtrW(hwnd, GWL_STYLE, _pack_long_ptr(style))

        ex_style = _USER32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        ex_style = ex_style | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        ex_style = ex_style & ~WS_EX_TRANSPARENT
        res_ex_style = _USER32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, _pack_long_ptr(ex_style))

        res_pos = _USER32.SetWindowPos(
            hwnd, HWND_BOTTOM, 0, 0, 0, 0,
            SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE | SWP_NOSENDCHANGING,
        )

        after_style = _USER32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        after_ex = _USER32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        is_visible_after = _USER32.IsWindowVisible(hwnd)
        parent_after = _USER32.GetParent(hwnd)
        has_valid_geometry = validate_window_attachment(hwnd, target)
        last_error = ctypes.windll.kernel32.GetLastError()

        logger.debug(
            "attach_widget_to_desktop result: parent=0x%x, res_parent=0x%x, res_style=0x%x, res_ex_style=0x%x, res_pos=%s, "
            "after: visible=%s, parent_after=0x%x, style=0x%x, ex=0x%x, valid=%s, last_error=0x%x",
            parent_before,
            int(res_parent) if res_parent else 0,
            int(res_style) if res_style else 0,
            int(res_ex_style) if res_ex_style else 0,
            bool(res_pos),
            bool(is_visible_after),
            parent_after,
            after_style,
            after_ex,
            bool(has_valid_geometry),
            int(last_error),
        )

        if not has_valid_geometry:
            logger.warning("attach_widget_to_desktop: post-attach validation failed for hwnd=0x%x on target=0x%x; restoring top-level window", hwnd, target)
            try:
                _USER32.SetParent(hwnd, 0)
                _USER32.SetWindowLongPtrW(hwnd, GWL_STYLE, _pack_long_ptr(before_style or 0))
                _USER32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, _pack_long_ptr(before_ex or 0))
            except Exception:  # noqa: BLE001
                logger.debug("attach_widget_to_desktop: failed to restore hwnd=0x%x to a top-level window", hwnd, exc_info=True)
            return False

        success = bool(res_parent) and bool(has_valid_geometry)
        logger.info("attach_widget_to_desktop: success=%s (valid=%s target=0x%x)", success, has_valid_geometry, target)
        return success
    except Exception:  # noqa: BLE001
        logger.exception("Exception attaching widget to desktop")
        return False


def set_process_priority_below_normal() -> bool:
    """Best-effort lowering of the current process priority."""
    if sys.platform != "win32":
        return True
    try:
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(handle, 0x00004000)
        return True
    except Exception:  # noqa: BLE001
        logger.warning("Failed to set process priority", exc_info=True)
        return False


def _autostart_command() -> str:
    """Return a GUI-safe command line for launching InsightOS at login.

    In a packaged install, the executable itself is the correct target. In a
    source checkout, we fall back to the interpreter plus the repo entry point.
    """
    executable = os.path.abspath(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{executable}"'

    python_path = Path(executable)
    if python_path.name.lower().startswith("python") and "pythonw" not in python_path.name.lower():
        pythonw_path = python_path.with_name("pythonw.exe")
        if pythonw_path.exists():
            executable = str(pythonw_path)

    entry_point = str(config.APP_ENTRYPOINT)
    return f'"{executable}" "{entry_point}"'


def set_startup_entry(enabled: bool) -> bool:
    """Register or remove the app from the Windows Run key."""
    if sys.platform != "win32":
        return True
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
            if not enabled:
                try:
                    winreg.DeleteValue(key, "InsightOS")
                except FileNotFoundError:
                    pass
                return True
            winreg.SetValueEx(key, "InsightOS", 0, winreg.REG_SZ, _autostart_command())
            return True
    except Exception:  # noqa: BLE001
        logger.warning("Failed to update Windows startup entry", exc_info=True)
        return False
