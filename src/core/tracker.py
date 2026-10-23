# tracker.py
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
from datetime import timedelta
from enum import Enum, auto

from src import config
from src.core import database as db
from src.core import platform_win
from src.utils import time_utils
from src.utils.logger import get_logger

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
        self._active_session_elapsed = 0.0
        self._active_idle_id: int | None = None
        self._active_idle_start: str | None = None
        self._pending_screen_seconds = 0.0
        self._pending_idle_seconds = 0
        self._last_summary_flush = time.monotonic()
        self._last_tick_monotonic = time.monotonic()
        self._last_tick_wall_iso: str | None = None
        self._pending_summary_date: str | None = None
        self._pending_summary_lock = threading.Lock()

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
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Tracker start requested while already running; ignoring duplicate startup")
            return

        self._stop_event.clear()
        self._paused.clear()
        db.reconcile_orphaned_sessions()
        db.log_system_event("boot")
        self._last_tick_monotonic = time.monotonic()
        self._last_summary_flush = self._last_tick_monotonic
        self._last_tick_wall_iso = time_utils.utc_now_iso()
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
        """Close whatever session or idle period is currently open."""
        if self._active_session_id is not None and self._last_tick_wall_iso is not None:
            final_elapsed = max(0.0, time.monotonic() - self._last_tick_monotonic)
            if final_elapsed:
                self._active_session_elapsed += final_elapsed
                self._queue_active_summary(
                    final_elapsed,
                    self._last_tick_wall_iso,
                    when_iso,
                    time_utils.today_str(),
                )
        if self._active_session_id is not None:
            db.close_app_session(
                self._active_session_id,
                when_iso,
                duration_seconds=int(self._active_session_elapsed),
            )
            self._active_session_id = None
            self._active_session_app = None
            self._active_session_elapsed = 0.0
        if self._active_idle_id is not None:
            db.close_idle_period(self._active_idle_id, when_iso)
            if self._active_idle_start is not None:
                idle_delta = time_utils.seconds_between(self._active_idle_start, when_iso)
                self._queue_summary_update(idle_delta=idle_delta, summary_date=time_utils.today_str())
            self._active_idle_id = None
            self._active_idle_start = None
        self._flush_pending_summary(when_iso, time_utils.today_str())

    def on_sleep(self) -> None:
        """Handle an OS sleep signal: pause polling and close open rows."""
        if self._state in (TrackerState.POLLING, TrackerState.IDLE):
            now = time_utils.utc_now_iso()
            self.close_active_session_and_idle(now)
            self._last_tick_monotonic = time.monotonic()
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
            self._last_tick_monotonic = time.monotonic()
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
        tick_monotonic = time.monotonic()
        elapsed_seconds = max(0.0, tick_monotonic - self._last_tick_monotonic)
        self._last_tick_monotonic = tick_monotonic
        idle_seconds = platform_win.get_idle_seconds()
        now = time_utils.utc_now_iso()
        today = time_utils.today_str()
        previous_wall_iso = self._last_tick_wall_iso
        self._last_tick_wall_iso = now
        logger.info("tracker tick: idle_seconds=%s elapsed_seconds=%.2f last_app=%s", idle_seconds, elapsed_seconds, self._active_session_app)

        if idle_seconds >= config.IDLE_THRESHOLD_SECONDS:
            if self._active_session_id is not None:
                self._active_session_elapsed += max(0.0, elapsed_seconds)
            self._enter_idle(now, today)
        else:
            self._exit_idle_if_needed(now)
            if self._update_foreground_session(now, today, elapsed_seconds):
                self._queue_active_summary(elapsed_seconds, previous_wall_iso, now, today)

        if tick_monotonic - self._last_summary_flush >= max(5.0, config.POLL_INTERVAL_SECONDS * 5):
            self._flush_pending_summary(now, today)

    def _enter_idle(self, now: str, today: str) -> None:
        """Close any active app session and ensure an idle period is open."""
        if self._active_session_id is not None:
            db.close_app_session(
                self._active_session_id,
                now,
                duration_seconds=int(self._active_session_elapsed),
            )
            self._active_session_id = None
            self._active_session_app = None
            self._active_session_elapsed = 0.0

        if self._active_idle_id is None:
            self._active_idle_id = db.open_idle_period(now, today)
            self._active_idle_start = now
            self._state = TrackerState.IDLE

    def _exit_idle_if_needed(self, now: str) -> None:
        """Close any open idle period and return to the POLLING state."""
        if self._active_idle_id is not None:
            db.close_idle_period(self._active_idle_id, now)
            idle_delta = time_utils.seconds_between(self._active_idle_start, now)
            self._queue_summary_update(idle_delta=idle_delta, summary_date=time_utils.today_str())
            self._active_idle_id = None
            self._active_idle_start = None
        self._state = TrackerState.POLLING

    def _queue_summary_update(
        self,
        *,
        screen_delta: float = 0,
        idle_delta: int = 0,
        summary_date: str | None = None,
    ) -> None:
        with self._pending_summary_lock:
            if summary_date is not None and self._pending_summary_date is None:
                self._pending_summary_date = summary_date
            self._pending_screen_seconds += max(0, screen_delta)
            self._pending_idle_seconds += max(0, idle_delta)

    def _queue_active_summary(
        self,
        elapsed_seconds: float,
        previous_wall_iso: str | None,
        now_iso: str,
        today: str,
    ) -> None:
        if previous_wall_iso is None:
            self._queue_summary_update(screen_delta=elapsed_seconds, summary_date=today)
            return

        previous_local = time_utils.to_local(time_utils.parse_iso(previous_wall_iso))
        current_local = time_utils.to_local(time_utils.parse_iso(now_iso))
        wall_seconds = (current_local - previous_local).total_seconds()
        if current_local.date() <= previous_local.date() or wall_seconds <= 0 or wall_seconds > 86400:
            self._queue_summary_update(screen_delta=elapsed_seconds, summary_date=today)
            return

        previous_date = previous_local.strftime("%Y-%m-%d")
        midnight = (previous_local + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        seconds_to_midnight = (midnight - previous_local).total_seconds()
        before_midnight = elapsed_seconds * max(0.0, min(1.0, seconds_to_midnight / wall_seconds))
        after_midnight = max(0.0, elapsed_seconds - before_midnight)
        self._queue_summary_update(screen_delta=before_midnight, summary_date=previous_date)
        self._flush_pending_summary(now_iso, previous_date, rollover=True)
        self._queue_summary_update(screen_delta=after_midnight, summary_date=today)

    def _flush_pending_summary(self, activity_time: str, today: str, rollover: bool = False) -> None:
        with self._pending_summary_lock:
            if not self._pending_screen_seconds and not self._pending_idle_seconds:
                return
            screen_seconds = int(self._pending_screen_seconds)
            idle_seconds = int(self._pending_idle_seconds)
            if not screen_seconds and not idle_seconds:
                if rollover:
                    self._pending_screen_seconds = 0.0
                    self._pending_idle_seconds = 0
                    self._pending_summary_date = None
                return
            db.upsert_daily_summary(
                self._pending_summary_date or today,
                screen_delta=screen_seconds,
                idle_delta=idle_seconds,
                activity_time=activity_time,
            )
            self._pending_screen_seconds = 0.0 if rollover else self._pending_screen_seconds - screen_seconds
            self._pending_idle_seconds -= idle_seconds
            if rollover or (not self._pending_screen_seconds and not self._pending_idle_seconds):
                self._pending_summary_date = None
            self._last_summary_flush = time.monotonic()

    def today_screen_total_snapshot(self, date: str) -> float:
        """Return persisted and unflushed screen time for ``date`` as one consistent snapshot."""
        with self._pending_summary_lock:
            summary = db.get_today_summary(date)
            pending_seconds = (
                self._pending_screen_seconds
                if self._pending_summary_date == date
                else 0.0
            )
            return summary.total_screen_seconds + max(0.0, pending_seconds)

    def current_session_snapshot(self) -> tuple[str | None, float]:
        """Return the current application and monotonic elapsed time for read-only consumers."""
        return self._active_session_app, self._active_session_elapsed

    def _update_foreground_session(self, now: str, today: str, elapsed_seconds: float) -> bool:
        """Detect a foreground-app change and open/close sessions accordingly."""
        app_name, window_title = platform_win.get_foreground_app()
        if app_name is None:
            logger.debug("tracker: no foreground app resolved at %s", now)
            return False

        if app_name != self._active_session_app:
            if self._active_session_id is not None:
                db.close_app_session(
                    self._active_session_id,
                    now,
                    duration_seconds=int(self._active_session_elapsed),
                )
                logger.info("tracker: session switch from %s to %s at %s", self._active_session_app, app_name, now)
            self._active_session_id = db.open_app_session(app_name, window_title, now, today)
            self._active_session_app = app_name
            self._active_session_elapsed = 0.0
            logger.info("tracker: started session app=%s title=%r at %s", app_name, (window_title[:80] if window_title else None), now)
        self._active_session_elapsed += max(0.0, elapsed_seconds)
        return True
