# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for time utility functions.

Tests key time utility features including:
- High-precision timing functions
- Duration calculations
- Date conversion and manipulation
- Timestamp conversions
- Context managers for timing
"""

import datetime
import time
from unittest.mock import Mock

import pytest

from appinfra.time.time import (
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

# =============================================================================
# Test Timing Functions
# =============================================================================


@pytest.mark.unit
class TestTimingFunctions:
    """Test timing utility functions."""

    def test_start_returns_float(self):
        """Test start() returns a float timestamp."""
        result = start()
        assert isinstance(result, float)
        assert result > 0

    def test_since_calculates_elapsed_time(self):
        """Test since() calculates elapsed time correctly."""
        start_time = start()
        time.sleep(0.01)
        elapsed = since(start_time)

        assert isinstance(elapsed, float)
        assert elapsed >= 0.01
        assert elapsed < 0.1  # Should be less than 100ms

    def test_since_with_zero_elapsed(self):
        """Test since() with minimal elapsed time."""
        start_time = start()
        elapsed = since(start_time)

        assert isinstance(elapsed, float)
        assert elapsed >= 0

    def test_since_str_formats_elapsed_time(self):
        """Test since_str() formats elapsed time as string."""
        start_time = start()
        time.sleep(0.01)
        result = since_str(start_time)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_since_str_with_micros(self):
        """Test since_str() with microsecond precision."""
        start_time = start()
        time.sleep(0.001)
        result = since_str(start_time, precise=True)

        assert isinstance(result, str)
        assert len(result) > 0


# =============================================================================
# Test Date Conversion Functions
# =============================================================================


@pytest.mark.unit
class TestDateConversionFunctions:
    """Test date conversion utility functions."""

    def test_date_from_str_valid_date(self):
        """Test date_from_str() with valid date string."""
        result = date_from_str("2025-12-25")

        assert isinstance(result, datetime.date)
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 25

    def test_date_from_str_single_digit_month_day(self):
        """Test date_from_str() with single-digit month/day."""
        result = date_from_str("2025-12-05")

        assert result.year == 2025
        assert result.month == 12
        assert result.day == 5

    def test_date_to_str_formats_correctly(self):
        """Test date_to_str() formats date correctly."""
        date = datetime.date(2025, 12, 25)
        result = date_to_str(date)

        assert result == "2025-12-25"

    def test_date_to_str_pads_month_day(self):
        """Test date_to_str() pads single-digit month/day."""
        date = datetime.date(2025, 12, 5)
        result = date_to_str(date)

        assert result == "2025-12-05"

    def test_date_from_str_to_str_roundtrip(self):
        """Test roundtrip conversion from string to date and back."""
        original = "2025-12-25"
        date = date_from_str(original)
        result = date_to_str(date)

        assert result == original


# =============================================================================
# Test Date and Time Combination Functions
# =============================================================================


@pytest.mark.unit
class TestDateTimeCombination:
    """Test date and time combination functions."""

    def test_date_with_time_default(self):
        """Test date_with_time() with default time."""
        date = datetime.date(2025, 12, 25)
        result = date_with_time(date)

        assert isinstance(result, datetime.datetime)
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 25
        assert result.hour == 0
        assert result.minute == 0

    def test_date_with_time_custom_time(self):
        """Test date_with_time() with custom time."""
        date = datetime.date(2025, 12, 25)
        result = date_with_time(date, "14:30")

        assert result.hour == 14
        assert result.minute == 30

    def test_date_with_time_midnight(self):
        """Test date_with_time() with midnight."""
        date = datetime.date(2025, 12, 25)
        result = date_with_time(date, "00:00")

        assert result.hour == 0
        assert result.minute == 0

    def test_date_with_time_end_of_day(self):
        """Test date_with_time() with end of day."""
        date = datetime.date(2025, 12, 25)
        result = date_with_time(date, "23:59")

        assert result.hour == 23
        assert result.minute == 59


# =============================================================================
# Test Timestamp Conversion Functions
# =============================================================================


@pytest.mark.unit
class TestTimestampConversion:
    """Test timestamp conversion functions."""

    def test_timestamp_from_date_default_time(self):
        """Test timestamp_from_date() with default time."""
        date = datetime.date(2025, 12, 1)
        result = timestamp_from_date(date)

        assert isinstance(result, float)
        assert result > 0

    def test_timestamp_from_date_custom_time(self):
        """Test timestamp_from_date() with custom time."""
        date = datetime.date(2025, 12, 1)
        result = timestamp_from_date(date, "14:30")

        assert isinstance(result, float)
        assert result > 0

    def test_date_from_timestamp_valid_timestamp(self):
        """Test date_from_timestamp() with valid timestamp."""
        # Use current time to avoid timezone issues
        now = datetime.datetime.now()
        timestamp = now.timestamp()
        result = date_from_timestamp(timestamp)

        assert isinstance(result, datetime.date)
        assert result.year == now.year
        assert result.month == now.month
        assert result.day == now.day

    def test_timestamp_date_roundtrip(self):
        """Test roundtrip conversion from date to timestamp and back."""
        original_date = datetime.date(2025, 12, 1)
        timestamp = timestamp_from_date(original_date, "00:00")
        result_date = date_from_timestamp(timestamp)

        assert result_date == original_date


# =============================================================================
# Test Yesterday Function
# =============================================================================


@pytest.mark.unit
class TestYesterday:
    """Test yesterday utility function."""

    def test_yesterday_returns_date(self):
        """Test yesterday() returns a date object."""
        result = yesterday()

        assert isinstance(result, datetime.date)

    def test_yesterday_is_one_day_before_today(self):
        """Test yesterday() is one day before today."""
        today = datetime.date.today()
        result = yesterday()

        expected = today - datetime.timedelta(days=1)
        assert result == expected


# =============================================================================
# Test Context Manager time_it
# =============================================================================


@pytest.mark.unit
class TestTimeItContextManager:
    """Test time_it context manager."""

    def test_time_it_calls_callback(self):
        """Test time_it() calls callback with elapsed time."""
        callback = Mock()

        with time_it(callback):
            time.sleep(0.01)

        callback.assert_called_once()
        elapsed = callback.call_args[0][0]
        assert isinstance(elapsed, float)
        assert elapsed >= 0.01

    def test_time_it_calls_callback_even_with_exception(self):
        """Test time_it() calls callback even when exception occurs."""
        callback = Mock()

        with pytest.raises(ValueError):
            with time_it(callback):
                raise ValueError("test error")

        callback.assert_called_once()

    def test_time_it_measures_zero_elapsed_time(self):
        """Test time_it() measures near-zero elapsed time."""
        callback = Mock()

        with time_it(callback):
            pass  # No work

        callback.assert_called_once()
        elapsed = callback.call_args[0][0]
        assert isinstance(elapsed, float)
        assert elapsed >= 0


# =============================================================================
# Test Context Manager time_it_lg
# =============================================================================


@pytest.mark.unit
class TestTimeItLgContextManager:
    """Test time_it_lg context manager."""

    def test_time_it_lg_calls_logger(self):
        """Test time_it_lg() calls logging function."""
        log_func = Mock()

        with time_it_lg(log_func, "test message"):
            time.sleep(0.01)

        log_func.assert_called_once()
        args, kwargs = log_func.call_args
        assert args[0] == "test message"
        assert "extra" in kwargs
        assert "after" in kwargs["extra"]

    def test_time_it_lg_includes_elapsed_time(self):
        """Test time_it_lg() includes elapsed time in extra data."""
        log_func = Mock()

        with time_it_lg(log_func, "test message"):
            time.sleep(0.01)

        kwargs = log_func.call_args[1]
        elapsed = kwargs["extra"]["after"]
        assert isinstance(elapsed, float)
        assert elapsed >= 0.01

    def test_time_it_lg_merges_extra_data(self):
        """Test time_it_lg() merges provided extra data."""
        log_func = Mock()
        extra = {"key1": "value1", "key2": "value2"}

        with time_it_lg(log_func, "test message", extra):
            time.sleep(0.01)

        kwargs = log_func.call_args[1]
        assert kwargs["extra"]["key1"] == "value1"
        assert kwargs["extra"]["key2"] == "value2"
        assert "after" in kwargs["extra"]

    def test_time_it_lg_calls_logger_even_with_exception(self):
        """Test time_it_lg() calls logger even when exception occurs."""
        log_func = Mock()

        with pytest.raises(ValueError):
            with time_it_lg(log_func, "test message"):
                raise ValueError("test error")

        log_func.assert_called_once()


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestIntegrationScenarios:
    """Test real-world usage scenarios."""

    def test_full_date_workflow(self):
        """Test complete date manipulation workflow."""
        # Parse date from string
        date_str = "2025-12-25"
        date = date_from_str(date_str)

        # Combine with time
        dt = date_with_time(date, "14:30")

        # Convert to timestamp
        timestamp = timestamp_from_date(date, "14:30")

        # Convert back to date
        result_date = date_from_timestamp(timestamp)

        assert result_date == date

    def test_timing_workflow(self):
        """Test complete timing workflow."""
        # Start timing
        start_time = start()

        # Simulate work
        time.sleep(0.01)

        # Calculate elapsed
        elapsed = since(start_time)
        elapsed_str = since_str(start_time)

        assert elapsed >= 0.01
        assert isinstance(elapsed_str, str)
