# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Date range utilities for iterating over date sequences.

This module provides functions for generating date ranges and iterating
over date sequences with various filtering and formatting options.

The module is designed for applications that need to process date ranges
efficiently, such as:
- Data processing pipelines
- Report generation
- Calendar applications
- Time series analysis
- Batch processing systems

Key Features:
- Memory-efficient generator-based iteration
- Flexible date range generation
- Weekend filtering support
- Multiple input format support
- Set operations for date collections

Example Usage:
    import logging

    lg = logging.getLogger(__name__)

    # Iterate over dates from start to today
    start_date = datetime.date(2025, 12, 1)
    for date in iter_dates(start_date):
        lg.info(f"Processing {date}")

    # Skip weekends
    for date in iter_dates(start_date, skip_weekends=True):
        lg.info(f"Business day: {date}")

    # Combine individual dates and ranges
    dates = [datetime.date(2025, 12, 1), datetime.date(2025, 12, 5)]
    ranges = [(datetime.date(2025, 12, 10), datetime.date(2025, 12, 1))]
    all_dates = dates_from_lists(dates, ranges)
    lg.info(f"Total dates: {len(all_dates)}")
"""

import datetime
from collections.abc import Generator
from typing import Any

from .time import date_from_str, date_to_str


def iter_dates(
    start_date: datetime.date,
    delay_hours: int = 0,
    subtract_days: int = 0,
    skip_weekends: bool = False,
) -> Generator[datetime.date, None, None]:
    """
    Iterate over dates from start_date to a calculated end date.

    Generates a sequence of dates starting from the given start_date and
    ending at a calculated end date based on current time with optional
    delays and adjustments. This is useful for processing date ranges
    relative to the current time.

    Args:
        start_date (datetime.date): Starting date for the iteration
        delay_hours (int): Hours to subtract from current time for end date calculation
        subtract_days (int): Additional days to subtract from the end date
        skip_weekends (bool): Whether to skip Saturday and Sunday

    Yields:
        datetime.date: Each date in the range

    Example:
        >>> import logging
        >>> lg = logging.getLogger(__name__)
        >>> start_date = datetime.date(2025, 12, 1)
        >>> for date in iter_dates(start_date, skip_weekends=True):
        ...     lg.info(f"Business day: {date}")
        ...     if date > datetime.date(2025, 12, 5):  # Limit output
        ...         break
        Business day: 2025-12-01
        Business day: 2025-12-02
        Business day: 2025-12-03
        Business day: 2025-12-04
        Business day: 2025-12-05
    """
    ts = datetime.datetime.now().timestamp()
    ts -= delay_hours * 3600
    end = datetime.datetime.fromtimestamp(ts).date()
    delta = datetime.timedelta(days=1)
    end -= datetime.timedelta(days=subtract_days)
    while start_date <= end:
        if not skip_weekends or start_date.weekday() < 5:
            yield start_date
        start_date += delta


def iter_dates_midnight_gmt(
    start_date: datetime.date, subtract_days: int = 0, skip_weekends: bool = False
) -> Generator[datetime.date, None, None]:
    """
    Iterate over dates from start_date to today (GMT midnight).

    Generates a sequence of dates starting from the given start_date and
    ending at today's date (GMT midnight) with optional adjustments.

    Args:
        start_date (datetime.date): Starting date for the iteration
        subtract_days (int): Days to subtract from today for end date calculation
        skip_weekends (bool): Whether to skip Saturday and Sunday

    Yields:
        datetime.date: Each date in the range
    """
    end = datetime.datetime.now().date()
    delta = datetime.timedelta(days=1)
    end -= datetime.timedelta(days=subtract_days)
    while start_date <= end:
        if not skip_weekends or start_date.weekday() < 5:
            yield start_date
        start_date += delta


def dates_from_lists(
    dates_list: list, date_range_list: list = [], strings: bool = True
) -> set[str] | set[datetime.date]:
    """
    Combine individual dates and date ranges into a unified set.

    Takes a list of individual dates and a list of date ranges (pairs of start/end dates)
    and combines them into a single set of dates, with optional string formatting.

    Args:
        dates_list (list): List of individual dates (can be date objects or strings)
        date_range_list (list): List of date range pairs [(start, end), ...]
        strings (bool): Whether to return dates as strings or date objects

    Returns:
        set: Set of dates (as strings or date objects based on strings parameter)
    """
    dates_temp: list[Any] = []
    delta = datetime.timedelta(days=1)

    # Process date ranges
    for pair in date_range_list:
        left, right = pair
        # Convert strings to date objects if needed
        left = date_from_str(left) if isinstance(left, str) else left
        right = date_from_str(right) if isinstance(right, str) else right

        # Add all dates in the range
        while left <= right:
            dates_temp.append(left)
            left += delta

    # Combine with individual dates and remove duplicates
    dates: set[Any] = set(dates_temp).union(set(dates_list))

    # Convert to strings if requested
    if not strings:
        return dates
    return set([date_to_str(d) for d in dates])
