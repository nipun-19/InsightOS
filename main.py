"""InsightOS entry point.

Per ARCHITECTURE.md §6, this file owns boot order and shutdown
orchestration ONLY — no business logic, no DB queries. It wires together
core/database.py, core/tracker.py, core/power_events.py, and
ui/system_tray.py in the exact sequence described in §9 (startup) and
§15 (shutdown), and installs the global exception hook from §20.
"""

import sys
import threading

from PySide6.QtWidgets import QApplication

import config
from core import database as db
from core import power_events
from core.tracker import Tracker
from utils.logger import configure_logging, get_logger

logger = get_logger(__name__)

_shutdown_lock = threading.Lock()
_shutdown_started = False


def _set_process_priority() -> None:
    """Best-effort: lower process priority per §14/§19. Windows-only, non-fatal."""
    if not config.PROCESS_PRIORITY_BELOW_NORMAL or sys.platform != "win32":
        return
    try:
        from core import platform_win

        platform_win.set_process_priority_below_normal()
    except Exception:  # noqa: BLE001 — a priority-class failure must never block startup
        logger.warning("Failed to set process priority", exc_info=True)


def _install_exception_hook() -> None:
    """Install a sys.excepthook that logs any unhandled exception (§20).

    Ensures no crash is ever silent, without changing the exit behavior
    for genuinely fatal errors.
    """

    def _hook(exc_type: type, exc_value: BaseException, exc_tb) -> None:
        logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _hook


def boot(app: QApplication, tracker: Tracker) -> "object":
    """Run the startup sequence described in ARCHITECTURE.md §9.

    Args:
        app: The QApplication instance whose event loop will run next.
        tracker: The Tracker instance to start.

    Returns:
        The initialized SystemTray instance (kept alive by main()'s caller).
    """
    from ui.system_tray import SystemTray  # local: UI must not be imported by core (§22 rule 6)

    db.init_db()
    tracker.start()  # internally: reconcile_orphaned_sessions(), log_system_event('boot')

    tray = SystemTray(app, on_exit=lambda: shutdown(app, tracker))
    return tray


def shutdown(app: QApplication, tracker: Tracker) -> None:
    """Run the shutdown sequence described in ARCHITECTURE.md §15.

    Safe to call more than once (e.g. both a user-initiated tray exit and
    an OS shutdown signal arriving in close succession) — only the first
    call executes; subsequent calls are no-ops.

    Args:
        app: The running QApplication instance.
        tracker: The running Tracker instance.

    Returns:
        None.
    """
    global _shutdown_started
    with _shutdown_lock:
        if _shutdown_started:
            return
        _shutdown_started = True

    logger.info("Shutdown sequence starting")
    tracker.stop_polling()

    from utils import time_utils

    now = time_utils.utc_now_iso()
    tracker.close_active_session_and_idle(now)
    db.log_system_event("shutdown")
    db.checkpoint_and_close()
    app.quit()
    logger.info("Shutdown sequence complete")


def main() -> int:
    """Application entry point: configure logging, boot, and run the event loop.

    Returns:
        Process exit code.
    """
    configure_logging()
    _install_exception_hook()
    _set_process_priority()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # closing Dashboard/Widget must never quit (§4)

    tracker = Tracker()
    tray = boot(app, tracker)  # noqa: F841 — must stay referenced for the app's lifetime

    listener = power_events.install(
        app,
        on_sleep=tracker.on_sleep,
        on_wake=tracker.on_wake,
        on_shutdown=lambda: shutdown(app, tracker),
    )  # noqa: F841 — Qt does not keep native event filters alive on its own

    exit_code = app.exec()

    if not _shutdown_started:
        shutdown(app, tracker)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
