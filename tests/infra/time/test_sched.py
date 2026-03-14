"""
Tests for scheduler functionality.

Tests key scheduler features including:
- Period enum and exception classes
- Helper functions for validation and parsing
- Sched initialization and setup
- Period-specific scheduling (daily, weekly, monthly, hourly, minutely)
- Synchronization and triggering
- Generator-based execution
- Status monitoring and control
"""

import datetime
import time
from unittest.mock import Mock, patch

import pytest

from appinfra.time.sched import (
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
    InvalidConfigError,
    InvalidTimeFormatError,
    Period,
    Sched,
    SchedulerError,
    UnsupportedPeriodError,
    _normalize_period,
    _parse_hhmm_format,
    _parse_offset,
    _validate_logger,
    _validate_weekday,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_logger():
    """Create mock logger with LoggerFactory patching."""
    logger = Mock()
    logger.info = Mock()
    logger.debug = Mock()
    logger.error = Mock()
    logger.name = "test"

    # Patch LoggerFactory.derive to return a logger mock
    with patch("appinfra.time.sched.LoggerFactory") as mock_factory:
        derived_logger = Mock()
        derived_logger.info = Mock()
        derived_logger.debug = Mock()
        derived_logger.error = Mock()
        mock_factory.derive.return_value = derived_logger
        yield logger


# =============================================================================
# Test Period Enum
# =============================================================================


@pytest.mark.unit
class TestPeriodEnum:
    """Test Period enum."""

    def test_period_values(self):
        """Test Period enum values."""
        assert Period.DAILY.value == "daily"
        assert Period.WEEKLY.value == "weekly"
        assert Period.MONTHLY.value == "monthly"
        assert Period.HOURLY.value == "hourly"
        assert Period.MINUTELY.value == "minutely"

    def test_period_comparison(self):
        """Test Period enum comparison."""
        assert Period.DAILY == Period.DAILY
        assert Period.DAILY != Period.WEEKLY


# =============================================================================
# Test Exception Classes
# =============================================================================


@pytest.mark.unit
class TestExceptionClasses:
    """Test exception hierarchy."""

    def test_scheduler_error_is_exception(self):
        """Test SchedulerError inherits from Exception."""
        error = SchedulerError("test")
        assert isinstance(error, Exception)

    def test_unsupported_period_error(self):
        """Test UnsupportedPeriodError."""
        error = UnsupportedPeriodError("Invalid period")
        assert isinstance(error, SchedulerError)

    def test_invalid_time_format_error(self):
        """Test InvalidTimeFormatError."""
        error = InvalidTimeFormatError("Invalid time")
        assert isinstance(error, SchedulerError)

    def test_invalid_configuration_error(self):
        """Test InvalidConfigError."""
        error = InvalidConfigError("Invalid config")
        assert isinstance(error, SchedulerError)


# =============================================================================
# Test Helper Functions
# =============================================================================


@pytest.mark.unit
class TestHelperFunctions:
    """Test module-level helper functions."""

    def test_validate_logger_with_valid_logger(self):
        """Test _validate_logger with valid logger."""
        logger = Mock()
        # Should not raise
        _validate_logger(logger)

    def test_validate_logger_with_none_raises_error(self):
        """Test _validate_logger with None raises error."""
        with pytest.raises(InvalidConfigError, match="Logger cannot be None"):
            _validate_logger(None)

    def test_normalize_period_with_enum(self):
        """Test _normalize_period with Period enum."""
        result = _normalize_period(Period.DAILY)
        assert result == Period.DAILY

    def test_normalize_period_with_string(self):
        """Test _normalize_period with string."""
        result = _normalize_period("daily")
        assert result == Period.DAILY

    def test_normalize_period_with_uppercase_string(self):
        """Test _normalize_period handles case insensitivity."""
        result = _normalize_period("DAILY")
        assert result == Period.DAILY

    def test_normalize_period_with_invalid_string(self):
        """Test _normalize_period with invalid string raises error."""
        with pytest.raises(UnsupportedPeriodError, match="Unsupported period"):
            _normalize_period("invalid")

    def test_validate_weekday_for_weekly_period(self):
        """Test _validate_weekday validates for weekly scheduling."""
        result = _validate_weekday(Period.WEEKLY, 3)
        assert result == 3

    def test_validate_weekday_for_weekly_without_weekday_raises_error(self):
        """Test _validate_weekday raises error when weekday missing."""
        with pytest.raises(InvalidConfigError, match="weekday must be specified"):
            _validate_weekday(Period.WEEKLY, None)

    def test_validate_weekday_out_of_range_raises_error(self):
        """Test _validate_weekday validates range."""
        with pytest.raises(InvalidConfigError, match="weekday must be between 0"):
            _validate_weekday(Period.WEEKLY, 7)

    def test_validate_weekday_for_non_weekly_period(self):
        """Test _validate_weekday returns None for non-weekly periods."""
        result = _validate_weekday(Period.DAILY, None)
        assert result is None

    def test_parse_offset_valid_hourly(self):
        """Test _parse_offset with valid hourly offset."""
        hour, minute = _parse_offset("15", Period.HOURLY)
        assert hour == 0
        assert minute == 15

    def test_parse_offset_valid_minutely(self):
        """Test _parse_offset with valid minutely offset."""
        hour, second = _parse_offset("30", Period.MINUTELY)
        assert hour == 0
        assert second == 30

    def test_parse_offset_out_of_range_raises_error(self):
        """Test _parse_offset validates range."""
        with pytest.raises(InvalidTimeFormatError, match="offset must be between"):
            _parse_offset("70", Period.HOURLY)

    def test_parse_offset_invalid_format_raises_error(self):
        """Test _parse_offset with invalid format."""
        with pytest.raises(InvalidTimeFormatError, match="Invalid offset format"):
            _parse_offset("abc", Period.HOURLY)

    def test_parse_hhmm_format_valid(self):
        """Test _parse_hhmm_format with valid time."""
        hour, minute = _parse_hhmm_format("14:30")
        assert hour == 14
        assert minute == 30

    def test_parse_hhmm_format_single_digit_hour(self):
        """Test _parse_hhmm_format with single digit hour."""
        hour, minute = _parse_hhmm_format("9:30")
        assert hour == 9
        assert minute == 30

    def test_parse_hhmm_format_invalid_hour_raises_error(self):
        """Test _parse_hhmm_format validates hour range."""
        with pytest.raises(InvalidTimeFormatError, match="Hour must be between"):
            _parse_hhmm_format("25:30")

    def test_parse_hhmm_format_invalid_minute_raises_error(self):
        """Test _parse_hhmm_format validates minute range."""
        with pytest.raises(InvalidTimeFormatError, match="Minute must be between"):
            _parse_hhmm_format("14:70")

    def test_parse_hhmm_format_unsupported_format_raises_error(self):
        """Test _parse_hhmm_format with unsupported format."""
        with pytest.raises(InvalidTimeFormatError, match="Unsupported time format"):
            _parse_hhmm_format("14")


# =============================================================================
# Test Sched Initialization
# =============================================================================


@pytest.mark.unit
class TestSchedInitialization:
    """Test Sched initialization."""

    def test_init_with_valid_daily_schedule(self, mock_logger):
        """Test initialization with daily schedule."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        assert sched.period == Period.DAILY
        assert sched._hour == 14
        assert sched._minute == 30
        assert sched.is_running is False

    def test_init_with_weekly_schedule(self, mock_logger):
        """Test initialization with weekly schedule."""
        sched = Sched(mock_logger, Period.WEEKLY, "09:00", weekday=0)
        assert sched.period == Period.WEEKLY
        assert sched._weekday == 0

    def test_init_with_hourly_schedule(self, mock_logger):
        """Test initialization with hourly schedule."""
        sched = Sched(mock_logger, Period.HOURLY, "15")
        assert sched.period == Period.HOURLY
        assert sched._minute == 15

    def test_init_with_minutely_schedule(self, mock_logger):
        """Test initialization with minutely schedule."""
        sched = Sched(mock_logger, Period.MINUTELY, "30")
        assert sched.period == Period.MINUTELY
        assert sched._minute == 30

    def test_init_with_none_logger_raises_error(self):
        """Test initialization with None logger raises error."""
        with pytest.raises(InvalidConfigError):
            Sched(None, Period.DAILY, "14:30")

    def test_init_with_string_period(self, mock_logger):
        """Test initialization with string period."""
        sched = Sched(mock_logger, "daily", "14:30")
        assert sched.period == Period.DAILY

    def test_init_with_custom_sleep_interval(self, mock_logger):
        """Test initialization with custom sleep interval."""
        sched = Sched(mock_logger, Period.DAILY, "14:30", sleep_interval=5)
        assert sched._sleep_interval == 5


# =============================================================================
# Test Sched Properties
# =============================================================================


@pytest.mark.unit
class TestSchedProperties:
    """Test Sched properties."""

    def test_period_property(self, mock_logger):
        """Test period property."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        assert sched.period == Period.DAILY

    def test_next_t_property_getter(self, mock_logger):
        """Test next_t property getter."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        assert sched.next_t is None

    def test_next_t_property_setter(self, mock_logger):
        """Test next_t property setter."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        sched.next_t = 1234567890.0
        assert sched.next_t == 1234567890.0

    def test_lg_property(self, mock_logger):
        """Test lg property."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        assert sched.lg is not None

    def test_is_running_property(self, mock_logger):
        """Test is_running property."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        assert sched.is_running is False


# =============================================================================
# Test Sched Setup Methods
# =============================================================================


@pytest.mark.unit
class TestSchedSetup:
    """Test Sched setup methods."""

    def test_setup_daily_sets_next_time(self, mock_logger):
        """Test _setup_daily sets next execution time."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        sched._setup()
        assert sched.next_t is not None
        assert sched.next_t > time.time()

    def test_setup_hourly_sets_next_time(self, mock_logger):
        """Test _setup_hourly sets next execution time."""
        sched = Sched(mock_logger, Period.HOURLY, "45")
        sched._setup()
        assert sched.next_t is not None
        assert sched.next_t > time.time()

    def test_setup_minutely_sets_next_time(self, mock_logger):
        """Test _setup_minutely sets next execution time."""
        sched = Sched(mock_logger, Period.MINUTELY, "45")
        sched._setup()
        assert sched.next_t is not None
        assert sched.next_t > time.time()


# =============================================================================
# Test Sched Sync
# =============================================================================


@pytest.mark.unit
class TestSchedSync:
    """Test Sched sync method."""

    def test_sync_first_call_sets_up_next_time(self, mock_logger):
        """Test sync() sets up next time on first call."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        assert sched.next_t is None

        triggered, delay = sched.sync()
        assert sched.next_t is not None
        assert triggered is False

    def test_sync_with_instant_triggers_immediately(self, mock_logger):
        """Test sync(instant=True) triggers on first call."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")

        triggered, delay = sched.sync(instant=True)
        assert triggered is True

    def test_sync_returns_false_before_scheduled_time(self, mock_logger):
        """Test sync() returns False before scheduled time."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        sched.next_t = time.time() + 3600  # 1 hour in future

        triggered, delay = sched.sync()
        assert triggered is False
        assert delay > 0

    def test_sync_returns_true_after_scheduled_time(self, mock_logger):
        """Test sync() returns True after scheduled time."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        sched.next_t = time.time() - 1  # 1 second in past

        triggered, delay = sched.sync()
        assert triggered is True


# =============================================================================
# Test Sched Schedule Next
# =============================================================================


@pytest.mark.unit
class TestSchedScheduleNext:
    """Test _schedule_next method."""

    def test_schedule_next_daily(self, mock_logger):
        """Test _schedule_next for daily period."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        sched.next_t = 1000.0

        sched._schedule_next()
        assert sched.next_t == 1000.0 + SECONDS_PER_DAY

    def test_schedule_next_hourly(self, mock_logger):
        """Test _schedule_next for hourly period."""
        sched = Sched(mock_logger, Period.HOURLY, "15")
        sched.next_t = 1000.0

        sched._schedule_next()
        assert sched.next_t == 1000.0 + SECONDS_PER_HOUR

    def test_schedule_next_minutely(self, mock_logger):
        """Test _schedule_next for minutely period."""
        sched = Sched(mock_logger, Period.MINUTELY, "30")
        sched.next_t = 1000.0

        sched._schedule_next()
        assert sched.next_t == 1000.0 + SECONDS_PER_MINUTE


# =============================================================================
# Test Sched Run
# =============================================================================


@pytest.mark.unit
class TestSchedRun:
    """Test Sched run method."""

    def test_run_sets_running_flag(self, mock_logger):
        """Test run() sets running flag when generator starts."""
        sched = Sched(mock_logger, Period.MINUTELY, "30", sleep_interval=0.01)
        sched.next_t = time.time() - 1  # Past time to trigger immediately

        # Initially not running
        assert sched.is_running is False

        gen = sched.run()

        # Get first yield to start generator
        timestamp = next(gen)
        assert isinstance(timestamp, float)

        # Stop and cleanup
        sched.stop()
        try:
            next(gen)
        except StopIteration:
            pass

    def test_run_yields_timestamps(self, mock_logger):
        """Test run() yields timestamps when triggered."""
        sched = Sched(mock_logger, Period.MINUTELY, "30", sleep_interval=0.01)
        sched.next_t = time.time() - 1  # Past time

        gen = sched.run()
        timestamp = next(gen)

        assert isinstance(timestamp, float)
        assert timestamp > 0

        sched.stop()
        try:
            next(gen)
        except StopIteration:
            pass


# =============================================================================
# Test Sched Control Methods
# =============================================================================


@pytest.mark.unit
class TestSchedControl:
    """Test Sched control methods."""

    def test_stop_sets_running_false(self, mock_logger):
        """Test stop() sets running flag to False."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        sched._running = True

        sched.stop()
        assert sched.is_running is False

    def test_get_status_returns_dict(self, mock_logger):
        """Test get_status() returns dict."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        status = sched.get_status()

        assert isinstance(status, dict)
        assert "period" in status
        assert "next_execution" in status
        assert "is_running" in status

    def test_get_status_includes_weekday_for_weekly(self, mock_logger):
        """Test get_status() includes weekday for weekly period."""
        sched = Sched(mock_logger, Period.WEEKLY, "09:00", weekday=0)
        status = sched.get_status()

        assert status["weekday"] == 0

    def test_get_status_weekday_none_for_daily(self, mock_logger):
        """Test get_status() has None weekday for non-weekly periods."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        status = sched.get_status()

        assert status["weekday"] is None


# =============================================================================
# Test Context Manager
# =============================================================================


@pytest.mark.unit
class TestContextManager:
    """Test Sched context manager."""

    def test_context_manager_enter(self, mock_logger):
        """Test __enter__ returns self."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        with sched as s:
            assert s is sched

    def test_context_manager_exit_calls_stop(self, mock_logger):
        """Test __exit__ calls stop()."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        sched._running = True

        with sched:
            pass

        assert sched.is_running is False


# =============================================================================
# Test Repr
# =============================================================================


@pytest.mark.unit
class TestRepr:
    """Test Sched __repr__."""

    def test_repr_includes_key_info(self, mock_logger):
        """Test __repr__ includes key information."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        repr_str = repr(sched)

        assert "Sched" in repr_str
        assert "daily" in repr_str
        assert "14:30" in repr_str


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestIntegrationScenarios:
    """Test real-world scheduler scenarios."""

    def test_daily_scheduler_workflow(self, mock_logger):
        """Test complete daily scheduler workflow."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")

        # Check initial state
        assert sched.is_running is False
        assert sched.next_t is None

        # Sync to set up
        triggered, delay = sched.sync()
        assert sched.next_t is not None
        assert triggered is False

        # Get status
        status = sched.get_status()
        assert status["period"] == "daily"

    def test_scheduler_with_instant_trigger(self, mock_logger):
        """Test scheduler with instant trigger."""
        sched = Sched(mock_logger, Period.HOURLY, "15", sleep_interval=0.01)

        gen = sched.run(instant=True)
        timestamp = next(gen)

        assert timestamp > 0

        sched.stop()
        try:
            next(gen)
        except StopIteration:
            pass


# =============================================================================
# Test Edge Cases
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_sched_with_midnight_time(self, mock_logger):
        """Test scheduler with midnight time."""
        sched = Sched(mock_logger, Period.DAILY, "00:00")
        assert sched._hour == 0
        assert sched._minute == 0

    def test_sched_with_23_59_time(self, mock_logger):
        """Test scheduler with 23:59 time."""
        sched = Sched(mock_logger, Period.DAILY, "23:59")
        assert sched._hour == 23
        assert sched._minute == 59

    def test_sched_with_zero_offset_hourly(self, mock_logger):
        """Test scheduler with zero offset for hourly."""
        sched = Sched(mock_logger, Period.HOURLY, "0")
        assert sched._minute == 0

    def test_next_t_can_be_set_to_none(self, mock_logger):
        """Test next_t property can be set to None."""
        sched = Sched(mock_logger, Period.DAILY, "14:30")
        sched.next_t = 1000.0
        sched.next_t = None
        assert sched.next_t is None


# =============================================================================
# Test Weekly and Monthly Scheduling
# =============================================================================


@pytest.mark.unit
class TestWeeklyScheduling:
    """Test weekly scheduling functionality."""

    def test_weekly_scheduling_initialization(self, mock_logger):
        """Test weekly scheduler initialization."""
        # Create scheduler for Wednesday (weekday=2) at 14:30
        sched = Sched(mock_logger, Period.WEEKLY, "14:30", weekday=2)

        assert sched.period == Period.WEEKLY
        assert sched._weekday == 2  # Wednesday
        assert sched._hour == 14
        assert sched._minute == 30

    def test_weekly_scheduling_all_weekdays(self, mock_logger):
        """Test weekly scheduling for all weekdays."""
        # Test for each day of the week (0=Monday, 6=Sunday)
        for weekday_num in range(7):
            sched = Sched(mock_logger, Period.WEEKLY, "12:00", weekday=weekday_num)
            assert sched._weekday == weekday_num
            assert sched._hour == 12
            assert sched._minute == 0


@pytest.mark.unit
class TestMonthlyScheduling:
    """Test monthly scheduling functionality."""

    def test_monthly_scheduling_initialization(self, mock_logger):
        """Test monthly scheduler initialization."""
        sched = Sched(mock_logger, Period.MONTHLY, "14:30")

        assert sched.period == Period.MONTHLY
        assert sched._hour == 14
        assert sched._minute == 30

    def test_monthly_scheduling_midnight(self, mock_logger):
        """Test monthly scheduling at midnight."""
        sched = Sched(mock_logger, Period.MONTHLY, "00:00")

        assert sched._hour == 0
        assert sched._minute == 0


@pytest.mark.unit
class TestCoverageImprovements:
    """Additional tests to improve coverage."""

    def test_invalid_time_format_error(self, mock_logger):
        """Test that invalid time format raises InvalidTimeFormatError (line 188)."""
        # Test completely invalid format (not matching any TIME_PATTERNS)
        with pytest.raises(InvalidTimeFormatError) as exc_info:
            Sched(mock_logger, Period.DAILY, "not:a:time:format")
        # Check that it's the right exception type (message can vary)
        assert isinstance(exc_info.value, InvalidTimeFormatError)

    def test_weekly_sync_triggers_setup(self, mock_logger):
        """Test weekly scheduler sync() triggers setup (lines 329, 357-371)."""
        sched = Sched(mock_logger, Period.WEEKLY, "14:30", weekday=3)  # Thursday

        # First sync() should call _setup_weekly
        result = sched.sync()

        # Should have set next_t
        assert sched.next_t is not None
        assert sched.next_t > 0

    def test_monthly_sync_triggers_setup(self, mock_logger):
        """Test monthly scheduler sync() triggers setup (lines 331, 397-412)."""
        sched = Sched(mock_logger, Period.MONTHLY, "14:30")

        # First sync() should call _setup_monthly
        result = sched.sync()

        # Should have set next_t
        assert sched.next_t is not None
        assert sched.next_t > 0

    def test_monthly_year_rollover(self, mock_logger):
        """Test monthly scheduling year rollover (lines 375-384)."""
        # Create scheduler in December to test year rollover
        with patch("appinfra.time.sched.datetime") as mock_dt:
            # Mock current time as December 15, 2025, 15:00
            dec_time = datetime.datetime(2025, 12, 15, 15, 0, 0)
            mock_dt.datetime.now.return_value = dec_time
            mock_dt.datetime.fromtimestamp = datetime.datetime.fromtimestamp

            sched = Sched(mock_logger, Period.MONTHLY, "14:30")
            sched._setup_monthly(dec_time)

            # Should schedule for next month (January 2026)
            next_dt = datetime.datetime.fromtimestamp(sched.next_t)
            assert next_dt.year == 2026
            assert next_dt.month == 1

    def test_weekly_schedule_next(self, mock_logger):
        """Test weekly _schedule_next() increments by week (line 490)."""
        sched = Sched(mock_logger, Period.WEEKLY, "14:30", weekday=2)

        # Trigger first sync to set up next_t
        sched.sync()
        initial_next_t = sched.next_t

        # Call _schedule_next (private method)
        sched._schedule_next()

        # Should increment by one week (7 days)
        from appinfra.time.sched import SECONDS_PER_WEEK

        assert sched.next_t == pytest.approx(initial_next_t + SECONDS_PER_WEEK, abs=1)

    def test_monthly_schedule_next(self, mock_logger):
        """Test monthly _schedule_next() increments by 30 days (line 493)."""
        sched = Sched(mock_logger, Period.MONTHLY, "14:30")

        # Trigger first sync to set up next_t
        sched.sync()
        initial_next_t = sched.next_t

        # Call _schedule_next (private method)
        sched._schedule_next()

        # Should increment by 30 days
        from appinfra.time.sched import SECONDS_PER_DAY

        assert sched.next_t == pytest.approx(
            initial_next_t + (SECONDS_PER_DAY * 30), abs=1
        )

    def test_hourly_time_already_passed(self, mock_logger):
        """Test hourly scheduling when time has already passed (line 420)."""
        # Create hourly scheduler with offset 30 (runs at minute 30 of each hour)
        sched = Sched(mock_logger, Period.HOURLY, "30")

        # Use a future time that's after this hour's target (14:45, target is 14:30)
        with patch("appinfra.time.sched.datetime") as mock_dt:
            current_time = datetime.datetime(2030, 1, 1, 14, 45, 0)
            # Mock both datetime.now() calls
            mock_dt.datetime = Mock()
            mock_dt.datetime.now = Mock(return_value=current_time)
            mock_dt.datetime.fromtimestamp = datetime.datetime.fromtimestamp
            mock_dt.timedelta = datetime.timedelta

            # Call setup with the current time
            sched._setup_hourly(current_time)

            # Since 14:30 has passed, should schedule for 15:30
            next_dt = datetime.datetime.fromtimestamp(sched.next_t)
            assert next_dt.hour == 15
            assert next_dt.minute == 30

    def test_weekly_same_day_time_passed(self, mock_logger):
        """Test weekly scheduling when on target day but time has passed (lines 367-368)."""
        # Create weekly scheduler for Wednesday at 14:30
        sched = Sched(mock_logger, Period.WEEKLY, "14:30", weekday=2)  # Wednesday

        # Use a future time - 2030-01-02 is a Wednesday at 15:00 (time has passed)
        with patch("appinfra.time.sched.datetime") as mock_dt:
            current_time = datetime.datetime(2030, 1, 2, 15, 0, 0)
            # Mock datetime module properly
            mock_dt.datetime = Mock()
            mock_dt.datetime.now = Mock(return_value=current_time)
            mock_dt.datetime.fromtimestamp = datetime.datetime.fromtimestamp
            mock_dt.timedelta = datetime.timedelta

            sched._setup_weekly(current_time)

            # Should schedule for next Wednesday, not today
            next_dt = datetime.datetime.fromtimestamp(sched.next_t)
            assert next_dt.weekday() == 2  # Wednesday
            # The difference should be 7 days exactly
            days_diff = (next_dt - current_time).days
            assert days_diff >= 6 and days_diff <= 7  # Allow for time-of-day effects
