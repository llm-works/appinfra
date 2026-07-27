# Time Utilities Package

The `infra/time` package provides comprehensive time-related utilities for applications that require reliable timing measurements, periodic task execution, and flexible date/time manipulation.

## Overview

This package consists of five main modules:

- **`time.py`** - Core timing and date utilities
- **`ticker.py`** - Periodic task execution system
- **`sched.py`** - Scheduled task execution at specific times
- **`delta.py`** - Duration formatting utilities
- **`date_range.py`** - Date range iteration utilities

## Quick Start

```python
from appinfra.time import (
    start,
    since,
    since_str,
    Ticker,
    TickerHandler,
    Sched,
    Period,
    delta_str,
)

# Basic timing
start_time = start()
# ... do work ...
elapsed = since(start_time)
print(f"Operation took {since_str(start_time)}")


# Periodic task execution
class MyHandler(TickerHandler):
    def ticker_tick(self):
        print("Periodic task executed")


ticker = Ticker(MyHandler(), secs=5)
ticker.run()

# Scheduled execution
sched = Sched(logger, Period.DAILY, "14:30")
for timestamp in sched.run():
    print(f"Task executed at {timestamp}")
```

## Module Details

### time.py - Core Time Utilities

Provides high-precision timing functions and date manipulation utilities.

**Key Functions:**
- `start()` - Get current monotonic time
- `since(start_t)` - Calculate elapsed time
- `since_str(start_t, precise=False)` - Format elapsed time as string
- `date_from_str(s)` - Convert date string to date object
- `date_to_str(d)` - Convert date object to string
- `time_it(f)` - Context manager for timing with custom callback
- `time_it_lg(lg_func, msg, extra={})` - Context manager for timing with logging

**Example:**
```python
from appinfra.time import start, since_str, time_it_lg

# Basic timing
start_time = start()
time.sleep(0.1)
print(f"Elapsed: {since_str(start_time)}")

# Context manager timing
with time_it_lg(logger.info, "database query", {"table": "users"}):
    # Database operation
    pass
```

### ticker.py - Periodic Task Execution

Provides a flexible system for periodic task execution with both scheduled and continuous modes.

**Key Classes:**
- `TickerHandler` - Interface for ticker-aware objects
- `Ticker` - Main ticker implementation

**Example:**
```python
from appinfra.time import Ticker, TickerHandler


class HealthChecker(TickerHandler):
    def ticker_start(self, *args, **kwargs):
        print("Health checking started")

    def ticker_tick(self):
        print("Checking system health...")

    def ticker_stop(self):
        print("Health checking stopped")


# Scheduled execution (every 10 seconds)
ticker = Ticker(HealthChecker(), secs=10)
ticker.run()

# Continuous execution
ticker = Ticker(HealthChecker())
ticker.run()
```

### sched.py - Scheduled Task Execution

Provides scheduling for tasks to run at specific times with configurable periods.

**Key Classes:**
- `Sched` - Main scheduler implementation
- `Period` - Enum for scheduling periods

**Supported Periods:**
- `DAILY` - Execute once per day
- `WEEKLY` - Execute once per week on specified weekday
- `MONTHLY` - Execute once per month
- `HOURLY` - Execute once per hour at specified minute
- `MINUTELY` - Execute once per minute at specified second

**Example:**
```python
from appinfra.time import Sched, Period

# Daily at 2:30 PM
sched = Sched(logger, Period.DAILY, "14:30")

# Weekly on Monday at 9:00 AM
sched = Sched(logger, Period.WEEKLY, "09:00", weekday=0)

# Every hour at 15 minutes past the hour
sched = Sched(logger, Period.HOURLY, "15")

# Run the scheduler
for timestamp in sched.run():
    print(f"Task executed at {timestamp}")
```

### delta.py - Duration Formatting

Provides comprehensive duration formatting with multiple output formats and precision control.

**Key Classes:**
- `DurationFormat` - Enum for output formats
- `TimeUnit` - Enum for time units

**Supported Formats:**
- `COMPACT` - Short format (e.g., "1h30m")
- `VERBOSE` - Human-readable format (e.g., "1 hour 30 minutes")
- `ISO_LIKE` - ISO 8601-like format (e.g., "01:30:00")
- `TECHNICAL` - Technical format with zero-padding (e.g., "1h30m00.000s")

**Example:**
```python
from appinfra.time import delta_str, DurationFormat

# Basic formatting (precise=False, simplified formatting)
print(delta_str(3661.5))  # "1h1m1s" (no fractional, no zero-padding)
print(delta_str(90.123))  # "1m30s" (no fractional when >= 60s)
print(delta_str(9.123))  # "9.123s" (fractional shown for seconds)
print(delta_str(0.009))  # "9ms" (< 10ms shows fractional)

# Full precision mode (precise=True, legacy behavior)
print(delta_str(3661.5, precise=True))  # "1h01m01.500s"

# Microsecond precision (requires precise=True)
print(delta_str(0.000001, precise=True))  # "1μs"

# Different formats
print(delta_str(3661.5, format_type=DurationFormat.VERBOSE))
# "1 hour 1 minute 1 second"

print(delta_str(3661.5, format_type=DurationFormat.ISO_LIKE))
# "01:01:01"

# Precision control
print(delta_str(1.234567, precision=2))  # "1h0m1.23s"
```

### date_range.py - Date Range Utilities

Provides memory-efficient date range iteration with filtering options.

**Key Functions:**
- `iter_dates(start_date, ...)` - Iterate over dates with configurable end conditions
- `iter_dates_midnight_gmt(start_date, ...)` - Iterate to today (GMT midnight)
- `dates_from_lists(dates_list, date_range_list=[], strings=True)` - Combine dates and ranges

**Example:**
```python
from appinfra.time import iter_dates, dates_from_lists
import datetime

# Iterate over dates
start_date = datetime.date(2025, 12, 1)
for date in iter_dates(start_date, skip_weekends=True):
    print(f"Business day: {date}")

# Combine individual dates and ranges
dates = [datetime.date(2025, 12, 1), datetime.date(2025, 12, 5)]
ranges = [(datetime.date(2025, 12, 10), datetime.date(2025, 12, 15))]
all_dates = dates_from_lists(dates, ranges)
print(f"Total dates: {len(all_dates)}")
```

## Design Principles

### Monotonic Time
All timing functions use the monotonic clock (`time.monotonic()`) to ensure consistent measurements even when system time changes.

### Thread Safety
The ticker system provides thread-safe operation with graceful stopping mechanisms using `threading.Event`.

### Memory Efficiency
Date range utilities use generators to provide memory-efficient iteration over large date ranges.

### Comprehensive Validation
All modules include comprehensive input validation with clear error messages and custom exceptions.

### Extensibility
The system is designed to be easily extensible with new scheduling periods, formatting options, and execution modes.

## Error Handling

The package provides comprehensive error handling with custom exceptions:

- `SchedulerError` - Base exception for scheduler errors
- `UnsupportedPeriodError` - Raised for unsupported scheduling periods
- `InvalidTimeFormatError` - Raised for invalid time formats
- `DurationError` - Base exception for duration formatting errors
- `InvalidDurationError` - Raised for invalid duration values

## Performance Considerations

- **Monotonic Clock**: Uses `time.monotonic()` for reliable timing measurements
- **Generator Pattern**: Memory-efficient iteration for large date ranges
- **Minimal Overhead**: Efficient implementations with minimal computational overhead
- **Thread Safety**: Proper synchronization for concurrent access

## Integration

The time package integrates deeply with the application framework:

- **Logging**: Uses framework's structured logging system
- **Error Handling**: Follows framework's error handling patterns
- **Configuration**: Integrates with framework's configuration system

## Testing

The package includes comprehensive test suites:

- **Unit Tests**: Individual function/class testing
- **Integration Tests**: Cross-module functionality testing
- **Edge Case Testing**: Boundary conditions and error cases
- **Performance Testing**: Timing accuracy validation

Run tests with:
```bash
source ~/.venv/bin/activate
timeout 30 python -m pytest infra/time/ -v
```
