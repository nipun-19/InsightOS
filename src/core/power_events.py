"""Windows lifecycle hooks used by the application bootstrap."""

from __future__ import annotations

import ctypes
import sys
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QObject
from PySide6.QtWidgets import QApplication

from src.utils.logger import get_logger

logger = get_logger(__name__)

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


class _PowerEventFilter(QAbstractNativeEventFilter):
    """Translate Windows power/session notifications into tracker callbacks."""

    def __init__(
        self,
        on_sleep: Callable[[], None] | None = None,
        on_wake: Callable[[], None] | None = None,
        on_shutdown: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_sleep = on_sleep
        self._on_wake = on_wake
        self._on_shutdown = on_shutdown

    def nativeEventFilter(self, eventType: str, message: int) -> tuple[bool, int]:
        if sys.platform != "win32":
            return False, 0
        try:
            if eventType != "windows_generic_MSG" or not isinstance(message, int):
                return False, 0
            if message == 0:
                return False, 0
            msg = ctypes.wintypes.MSG.from_address(message)
            if msg.message == WM_POWERBROADCAST:
                if msg.wParam in (PBT_APMSUSPEND, PBT_APMRESUMECRITICAL):
                    if self._on_sleep is not None:
                        self._on_sleep()
                elif msg.wParam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                    if self._on_wake is not None:
                        self._on_wake()
            elif msg.message == WM_QUERYENDSESSION:
                return False, 1
            elif msg.message == WM_ENDSESSION:
                if self._on_shutdown is not None:
                    self._on_shutdown()
            elif msg.message == WM_WTSSESSION_CHANGE and msg.wParam in (WTS_SESSION_LOGON, WTS_SESSION_LOGOFF):
                if self._on_wake is not None:
                    self._on_wake()
        except Exception:  # noqa: BLE001
            return False, 0


def install(
    app: QApplication,
    on_sleep: Callable[[], None] | None = None,
    on_wake: Callable[[], None] | None = None,
    on_shutdown: Callable[[], None] | None = None,
) -> object:
    """Register lightweight callbacks for system power lifecycle events."""
    if sys.platform != "win32":
        return object()
    filter_instance = _PowerEventFilter(on_sleep=on_sleep, on_wake=on_wake, on_shutdown=on_shutdown)
    app.installNativeEventFilter(filter_instance)
    return filter_instance
