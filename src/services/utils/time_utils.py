"""Time and date helpers shared across InsightOS.

ARCHITECTURE.md §7 notes: "All timestamps are stored in UTC ISO8601.
Conversion to local time happens only in time_utils.py at display time."
This module is therefore the single place where UTC<->local conversion,
duration formatting, and date-bucketing logic lives. No DB access, no UI
imports (§6).
"""

from datetime import datetime, timedelta, timezone


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO8601 string.

    Returns:
        e.g. "2026-07-16T18:21:05.123456+00:00"
    """
    return datetime.now(timezone.utc).isoformat()


def parse_iso(timestamp: str) -> datetime:
    """Parse an ISO8601 string (as stored in SQLite) back into a datetime.

    Args:
        timestamp: An ISO8601 string, assumed UTC if no offset is present.

    Returns:
        A timezone-aware datetime in UTC.
    """
    dt = datetime.fromisoformat(timestamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_local(dt: datetime) -> datetime:
    """Convert a timezone-aware UTC datetime to the machine's local time.

    Args:
        dt: A timezone-aware datetime (typically UTC).

    Returns:
        A timezone-aware datetime converted to local time.
    """
    return dt.astimezone()


def local_date_str(dt: datetime | None = None) -> str:
    """Return the local calendar date (YYYY-MM-DD) for a given UTC datetime.

    This is the value stored in the `date` column of app_sessions,
    idle_periods, and the primary key of daily_summary, so all bucketing
    is based on the user's local day boundary, not UTC midnight.

    Args:
        dt: A timezone-aware UTC datetime. Defaults to now.

    Returns:
        Local date string in "YYYY-MM-DD" format.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    return to_local(dt).strftime("%Y-%m-%d")


def today_str() -> str:
    """Return today's local date as "YYYY-MM-DD".

    Returns:
        Local date string for the current moment.
    """
    return local_date_str()


def yesterday_str() -> str:
    """Return yesterday's local date as "YYYY-MM-DD".

    Returns:
        Local date string for one calendar day before today.
    """
    return days_ago_str(1)


def days_ago_str(days: int) -> str:
    """Return the local date string N days before today.

    Args:
        days: Number of days to subtract from today (0 = today).

    Returns:
        Local date string in "YYYY-MM-DD" format.
    """
    local_today = to_local(datetime.now(timezone.utc)).date()
    target = local_today - timedelta(days=days)
    return target.strftime("%Y-%m-%d")


def date_range_strings(days: int) -> list[str]:
    """Return a list of local date strings for the last N days, oldest first.

    Includes today. E.g. date_range_strings(7) returns 7 date strings
    spanning today and the 6 days before it — used for the "Last 7 Days"
    history view (§12).

    Args:
        days: Number of days in the range, including today.

    Returns:
        List of "YYYY-MM-DD" strings, ordered oldest to newest.
    """
    return [days_ago_str(n) for n in range(days - 1, -1, -1)]


def format_duration(seconds: int) -> str:
    """Format a duration in seconds as a short "Xh Ym" style string.

    Used by the Dashboard and tray tooltip for totals. Examples:
        0        -> "0m"
        45       -> "0m"
        125      -> "2m"
        13320    -> "3h 42m"
        90000    -> "25h 0m"

    Args:
        seconds: Non-negative duration in seconds.

    Returns:
        Human-readable duration string.
    """
    if seconds < 0:
        seconds = 0
    total_minutes = seconds // 60
    hours, minutes = divmod(total_minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_duration_hms(seconds: int) -> str:
    """Format a duration in seconds as "HH:MM:SS", for a live session timer.

    Used by the Desktop Widget's "Current App" running duration (§11).

    Args:
        seconds: Non-negative duration in seconds.

    Returns:
        Zero-padded "HH:MM:SS" string.
    """
    if seconds < 0:
        seconds = 0
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def seconds_between(start_iso: str, end_iso: str) -> int:
    """Compute the whole-second duration between two ISO8601 timestamps.

    Args:
        start_iso: ISO8601 start timestamp.
        end_iso: ISO8601 end timestamp.

    Returns:
        Duration in whole seconds, floored at 0.
    """
    delta = parse_iso(end_iso) - parse_iso(start_iso)
    return max(0, int(delta.total_seconds()))
