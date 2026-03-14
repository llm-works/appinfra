"""
Scheduler for periodic task execution at specific times.

This module provides the Sched class for scheduling tasks to run
at specific times with configurable periods (daily, weekly, etc.).

The scheduler is designed for applications that need to execute
tasks at specific times rather than regular intervals, such as:
- Daily reports at 9:00 AM
- Weekly backups on Sunday at 2:00 AM
- Monthly maintenance on the 1st at midnight
- Hourly data collection at 15 minutes past the hour

Key Features:
- Multiple scheduling periods (daily, weekly, monthly, hourly, minutely)
- Flexible time format parsing
- Comprehensive input validation
- Generator-based execution model
- Context manager support
- Status monitoring and introspection

Example Usage:
    import logging

    lg = logging.getLogger(__name__)

    # Daily at 2:30 PM
    sched = Sched(lg, Period.DAILY, "14:30")

    # Weekly on Monday at 9:00 AM
    sched = Sched(lg, Period.WEEKLY, "09:00", weekday=0)

    # Every hour at 15 minutes past the hour
    sched = Sched(lg, Period.HOURLY, "15")

    # Run the scheduler
    for timestamp in sched.run():
        lg.info(f"Task executed at {timestamp}")
"""

import datetime
import re
import time
from collections.abc import Generator
from enum import Enum
from typing import Any, Self

from ..log import LoggerFactory
from .delta import delta_str


class Period(Enum):
    """
    Supported scheduling periods.

    Defines the available scheduling periods for the Sched class.
    Each period determines how often a task should be executed.

    Values:
        DAILY: Execute once per day at the specified time
        WEEKLY: Execute once per week on the specified weekday at the specified time
        MONTHLY: Execute once per month on the specified day at the specified time
        HOURLY: Execute once per hour at the specified minute offset
        MINUTELY: Execute once per minute at the specified second offset

    Example:
        >>> Period.DAILY.value
        'daily'
        >>> Period.WEEKLY.value
        'weekly'
    """

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    HOURLY = "hourly"
    MINUTELY = "minutely"


class SchedulerError(Exception):
    """Base exception for scheduler errors."""

    pass


class UnsupportedPeriodError(SchedulerError):
    """Raised when an unsupported period is specified."""

    pass


class InvalidTimeFormatError(SchedulerError):
    """Raised when an invalid time format is provided."""

    pass


class InvalidConfigError(SchedulerError):
    """Raised when invalid configuration is provided."""

    pass


# Constants
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
SECONDS_PER_WEEK = 604800
DEFAULT_SLEEP_INTERVAL = 10
DEFAULT_MSG_INTERVAL = 3600

# Time format patterns
TIME_PATTERNS = [
    r"^\d{1,2}:\d{1,2}$",  # H:MM or HH:MM
    r"^\d{1,2}:\d{2}$",  # H:MM
    r"^\d{2}:\d{1,2}$",  # HH:M
]


# Helper functions for Sched


def _validate_logger(lg: Any) -> None:
    """Validate logger parameter."""
    if lg is None:
        raise InvalidConfigError("Logger cannot be None")


def _normalize_period(period: str | Period) -> Period:
    """Normalize period from string or Period enum."""
    if isinstance(period, str):
        try:
            return Period(period.lower())
        except ValueError:
            raise UnsupportedPeriodError(f"Unsupported period: {period}")
    return period


def _validate_weekday(period: Period, weekday: int | None) -> int | None:
    """Validate weekday for weekly scheduling."""
    if period == Period.WEEKLY:
        if weekday is None:
            raise InvalidConfigError("weekday must be specified for weekly scheduling")
        if not 0 <= weekday <= 6:
            raise InvalidConfigError(
                "weekday must be between 0 (Monday) and 6 (Sunday)"
            )
        return weekday
    return None


def _parse_offset(
    when: str, period: Period, min_val: int = 0, max_val: int = 59
) -> tuple[int, int]:
    """Parse offset for hourly/minutely periods."""
    try:
        offset = int(when)
        if not min_val <= offset <= max_val:
            period_name = "Hourly" if period == Period.HOURLY else "Minutely"
            raise InvalidTimeFormatError(
                f"{period_name} offset must be between {min_val} and {max_val}"
            )
        return 0, offset
    except ValueError:
        raise InvalidTimeFormatError(f"Invalid offset format: {when}")


def _parse_hhmm_format(when: str) -> tuple[int, int]:
    """Parse HH:MM format time string."""
    for pattern in TIME_PATTERNS:
        if re.match(pattern, when):
            try:
                parts = when.split(":")
                hour = int(parts[0])
                minute = int(parts[1])

                if not 0 <= hour <= 23:
                    raise InvalidTimeFormatError(
                        f"Hour must be between 0 and 23, got: {hour}"
                    )
                if not 0 <= minute <= 59:
                    raise InvalidTimeFormatError(
                        f"Minute must be between 0 and 59, got: {minute}"
                    )

                return hour, minute
            except (ValueError, IndexError):
                raise InvalidTimeFormatError(f"Invalid time format: {when}")

    raise InvalidTimeFormatError(f"Unsupported time format: {when}")


class Sched:
    """
    Scheduler for periodic task execution at specific times.

    Provides functionality to schedule tasks to run at specific times
    with configurable periods. Supports daily, weekly, monthly, hourly,
    and minutely scheduling.

    Examples:
        # Daily at 2:30 PM
        sched = Sched(logger, Period.DAILY, "14:30")

        # Weekly on Monday at 9:00 AM
        sched = Sched(logger, Period.WEEKLY, "09:00", weekday=0)

        # Every hour at 15 minutes past the hour
        sched = Sched(logger, Period.HOURLY, "15")
    """

    def __init__(
        self,
        lg: Any,
        period: str | Period,
        when: str,
        weekday: int | None = None,
        sleep_interval: int = DEFAULT_SLEEP_INTERVAL,
    ) -> None:
        """
        Initialize the scheduler.

        Args:
            lg: Logger instance for scheduler operations
            period: Scheduling period (string or Period enum)
            when: Time specification (format depends on period)
            weekday: Day of week for weekly scheduling (0=Monday, 6=Sunday)
            sleep_interval: Seconds to sleep between checks in run() method

        Raises:
            InvalidConfigError: If configuration is invalid
            InvalidTimeFormatError: If time format is invalid
            UnsupportedPeriodError: If period is not supported
        """
        _validate_logger(lg)
        self._period = _normalize_period(period)
        self._hour, self._minute = self._parse_time(when, self._period)
        self._weekday = _validate_weekday(self._period, weekday)

        self._next_t: float | None = None
        self._lg = LoggerFactory.derive(lg, ["time", "sched"])
        self._sleep_interval = sleep_interval
        self._running = False

    def _parse_time(self, when: str, period: Period) -> tuple[int, int]:
        """
        Parse time string based on period type.

        Args:
            when: Time specification string
            period: Scheduling period

        Returns:
            Tuple of (hour, minute)

        Raises:
            InvalidTimeFormatError: If time format is invalid
        """
        when = when.strip()

        if period in [Period.HOURLY, Period.MINUTELY]:
            return _parse_offset(when, period)

        return _parse_hhmm_format(when)

    @property
    def period(self) -> Period:
        """
        Get the scheduling period.

        Returns:
            Period: The scheduling period
        """
        return self._period

    @property
    def next_t(self) -> float | None:
        """
        Get the next scheduled execution timestamp.

        Returns:
            float or None: Next execution timestamp or None if not set
        """
        return self._next_t

    @next_t.setter
    def next_t(self, value: float | None) -> None:
        """
        Set the next scheduled execution timestamp.

        Args:
            value: Next execution timestamp or None
        """
        self._next_t = value

    @property
    def lg(self) -> Any:
        """
        Get the logger instance.

        Returns:
            Logger: Logger instance for scheduler operations
        """
        return self._lg

    @property
    def is_running(self) -> bool:
        """
        Check if the scheduler is currently running.

        Returns:
            bool: True if running, False otherwise
        """
        return self._running

    def _setup(self) -> None:
        """
        Set up the next scheduled execution time.

        Calculates the next execution time based on the current time and
        the configured schedule. If the scheduled time has already passed
        for the current period, schedules for the next occurrence.
        """
        now = datetime.datetime.now()

        if self._period == Period.DAILY:
            self._setup_daily(now)
        elif self._period == Period.WEEKLY:
            self._setup_weekly(now)
        elif self._period == Period.MONTHLY:
            self._setup_monthly(now)
        elif self._period == Period.HOURLY:
            self._setup_hourly(now)
        elif self._period == Period.MINUTELY:
            self._setup_minutely(now)
        else:
            raise UnsupportedPeriodError(
                f"Setup not implemented for period: {self._period}"
            )

    def _setup_daily(self, now: datetime.datetime) -> None:
        """Set up daily scheduling."""
        target_time = now.replace(
            hour=self._hour, minute=self._minute, second=0, microsecond=0
        )

        # If time has passed today, schedule for tomorrow
        if now >= target_time:
            target_time += datetime.timedelta(days=1)

        self._next_t = target_time.timestamp()
        self._log_setup(target_time)

    def _setup_weekly(self, now: datetime.datetime) -> None:
        """Set up weekly scheduling."""
        assert self._weekday is not None  # Validated in __init__ for WEEKLY period
        # Calculate days until target weekday
        days_ahead = self._weekday - now.weekday()
        if days_ahead <= 0:  # Target day is this week or next week
            days_ahead += 7

        target_date = now + datetime.timedelta(days=days_ahead)
        target_time = target_date.replace(
            hour=self._hour, minute=self._minute, second=0, microsecond=0
        )

        # If we're on the target day but time has passed, schedule for next week
        if now.weekday() == self._weekday and now >= target_time:
            target_time += datetime.timedelta(days=7)

        self._next_t = target_time.timestamp()
        self._log_setup(target_time)

    def _calculate_next_month(self, now: datetime.datetime) -> datetime.datetime:
        """Calculate next month's target time, handling year rollover."""
        if now.month == 12:
            return now.replace(
                year=now.year + 1,
                month=1,
                day=1,
                hour=self._hour,
                minute=self._minute,
                second=0,
                microsecond=0,
            )
        else:
            return now.replace(
                month=now.month + 1,
                day=1,
                hour=self._hour,
                minute=self._minute,
                second=0,
                microsecond=0,
            )

    def _setup_monthly(self, now: datetime.datetime) -> None:
        """Set up monthly scheduling."""
        try:
            next_month = self._calculate_next_month(now)
            target_time = now.replace(
                day=1, hour=self._hour, minute=self._minute, second=0, microsecond=0
            )

            # Schedule for next month if time has passed, otherwise this month
            if now >= target_time:
                self._next_t = next_month.timestamp()
            else:
                self._next_t = target_time.timestamp()

            self._log_setup(datetime.datetime.fromtimestamp(self._next_t))
        except ValueError:
            # Handle edge cases like Feb 31st
            self._setup_daily(now)  # Fallback to daily

    def _setup_hourly(self, now: datetime.datetime) -> None:
        """Set up hourly scheduling."""
        target_time = now.replace(minute=self._minute, second=0, microsecond=0)

        # If time has passed this hour, schedule for next hour
        if now >= target_time:
            target_time += datetime.timedelta(hours=1)

        self._next_t = target_time.timestamp()
        self._log_setup(target_time)

    def _setup_minutely(self, now: datetime.datetime) -> None:
        """Set up minutely scheduling."""
        target_time = now.replace(second=self._minute, microsecond=0)

        # If time has passed this minute, schedule for next minute
        if now >= target_time:
            target_time += datetime.timedelta(minutes=1)

        self._next_t = target_time.timestamp()
        self._log_setup(target_time)

    def _log_setup(self, target_time: datetime.datetime) -> None:
        """Log scheduler setup information."""
        diff = (target_time - datetime.datetime.now()).total_seconds()
        self.lg.info(
            "scheduler configured",
            extra={
                "period": self._period.value,
                "next": target_time.isoformat(),
                "in": delta_str(diff, precise=False),
            },
        )

    def sync(self, instant: bool = False) -> tuple[bool, float]:
        """
        Check if it's time to execute the scheduled task.

        Compares current time with the next scheduled execution time and
        updates the schedule if the task should be triggered.

        Args:
            instant: Whether to trigger immediately on first call

        Returns:
            tuple: (triggered, delay) where triggered is bool and delay is seconds until next execution

        Raises:
            UnsupportedPeriodError: If period is not supported
        """
        now = time.time()

        if self.next_t is None:
            self._setup()
            assert self.next_t is not None  # _setup() always sets next_t
            if instant:
                return True, self.next_t - now

        if now >= self.next_t:
            # Schedule next execution
            self._schedule_next()
            self.lg.info(
                "scheduler triggered",
                extra={
                    "period": self._period.value,
                    "next": datetime.datetime.fromtimestamp(self.next_t).isoformat(),
                },
            )
            return True, self.next_t - now

        return False, self.next_t - now

    def _schedule_next(self) -> None:
        """Schedule the next execution based on period."""
        assert self.next_t is not None  # Always set by sync() before calling this
        if self._period == Period.DAILY:
            self.next_t += SECONDS_PER_DAY
        elif self._period == Period.WEEKLY:
            self.next_t += SECONDS_PER_WEEK
        elif self._period == Period.MONTHLY:
            # Approximate month as 30 days
            self.next_t += SECONDS_PER_DAY * 30
        elif self._period == Period.HOURLY:
            self.next_t += SECONDS_PER_HOUR
        elif self._period == Period.MINUTELY:
            self.next_t += SECONDS_PER_MINUTE
        else:
            raise UnsupportedPeriodError(
                f"Next scheduling not implemented for period: {self._period}"
            )

    def _log_scheduler_status(self, delay: float) -> None:
        """Log periodic scheduler status."""
        self.lg.debug(
            "waiting for next trigger",
            extra={
                "period": self._period.value,
                "in": delta_str(delay, precise=False),
                "next": (
                    datetime.datetime.fromtimestamp(self.next_t).isoformat()
                    if self.next_t
                    else None
                ),
            },
        )

    def run(
        self, msg_intvl_secs: int = DEFAULT_MSG_INTERVAL, instant: bool = False
    ) -> Generator[float, None, None]:
        """
        Run the scheduler in a continuous loop.

        Continuously monitors the schedule and yields timestamps when
        the scheduled task should be executed. Provides periodic logging
        of wait times.

        Args:
            msg_intvl_secs: Interval in seconds between status messages
            instant: Whether to trigger immediately on first call

        Yields:
            float: Timestamp when the scheduled task should be executed

        Example:
            >>> from appinfra.time.sched import Sched, Period
            >>>
            >>> sched = Sched(logger, Period.DAILY, "09:00")
            >>> for timestamp in sched.run():
            ...     # Runs daily at 9:00 AM
            ...     generate_report()
            ...     send_notification()
            >>>
            >>> # With context manager for graceful shutdown:
            >>> with Sched(logger, Period.HOURLY, "30") as sched:
            ...     for timestamp in sched.run():
            ...         collect_metrics()
        """
        self._running = True
        last_t = time.time()

        try:
            while self._running:
                triggered, delay = self.sync(instant)
                now = time.time()

                if triggered:
                    yield now

                # Log status periodically
                if last_t is None or now - last_t > msg_intvl_secs:
                    self._log_scheduler_status(delay)
                    last_t = now

                # Sleep for configured interval before checking again
                time.sleep(self._sleep_interval)
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self._running = False
        self.lg.info("scheduler stopped")

    def get_status(self) -> dict:
        """
        Get current scheduler status.

        Returns:
            dict: Status information including next execution time, period, etc.
        """
        return {
            "period": self._period.value,
            "next_execution": (
                datetime.datetime.fromtimestamp(self.next_t).isoformat()
                if self.next_t
                else None
            ),
            "is_running": self._running,
            "sleep_interval": self._sleep_interval,
            "weekday": self._weekday if self._period == Period.WEEKLY else None,
        }

    def __enter__(self) -> Self:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.stop()

    def __repr__(self) -> str:
        """String representation of the scheduler."""
        return (
            f"Sched(period={self._period.value}, "
            f"time={self._hour:02d}:{self._minute:02d}, "
            f"next_t={self.next_t}, "
            f"running={self._running})"
        )
