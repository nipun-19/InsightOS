"""The Tracker: foreground-app + idle polling loop (ARCHITECTURE.md §8).

This is the only component in the whole application that writes tracked
data (§4). It runs on its own background thread (§16), never imports `ui/`
(§22 rule 6), and delegates every raw OS call to core/platform_win.py.

State machine (§8):
    Starting -> Reconciling -> Polling
    Polling <-> Idle (idle_seconds crosses IDLE_THRESHOLD_SECONDS)
    Polling/Idle -> Paused (on_sleep) -> Polling (on_wake)
    Any state -> Stopped (shutdown)
"""

import threading
import time
from enum import Enum, auto

import config
from core import database as db
from core import platform_win
from utils import time_utils
from utils.logger import get_logger

logger = get_logger(__name__)


class TrackerState(Enum):
    """The Tracker's current lifecycle state, per the §8 state diagram."""

    STARTING = auto()
    POLLING = auto()
    IDLE = auto()
    PAUSED = auto()
    STOPPED = auto()


class Tracker:
    """Owns the polling loop and all session/idle open-close decisions.

    Thread-safety: `_state` and the "paused" flag are only ever mutated
    from the tracker thread itself or via the sleep/wake/stop methods,
    which are safe to call from the Qt main thread because they only set
    a threading.Event / flag that the loop checks each tick — no direct
    database writes happen outside the tracker thread.
    """

    def __init__(self) -> None:
        """Initialize the Tracker in the STARTING state, not yet running."""
        self._state = TrackerState.STARTING
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._active_session_id: int | None = None
        self._active_session_app: str | None = None
        self._active_idle_id: int | None = None
        self._active_idle_start: str | None = None

    @property
    def state(self) -> TrackerState:
        """Return the Tracker's current lifecycle state.

        Returns:
            The current TrackerState.
        """
        return self._state

    def start(self) -> None:
        """Reconcile any orphaned rows, log a boot event, and start polling.

        Must be called once from the main thread during startup (§9). The
        actual polling loop runs on a dedicated background thread.

        Returns:
            None.
        """
        db.reconcile_orphaned_sessions()
        db.log_system_event("boot")
        self._state = TrackerState.POLLING
        self._thread = threading.Thread(target=self._run_loop, name="TrackerThread", daemon=True)
        self._thread.start()
        logger.info("Tracker started")

    def stop_polling(self) -> None:
        """Signal the polling loop to stop and wait for it to exit.

        Called from main.shutdown() (§15), step 1, before closing the
        active session/idle period.

        Returns:
            None.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._state = TrackerState.STOPPED
        logger.info("Tracker polling stopped")

    def close_active_session_and_idle(self, when_iso: str) -> None:
        """Close whatever session or idle period is currently open.

        Called from main.shutdown() (§15), step 2, so no row is left with
        end_time NULL when the process exits cleanly.

        Args:
            when_iso: ISO8601 UTC timestamp to close with.

        Returns:
            None.
        """
        if self._active_session_id is not None:
            db.close_app_session(self._active_session_id, when_iso)
            self._active_session_id = None
            self._active_session_app = None
        if self._active_idle_id is not None:
            db.close_idle_period(self._active_idle_id, when_iso)
            if self._active_idle_start is not None:
                idle_delta = time_utils.seconds_between(self._active_idle_start, when_iso)
                db.upsert_daily_summary(time_utils.today_str(), idle_delta=idle_delta, activity_time=when_iso)
            self._active_idle_id = None
            self._active_idle_start = None

    def on_sleep(self) -> None:
        """Handle an OS sleep signal: pause polling and close open rows.

        Invoked by core/power_events.py. Closing the active session/idle
        period here prevents sleep time from being counted as usage.

        Returns:
            None.
        """
        if self._state in (TrackerState.POLLING, TrackerState.IDLE):
            now = time_utils.utc_now_iso()
            self.close_active_session_and_idle(now)
            self._paused.set()
            self._state = TrackerState.PAUSED
            logger.info("Tracker paused (system sleep)")

    def on_wake(self) -> None:
        """Handle an OS wake signal: resume polling from a clean state.

        Invoked by core/power_events.py. The next tick will open a fresh
        session or idle period as appropriate — no stale state carries over.

        Returns:
            None.
        """
        if self._state == TrackerState.PAUSED:
            self._paused.clear()
            self._state = TrackerState.POLLING
            logger.info("Tracker resumed (system wake)")

    def _run_loop(self) -> None:
        """The polling loop body, executed on the tracker thread."""
        while not self._stop_event.is_set():
            if not self._paused.is_set():
                try:
                    self._tick()
                except Exception:  # noqa: BLE001 — a single bad tick must never kill the loop
                    logger.warning("Tracker tick failed", exc_info=True)
            self._stop_event.wait(config.POLL_INTERVAL_SECONDS)

    def _tick(self) -> None:
        """Perform one polling tick: check idle state, then app switches."""
        idle_seconds = platform_win.get_idle_seconds()
        now = time_utils.utc_now_iso()
        today = time_utils.today_str()

        if idle_seconds >= config.IDLE_THRESHOLD_SECONDS:
            self._enter_idle(now, today)
        else:
            self._exit_idle_if_needed(now)
            self._update_foreground_session(now, today)

    def _enter_idle(self, now: str, today: str) -> None:
        """Close any active app session and ensure an idle period is open."""
        if self._active_session_id is not None:
            db.close_app_session(self._active_session_id, now)
            self._active_session_id = None
            self._active_session_app = None

        if self._active_idle_id is None:
            self._active_idle_id = db.open_idle_period(now, today)
            self._active_idle_start = now
            self._state = TrackerState.IDLE

    def _exit_idle_if_needed(self, now: str) -> None:
        """Close any open idle period and return to the POLLING state."""
        if self._active_idle_id is not None:
            db.close_idle_period(self._active_idle_id, now)
            idle_delta = time_utils.seconds_between(self._active_idle_start, now)
            db.upsert_daily_summary(time_utils.today_str(), idle_delta=idle_delta, activity_time=now)
            self._active_idle_id = None
            self._active_idle_start = None
        self._state = TrackerState.POLLING

    def _update_foreground_session(self, now: str, today: str) -> None:
        """Detect a foreground-app change and open/close sessions accordingly."""
        app_name, window_title = platform_win.get_foreground_app()
        if app_name is None:
            return

        if app_name != self._active_session_app:
            if self._active_session_id is not None:
                db.close_app_session(self._active_session_id, now)
            self._active_session_id = db.open_app_session(app_name, window_title, now, today)
            self._active_session_app = app_name

        db.upsert_daily_summary(today, screen_delta=config.POLL_INTERVAL_SECONDS, activity_time=now)
