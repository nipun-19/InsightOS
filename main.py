# main.py
"""InsightOS entry point.

Per ARCHITECTURE.md §6, this file owns boot order and shutdown
orchestration ONLY — no business logic, no DB queries. It wires together
core/database.py, core/tracker.py, core/power_events.py, and
ui/system_tray.py in the exact sequence described in §9 (startup) and
§15 (shutdown), and installs the global exception hook from §20.
"""

import os
import signal
import sys
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from src import config
from src.core import power_events
from src.core.tracker import Tracker
from src.utils import settings_store
from src.utils.logger import configure_logging, get_logger
from src.core import database as db

config.resolve_user_data_dir()
config.resolve_app_resource_root()
logger = get_logger(__name__)

_shutdown_lock = threading.Lock()
_shutdown_started = False
_shutdown_event = threading.Event()  # Signals that shutdown was requested (e.g., via Ctrl+C)


def _log_startup_step(message: str) -> None:
    """Emit a startup message through the production logger."""
    logger.info(message)


def _install_signal_handlers(app: QApplication) -> None:
    """Install handlers for SIGINT (Ctrl+C) and SIGTERM to trigger clean shutdown.

    On Windows, Qt's event loop may intercept signals. We use a timer-based
    polling approach and also install a signal handler that sets an event.
    """
    if sys.platform == "win32":
        # On Windows, signal handling is tricky with Qt GUI apps
        # We'll use a hybrid approach: signal handler + socket notifier for SIGINT
        import signal as signal_module

        def _signal_handler(signum: int, frame) -> None:
            logger.info("Received signal %d, requesting shutdown", signum)
            _shutdown_event.set()

        signal_module.signal(signal_module.SIGINT, _signal_handler)
        signal_module.signal(signal_module.SIGTERM, _signal_handler)
        
        # Also set up a way to break out of exec() from outside
        # This is a workaround for Qt on Windows not properly handling Ctrl+C
        import ctypes
        def _windows_ctrl_handler(event):
            if event == 0:  # CTRL_C_EVENT
                logger.info("Windows CTRL_C detected, requesting shutdown")
                _shutdown_event.set()
                return True
            return False
        
        try:
            # Register Windows console control handler
            kernel32 = ctypes.windll.kernel32
            SetConsoleCtrlHandler = kernel32.SetConsoleCtrlHandler
            SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, ctypes.c_bool]
            SetConsoleCtrlHandler.restype = ctypes.c_bool
            
            # We can't directly use the Python callback, but we set the SIGINT handler above
            # which should work in most cases
        except Exception:
            logger.debug("Failed to set Windows console control handler", exc_info=True)
    else:
        # Unix-like signal handling
        import signal as signal_module
        
        def _signal_handler(signum: int, frame) -> None:
            logger.info("Received signal %d, requesting shutdown", signum)
            _shutdown_event.set()

        signal_module.signal(signal_module.SIGINT, _signal_handler)
        signal_module.signal(signal_module.SIGTERM, _signal_handler)


def _set_process_priority() -> None:
    """Best-effort: lower process priority per §14/§19. Windows-only, non-fatal."""
    if sys.platform != "win32":
        return

    priority_setting = getattr(config, "PROCESS_PRIORITY_BELOW_NORMAL", None)
    if priority_setting is None:
        priority_setting = getattr(config, "PROCESS_PRIORITY_CLASS", None)

    if not priority_setting:
        return

    if str(priority_setting).upper() != "BELOW_NORMAL":
        return

    try:
        from src.core import platform_win

        platform_win.set_process_priority_below_normal()
    except Exception:  # noqa: BLE001 — a priority-class failure must never block startup
        logger.warning("Failed to set process priority", exc_info=True)


def _sync_autostart_from_settings() -> None:
    """Reconcile the current user's Run entry with the saved opt-in setting."""
    if sys.platform != "win32":
        return

    from src.core import platform_win

    enabled = bool(settings_store.get_value("widget_auto_start"))
    if not platform_win.set_startup_entry(enabled):
        logger.warning("Failed to apply Windows startup registration")


def _install_exception_hook() -> None:
    """Install a sys.excepthook that logs any unhandled exception (§20).

    Ensures no crash is ever silent, without changing the exit behavior
    for genuinely fatal errors.
    """

    def _hook(exc_type: type, exc_value: BaseException, exc_tb) -> None:
        logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _hook


def _acquire_single_instance() -> bool:
    """Acquire an exclusive lock to prevent multiple instances.
    
    On Windows, uses a lock file with PID validation.
    On Unix, would use similar approach.
    
    Returns True if this instance acquired the lock, False otherwise.
    """
    lock_path = str(config.LOCK_FILE_PATH)
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)

    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r", encoding="utf-8") as handle:
                pid_text = handle.read().strip()
            if pid_text.isdigit():
                pid = int(pid_text)
                # Try to detect if process is still alive
                if sys.platform == "win32":
                    # On Windows, check if process is running using tasklist or similar
                    try:
                        import subprocess
                        result = subprocess.run(
                            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                            capture_output=True,
                            text=True,
                            timeout=2
                        )
                        # If process found, another instance is running
                        if str(pid) in result.stdout:
                            logger.info("Another InsightOS instance (PID %s) is already running", pid)
                            return False
                    except Exception:  # noqa: BLE001 — tasklist check failed, assume stale lock
                        logger.debug("tasklist check failed, removing stale lock", exc_info=True)
                        try:
                            os.remove(lock_path)
                        except OSError:
                            pass
                else:
                    # On Unix-like systems, use os.kill with signal 0
                    try:
                        os.kill(pid, 0)
                        # If we reach here, process is running
                        logger.info("Another InsightOS instance (PID %s) is already running", pid)
                        return False
                    except ProcessLookupError:
                        # Process doesn't exist, remove stale lock
                        logger.debug("Process %s no longer exists, removing stale lock", pid)
                        try:
                            os.remove(lock_path)
                        except OSError:
                            pass
                    except PermissionError:
                        # Process exists but we can't signal it (different user)
                        logger.info("Another InsightOS instance (PID %s) exists (permission denied)", pid)
                        return False
        except (OSError, ValueError):
            # Failed to read lock file, assume stale and overwrite
            logger.debug("Failed to read or parse lock file", exc_info=True)

    # Write our PID to the lock file
    try:
        with open(lock_path, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        logger.debug("Acquired single-instance lock (PID %s)", os.getpid())
        return True
    except OSError as exc:
        logger.error("Failed to acquire single-instance lock: %s", exc)
        return False


def _release_single_instance() -> None:
    lock_path = str(config.LOCK_FILE_PATH)
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except OSError:
        pass


def boot(app: QApplication, tracker: Tracker) -> "object":
    """Run the startup sequence described in ARCHITECTURE.md §9."""
    from src.ui.system_tray import SystemTray  # local: UI must not be imported by core (§22 rule 6)
    from src.ui.desktop_widget import DesktopWidget
    from src.ui.startup_state import StartupStateStore
    from src.utils import settings_store

    try:
        _log_startup_step("Loading database...")
        logger.info("Database path: %s", config.DATABASE_PATH)
        db.init_db()

        _log_startup_step("Creating tracker...")
        logger.info("Tracker startup: state=%s database=%s", tracker.state, config.DATABASE_PATH)
        tracker.start()
        _log_startup_step("Created tracker")

        _log_startup_step("Creating widget...")
        widget = DesktopWidget(tracker)
        app.desktop_widget = widget
        widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        _log_startup_step("Created widget")

        state_store = StartupStateStore()
        widget_state = state_store.restore_widget()
        if not widget_state.get("visible", True):
            widget.hide()
            settings_store.set_value("widget_visible", False)

        _log_startup_step("Creating tray...")
        tray = SystemTray(app, on_exit=lambda: shutdown(app, tracker))
        app.tray = tray
        _log_startup_step("Created tray")

        _log_startup_step("Creating dashboard...")
        from src.ui.dashboard.dashboard_window import DashboardWindow

        dashboard = DashboardWindow(tracker=tracker)
        dashboard.hide()
        app.dashboard_window = dashboard
        _log_startup_step("Created dashboard")

        _log_startup_step("Showing widget...")
        if widget_state.get("visible", True):
            widget.show()
        _log_startup_step("Shown widget")

        _log_startup_step("Showing tray...")
        tray.setVisible(True)
        _log_startup_step("Shown tray")
        return tray
    except Exception:
        logger.exception("Startup failed during boot sequence")
        raise


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

    from src.ui.desktop_widget import DesktopWidget
    from src.ui.startup_state import StartupStateStore
    from src.utils import time_utils

    state_store = StartupStateStore()
    if hasattr(app, "desktop_widget"):
        widget = app.desktop_widget
        if isinstance(widget, DesktopWidget):
            state_store.remember_widget((widget.x(), widget.y(), widget.width(), widget.height()), widget.isVisible(), widget._compact_mode, widget.windowOpacity())

    try:
        from src.ui.dashboard.dashboard_window import DashboardWindow
        for top_level in app.topLevelWidgets():
            if isinstance(top_level, DashboardWindow):
                state_store.remember_window(top_level.windowTitle(), (top_level.x(), top_level.y(), top_level.width(), top_level.height()))
    except Exception:  # noqa: BLE001
        logger.debug("Failed to persist dashboard geometry", exc_info=True)

    now = time_utils.utc_now_iso()
    tracker.close_active_session_and_idle(now)
    db.log_system_event("shutdown")
    db.checkpoint_and_close()
    _release_single_instance()
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

    _log_startup_step("Creating QApplication...")
    app = QApplication(sys.argv)
    app.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    app.setQuitOnLastWindowClosed(False)
    _log_startup_step("Created QApplication")
    
    # Install signal handlers after QApplication is created
    _install_signal_handlers(app)
    _log_startup_step("Installed signal handlers for Ctrl+C")

    if not _acquire_single_instance():
        try:
            from src.ui.toasts import show_toast
            show_toast("InsightOS is already running", "The existing instance is already tracking in the background.")
        except Exception:  # noqa: BLE001
            logger.warning("Failed to display already-running toast", exc_info=True)
        return 0
    _log_startup_step("Creating Tracker...")
    tracker = Tracker()
    _log_startup_step("Created Tracker")
    tray = boot(app, tracker)  # noqa: F841 — must stay referenced for the app's lifetime

    _sync_autostart_from_settings()

    listener = power_events.install(
        app,
        on_sleep=tracker.on_sleep,
        on_wake=tracker.on_wake,
        on_shutdown=lambda: shutdown(app, tracker),
    )  # noqa: F841 — Qt does not keep native event filters alive on its own

    # Install a timer that checks if a shutdown was requested (e.g., via Ctrl+C signal handler)
    def _check_shutdown_request() -> None:
        if _shutdown_event.is_set():
            logger.info("Shutdown requested via signal, initiating shutdown sequence")
            shutdown(app, tracker)

    shutdown_check_timer = QTimer()
    shutdown_check_timer.setInterval(100)  # Check every 100ms for shutdown request
    shutdown_check_timer.timeout.connect(_check_shutdown_request)
    shutdown_check_timer.start()
    
    # Keep timer alive for the lifetime of the app
    app.shutdown_check_timer = shutdown_check_timer

    _log_startup_step("Entering app.exec()")
    exit_code = app.exec()
    _log_startup_step("Exited app.exec()")

    if not _shutdown_started:
        shutdown(app, tracker)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())