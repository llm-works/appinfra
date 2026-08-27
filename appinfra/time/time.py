# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Time utilities for timing, date manipulation, and duration formatting.

This module provides comprehensive time-related utilities including:
- High-precision timing functions using monotonic clock
- Duration formatting with human-readable output
- Date conversion and manipulation functions
- Context managers for timing code execution
- Timestamp conversion utilities

The module is designed for applications that require reliable timing measurements
and flexible date/time manipulation. All timing functions use the monotonic clock
to ensure consistent measurements even when system time changes.

Example Usage:
    import logging

    lg = logging.getLogger(__name__)

    # Basic timing
    start_time = start()
    # ... do work ...
    elapsed = since(start_time)
    lg.info(f"Operation took {since_str(start_time)}")

    # Context manager timing
    with time_it_lg(lg.info, "database query", {"table": "users"}):
        # ... database operation ...

    # Date manipulation
    date_str = "2025-12-25"
    date_obj = date_from_str(date_str)
    timestamp = timestamp_from_date(date_obj, "14:30")

    # Yesterday's date
    yesterday = yesterday()
    lg.info(f"Yesterday was: {date_to_str(yesterday)}")
"""

import contextlib
import datetime
import time
from collections.abc import Callable, Generator
from typing import Any

from .delta import delta_str


def start() -> float:
    """
    Get the current monotonic time for timing measurements.

    Uses the monotonic clock which is not affected by system clock adjustments,
    making it ideal for measuring elapsed time intervals.

    Returns:
        float: Current monotonic time in seconds

    Example:
        >>> import logging
        >>> lg = logging.getLogger(__name__)
        >>> start_time = start()
        >>> # ... do work ...
        >>> elapsed = since(start_time)
        >>> lg.info(f"Work completed in {elapsed:.3f} seconds")
    """
    return time.monotonic()


def since(start_t: float) -> float:
    """
    Calculate elapsed time since a start time.

    Args:
        start_t (float): Start time from time.monotonic() or start()

    Returns:
        float: Elapsed time in seconds

    Example:
        >>> import logging
        >>> lg = logging.getLogger(__name__)
        >>> start_time = start()
        >>> time.sleep(0.1)  # Simulate work
        >>> elapsed = since(start_time)
        >>> lg.info(f"Elapsed: {elapsed:.3f}s")  # Output: Elapsed: 0.100s
    """
    return time.monotonic() - start_t


def since_str(start_t: float, precise: bool = False) -> str:
    """
    Calculate elapsed time since a start time and format as string.

    Args:
        start_t (float): Start time from time.monotonic() or start()
        precise (bool): Whether to show full precision (microseconds, zero-padding)

    Returns:
        str: Formatted elapsed time string

    Format rules for precise=False (default):
        - Durations ≥60s: No fractional, no zero-padding (e.g., "1m10s", "1h1m5s")
        - Seconds < 10: Show 3 decimals ONLY if non-zero (e.g., "1s", "1.001s", "9.123s")
        - Seconds ≥ 10: No fractional (e.g., "10s", "59s")
        - Milliseconds: Fractional if <10ms, integer if ≥10ms
        - Microseconds: Always show (e.g., "123μs")

    Format rules for precise=True:
        - Full precision with microseconds and zero-padding

    Example:
        >>> import logging
        >>> lg = logging.getLogger(__name__)
        >>> start_time = start()
        >>> time.sleep(0.001)  # 1ms
        >>> lg.debug(since_str(start_time))      # Output: "1ms"
        >>> lg.debug(since_str(start_time, precise=True))  # Output: "1.000ms"

        >>> start_time = start()
        >>> time.sleep(70.5)  # 1m 10.5s
        >>> lg.debug(since_str(start_time))      # Output: "1m10s"
    """
    return delta_str(time.monotonic() - start_t, precise)


def date_from_str(s: str) -> datetime.date:
    """
    Convert a date string in YYYY-MM-DD format to a date object.

    Args:
        s (str): Date string in YYYY-MM-DD format

    Returns:
        datetime.date: Date object

    Example:
        date_from_str("2025-12-25") -> datetime.date(2025, 12, 25)
    """
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def date_to_str(d: datetime.date) -> str:
    """
    Convert a date object to a string in YYYY-MM-DD format.

    Args:
        d (datetime.date): Date object

    Returns:
        str: Date string in YYYY-MM-DD format

    Example:
        date_to_str(datetime.date(2025, 12, 25)) -> "2025-12-25"
    """
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"


def date_with_time(date: datetime.date, time: str = "00:00") -> datetime.datetime:
    """
    Combine a date with a time to create a datetime object.

    Args:
        date (datetime.date): Date object
        time (str): Time string in HH:MM format (default: "00:00")

    Returns:
        datetime.datetime: Combined datetime object

    Example:
        date_with_time(datetime.date(2025, 12, 25), "14:30")
        -> datetime.datetime(2025, 12, 25, 14, 30)
    """
    return datetime.datetime.combine(
        date, datetime.time(hour=int(time[:2]), minute=int(time[3:]))
    )


def timestamp_from_date(date: datetime.date, time: str = "12:00") -> float:
    """
    Convert a date (with optional time) to a Unix timestamp.

    Args:
        date (datetime.date): Date object
        time (str): Time string in HH:MM format (default: "12:00")

    Returns:
        float: Unix timestamp
    """
    return date_with_time(date, time).timestamp()


def date_from_timestamp(ts: float) -> datetime.date:
    """
    Convert a Unix timestamp to a date object.

    Args:
        ts (float): Unix timestamp

    Returns:
        datetime.date: Date object
    """
    return datetime.datetime.fromtimestamp(ts).date()


def yesterday() -> datetime.date:
    """
    Get yesterday's date.

    Returns:
        datetime.date: Yesterday's date
    """
    today = datetime.date.today()
    return today - datetime.timedelta(days=1)


@contextlib.contextmanager
def time_it(f: Callable[[float], Any]) -> Generator[None, None, None]:
    """
    Context manager for timing code execution with custom callback.

    Measures the execution time of a code block and calls the provided
    function with the elapsed time. The callback function receives the
    elapsed time in seconds as its only argument.

    Args:
        f: Function to call with elapsed time (in seconds)

    Example:
        >>> import logging
        >>> lg = logging.getLogger(__name__)
        >>> def log_time(elapsed):
        ...     lg.info(f"Operation took {elapsed:.2f} seconds")
        >>>
        >>> with time_it(log_time):
        ...     time.sleep(0.1)
        ...     # Output: Operation took 0.10 seconds

        >>> # Custom timing with multiple operations
        >>> def detailed_timing(elapsed):
        ...     lg.info(f"Database query completed in {elapsed:.3f}s")
        >>>
        >>> with time_it(detailed_timing):
        ...     # Simulate database operation
        ...     time.sleep(0.05)
    """
    start = time.monotonic()
    try:
        yield
    finally:
        f(time.monotonic() - start)


@contextlib.contextmanager
def time_it_lg(
    lg_func: Callable, msg: str, extra: dict = {}
) -> Generator[None, None, None]:
    """
    Context manager for timing code execution with logging.

    Measures the execution time of a code block and logs it using
    the provided logging function with structured data. The elapsed
    time is automatically added to the 'after' field in the extra data.

    Args:
        lg_func: Logging function to call (e.g., logger.info, logger.debug)
        msg (str): Log message to display
        extra (dict): Additional data to include in log (elapsed time added to 'after')

    Example:
        >>> import logging
        >>> logger = logging.getLogger(__name__)
        >>>
        >>> with time_it_lg(logger.info, "database operation", {"table": "users"}):
        ...     # Simulate database query
        ...     time.sleep(0.1)
        ... # Logs: database operation table[users] after[0.100s]

        >>> # With additional context
        >>> with time_it_lg(logger.debug, "file processing",
        ...                 {"file": "data.csv", "size": "1MB"}):
        ...     # Process file
        ...     time.sleep(0.05)
        ... # Logs: file processing file[data.csv] size[1MB] after[0.050s]
    """
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        lg_func(msg, extra={"after": elapsed} | extra)
