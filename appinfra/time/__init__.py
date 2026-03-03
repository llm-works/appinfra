"""Time utilities including scheduling, periodic execution, and duration formatting."""

# Date range utilities
# Ticker exceptions
from appinfra.errors import (
    TickerAPIError,
    TickerConfigError,
    TickerError,
    TickerStateError,
)

from .date_range import dates_from_lists, iter_dates, iter_dates_midnight_gmt

# Duration formatting
from .delta import InvalidDurationError, delta_str, delta_to_secs, validate_duration

# ETA progress tracking
from .eta import ETA

# Scheduler
from .sched import (
    InvalidConfigurationError,
    InvalidTimeFormatError,
    Period,
    Sched,
    SchedulerError,
    UnsupportedPeriodError,
)

# Ticker
from .ticker import Ticker, TickerHandler, TickerMode

# Time utilities
from .time import (
    date_from_str,
    date_from_timestamp,
    date_to_str,
    date_with_time,
    since,
    since_str,
    start,
    time_it,
    time_it_lg,
    timestamp_from_date,
    yesterday,
)

__all__ = [
    # Date range
    "iter_dates",
    "iter_dates_midnight_gmt",
    "dates_from_lists",
    # Duration
    "delta_str",
    "delta_to_secs",
    "validate_duration",
    "InvalidDurationError",
    # ETA
    "ETA",
    # Scheduler
    "Sched",
    "Period",
    "SchedulerError",
    "UnsupportedPeriodError",
    "InvalidTimeFormatError",
    "InvalidConfigurationError",
    # Ticker
    "Ticker",
    "TickerHandler",
    "TickerMode",
    "TickerError",
    "TickerAPIError",
    "TickerStateError",
    "TickerConfigError",
    # Time utilities
    "start",
    "since",
    "since_str",
    "date_from_str",
    "date_to_str",
    "date_with_time",
    "timestamp_from_date",
    "date_from_timestamp",
    "yesterday",
    "time_it",
    "time_it_lg",
]
