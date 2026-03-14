"""
Tests for rate limiting functionality.

Tests key rate limiter features including:
- Rate limiter initialization
- Rate limiting behavior
- Waiting between operations
- Exponential backoff
"""

import time
from unittest.mock import Mock, patch

import pytest

from appinfra.rate_limit import Backoff, RateLimiter

# =============================================================================
# Test RateLimiter Initialization
# =============================================================================


@pytest.mark.unit
class TestRateLimiterInitialization:
    """Test RateLimiter initialization."""

    def test_init_with_per_minute(self):
        """Test initialization with per_minute parameter."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)
        assert limiter.per_minute == 60
        # last_t is initialized to a future time to prevent thundering herd
        assert isinstance(limiter.last_t, float)

    def test_init_with_logger(self):
        """Test initialization with logger."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)
        assert limiter._lg is mock_logger

    def test_init_with_zero_per_minute_raises(self):
        """Test initialization with zero per_minute raises ValueError."""
        mock_logger = Mock()
        with pytest.raises(ValueError, match="per_minute must be positive"):
            RateLimiter(mock_logger, per_minute=0)

    def test_init_with_negative_per_minute_raises(self):
        """Test initialization with negative per_minute raises ValueError."""
        mock_logger = Mock()
        with pytest.raises(ValueError, match="per_minute must be positive"):
            RateLimiter(mock_logger, per_minute=-10)


# =============================================================================
# Test RateLimiter next() Method
# =============================================================================


@pytest.mark.unit
class TestRateLimiterNext:
    """Test RateLimiter next() method."""

    def test_first_call_waits(self):
        """Test first call to next() waits to prevent thundering herd at startup."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)
        wait = limiter.next()
        # First call waits because last_t is initialized to future time
        assert wait > 0
        assert isinstance(limiter.last_t, float)

    def test_rapid_calls_cause_waiting(self):
        """Test rapid calls cause waiting."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=120)  # 2 per second

        # First call
        limiter.next()

        # Second call should wait
        start = time.monotonic()
        wait = limiter.next()
        elapsed = time.monotonic() - start

        # Should have waited approximately the delay amount
        assert wait > 0
        assert elapsed >= wait * 0.9  # Allow 10% tolerance

    def test_respect_max_ticks_false_no_sleep(self):
        """Test respect_max_ticks=False doesn't sleep."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=120)

        # First call
        limiter.next()

        # Second call with respect_max_ticks=False should not sleep
        start = time.monotonic()
        wait = limiter.next(respect_max_ticks=False)
        elapsed = time.monotonic() - start

        # Should calculate wait but not actually sleep
        assert wait > 0
        assert elapsed < 0.01  # Should be very quick

    def test_sufficient_delay_no_wait(self):
        """Test sufficient delay between calls doesn't cause waiting."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)

        # First call
        limiter.next()

        # Wait for the rate limit delay
        time.sleep(1.1)  # Slightly more than 1 second (60 per minute = 1/sec)

        # Second call should not wait
        wait = limiter.next()
        assert wait == 0

    def test_logger_called_when_waiting(self):
        """Test logger is called when waiting."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=120)

        # First call waits (and logs)
        limiter.next()

        # Logger should have been called
        mock_logger.trace.assert_called_once()
        args, kwargs = mock_logger.trace.call_args
        assert "rate limiter wait" in args
        assert "extra" in kwargs
        assert "wait" in kwargs["extra"]

    def test_logger_not_called_when_slot_available(self):
        """Test logger not called when slot is available (after waiting)."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)

        # First call waits
        limiter.next()
        mock_logger.reset_mock()

        # Wait for slot to become available
        time.sleep(1.1)

        # Second call - slot available, no wait
        limiter.next()

        # Logger should not have been called for second call
        mock_logger.trace.assert_not_called()


# =============================================================================
# Test RateLimiter try_next() Method
# =============================================================================


@pytest.mark.unit
class TestRateLimiterTryNext:
    """Test RateLimiter try_next() method."""

    def test_first_call_returns_false(self):
        """Test first call to try_next() returns False (slot not yet available)."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)
        # First call returns False because last_t is initialized to future time
        assert limiter.try_next() is False

    def test_rapid_call_returns_false(self):
        """Test rapid calls return False without blocking until slot available."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)  # 1 per second

        # Wait for slot to become available
        time.sleep(1.1)

        # First call after wait should succeed
        assert limiter.try_next() is True
        first_t = limiter.last_t

        # Immediate second call should fail (non-blocking)
        start = time.monotonic()
        assert limiter.try_next() is False
        elapsed = time.monotonic() - start

        # Should be non-blocking (very fast)
        assert elapsed < 0.01
        # last_t should not have changed
        assert limiter.last_t == first_t

    def test_after_delay_returns_true(self):
        """Test try_next() returns True after sufficient delay."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=120)  # 0.5 second delay

        # Wait for initial slot to become available
        time.sleep(0.55)

        assert limiter.try_next() is True

        # Wait for the rate limit delay
        time.sleep(0.55)

        # Should succeed now
        assert limiter.try_next() is True

    def test_does_not_modify_state_on_false(self):
        """Test try_next() doesn't modify last_t when returning False."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)

        limiter.try_next()
        original_last_t = limiter.last_t

        # Multiple rapid calls should not change last_t
        for _ in range(5):
            limiter.try_next()

        assert limiter.last_t == original_last_t

    def test_updates_state_on_true(self):
        """Test try_next() updates last_t when returning True."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=120)

        limiter.try_next()
        first_t = limiter.last_t

        time.sleep(0.55)

        limiter.try_next()
        second_t = limiter.last_t

        assert second_t > first_t

    def test_non_blocking_behavior(self):
        """Test try_next() never blocks regardless of rate limit."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=1)  # Very slow: 60 second delay

        limiter.try_next()

        # Even with 60-second delay, try_next should return immediately
        start = time.monotonic()
        result = limiter.try_next()
        elapsed = time.monotonic() - start

        assert result is False
        assert elapsed < 0.01  # Should be near-instant


# =============================================================================
# Test RateLimiter can_proceed() Method
# =============================================================================


@pytest.mark.unit
class TestRateLimiterCanProceed:
    """Test RateLimiter can_proceed() method."""

    def test_first_call_returns_false(self):
        """Test can_proceed() returns False initially (slot not yet available)."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)
        # Initially False because last_t is set to future time
        assert limiter.can_proceed() is False

    def test_does_not_modify_last_t_on_true(self):
        """Test can_proceed() does NOT update last_t when returning True."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)

        # Wait for slot to become available
        time.sleep(1.1)
        original_last_t = limiter.last_t
        assert limiter.can_proceed() is True
        # last_t unchanged - slot not consumed
        assert limiter.last_t == original_last_t

    def test_does_not_modify_last_t_on_false(self):
        """Test can_proceed() does NOT update last_t when returning False."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)

        # Consume a slot first
        limiter.try_next()
        original_last_t = limiter.last_t

        # can_proceed() should return False and not modify last_t
        assert limiter.can_proceed() is False
        assert limiter.last_t == original_last_t

    def test_rapid_call_returns_false(self):
        """Test can_proceed() returns False immediately after try_next()."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)  # 1 per second

        # Consume a slot
        limiter.try_next()

        # Immediate can_proceed() should return False
        assert limiter.can_proceed() is False

    def test_after_delay_returns_true(self):
        """Test can_proceed() returns True after sufficient delay."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=120)  # 0.5 second delay

        # Wait for initial slot
        time.sleep(0.55)

        limiter.try_next()

        # Wait for the rate limit delay
        time.sleep(0.55)

        # Should return True now
        assert limiter.can_proceed() is True

    def test_multiple_calls_return_same_value(self):
        """Test calling can_proceed() multiple times returns consistent value."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)

        # Initially all should return False (slot not yet available)
        assert limiter.can_proceed() is False
        assert limiter.can_proceed() is False
        assert limiter.can_proceed() is False

        # Wait for slot to become available
        time.sleep(1.1)

        # Now all should return True
        assert limiter.can_proceed() is True
        assert limiter.can_proceed() is True

        # Consume a slot
        limiter.try_next()

        # After consumption - all should return False
        assert limiter.can_proceed() is False
        assert limiter.can_proceed() is False
        assert limiter.can_proceed() is False

    def test_non_blocking_behavior(self):
        """Test can_proceed() never blocks regardless of rate limit."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=1)  # Very slow: 60 second delay

        # Even with 60-second delay, can_proceed should return immediately
        start = time.monotonic()
        result = limiter.can_proceed()
        elapsed = time.monotonic() - start

        assert result is False  # Slot not available yet
        assert elapsed < 0.01  # Should be near-instant

    def test_consistent_with_try_next(self):
        """Test can_proceed() returns True exactly when try_next() would succeed."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=120)  # 0.5 second delay

        # Initially both would fail (slot not yet available)
        assert limiter.can_proceed() is False

        # Wait for slot
        time.sleep(0.55)

        # Now both would succeed
        assert limiter.can_proceed() is True

        # Consume slot
        limiter.try_next()

        # Both would fail now
        assert limiter.can_proceed() is False

        # Wait for delay
        time.sleep(0.55)

        # Both would succeed now
        assert limiter.can_proceed() is True
        # Actually consume it to verify
        assert limiter.try_next() is True


# =============================================================================
# Test Rate Limiting Calculations
# =============================================================================


@pytest.mark.unit
class TestRateLimitingCalculations:
    """Test rate limiting calculations."""

    def test_60_per_minute_delay(self):
        """Test 60 per minute gives 1 second delay."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=60)
        delay = 60.0 / limiter.per_minute
        assert delay == 1.0

    def test_120_per_minute_delay(self):
        """Test 120 per minute gives 0.5 second delay."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=120)
        delay = 60.0 / limiter.per_minute
        assert delay == 0.5

    def test_30_per_minute_delay(self):
        """Test 30 per minute gives 2 second delay."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=30)
        delay = 60.0 / limiter.per_minute
        assert delay == 2.0


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestRateLimiterIntegration:
    """Test real-world rate limiter scenarios."""

    def test_rate_limiter_workflow(self):
        """Test complete rate limiter workflow."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=120)  # Fast rate for testing

        # First operation - waits (prevents thundering herd at startup)
        wait1 = limiter.next()
        assert wait1 > 0

        # Second operation - should wait
        wait2 = limiter.next()
        assert wait2 > 0

        # Third operation - should wait
        wait3 = limiter.next()
        assert wait3 > 0

    def test_rate_limiter_with_variable_delays(self):
        """Test rate limiter with variable delays between calls."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=120)

        limiter.next()
        time.sleep(0.3)  # Partial delay

        wait = limiter.next()
        # Should wait for remaining time
        assert 0 < wait < 0.5

    def test_multiple_operations_stay_within_rate(self):
        """Test multiple operations stay within rate limit."""
        mock_logger = Mock()
        limiter = RateLimiter(mock_logger, per_minute=120)  # 2 per second

        start = time.monotonic()

        # Perform 10 operations
        for _ in range(10):
            limiter.next()

        elapsed = time.monotonic() - start

        # Should take at least 4.5 seconds (10 ops / 2 per sec = 5 sec, minus first op)
        assert elapsed >= 4.0  # Allow some tolerance


# =============================================================================
# Test Backoff Initialization
# =============================================================================


@pytest.mark.unit
class TestBackoffInitialization:
    """Test Backoff initialization."""

    def test_init_default_values(self):
        """Test initialization with default values."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger)
        assert backoff.base == 1.0
        assert backoff.max_delay == 60.0
        assert backoff.factor == 2.0
        assert backoff.jitter is True
        assert backoff._lg is mock_logger
        assert backoff.attempts == 0

    def test_init_custom_values(self):
        """Test initialization with custom values."""
        mock_logger = Mock()
        backoff = Backoff(
            mock_logger, base=0.5, max_delay=30.0, factor=3.0, jitter=False
        )
        assert backoff.base == 0.5
        assert backoff.max_delay == 30.0
        assert backoff.factor == 3.0
        assert backoff.jitter is False

    def test_init_logger_is_required(self):
        """Test logger is required as first parameter."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger)
        assert backoff._lg is mock_logger

    def test_init_rejects_non_positive_base(self):
        """Test that base must be positive."""
        mock_logger = Mock()
        with pytest.raises(ValueError, match="base must be positive"):
            Backoff(mock_logger, base=0)
        with pytest.raises(ValueError, match="base must be positive"):
            Backoff(mock_logger, base=-1.0)

    def test_init_rejects_non_positive_max_delay(self):
        """Test that max_delay must be positive."""
        mock_logger = Mock()
        with pytest.raises(ValueError, match="max_delay must be positive"):
            Backoff(mock_logger, max_delay=0)
        with pytest.raises(ValueError, match="max_delay must be positive"):
            Backoff(mock_logger, max_delay=-10.0)

    def test_init_rejects_factor_less_than_one(self):
        """Test that factor must be >= 1."""
        mock_logger = Mock()
        with pytest.raises(ValueError, match="factor must be >= 1"):
            Backoff(mock_logger, factor=0.5)
        with pytest.raises(ValueError, match="factor must be >= 1"):
            Backoff(mock_logger, factor=0)

    def test_init_accepts_factor_of_one(self):
        """Test that factor=1 is allowed (constant delay)."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, factor=1.0, jitter=False)
        assert backoff.factor == 1.0
        # All delays should be the same
        delays = [backoff.next_delay() for _ in range(3)]
        assert delays == [1.0, 1.0, 1.0]


# =============================================================================
# Test Backoff next_delay() Method
# =============================================================================


@pytest.mark.unit
class TestBackoffNextDelay:
    """Test Backoff next_delay() method."""

    def test_exponential_growth_without_jitter(self):
        """Test delay grows exponentially without jitter."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, base=1.0, factor=2.0, jitter=False)

        delays = [backoff.next_delay() for _ in range(5)]

        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]

    def test_attempts_increment(self):
        """Test attempts counter increments with each call."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, jitter=False)

        assert backoff.attempts == 0
        backoff.next_delay()
        assert backoff.attempts == 1
        backoff.next_delay()
        assert backoff.attempts == 2
        backoff.next_delay()
        assert backoff.attempts == 3

    def test_max_delay_cap(self):
        """Test delay is capped at max_delay."""
        mock_logger = Mock()
        backoff = Backoff(
            mock_logger, base=1.0, max_delay=10.0, factor=2.0, jitter=False
        )

        # 1, 2, 4, 8, 10 (capped), 10 (capped)
        delays = [backoff.next_delay() for _ in range(6)]

        assert delays == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]

    def test_jitter_reduces_delay(self):
        """Test jitter reduces delay (multiplies by 0.0-1.0)."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, base=10.0, factor=1.0, jitter=True)

        # With full jitter, delay should be between 0.0 and 10.0
        delays = [backoff.next_delay() for _ in range(100)]

        for delay in delays:
            assert 0.0 <= delay <= 10.0

    def test_jitter_provides_randomness(self):
        """Test jitter produces different values."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, base=10.0, factor=1.0, jitter=True)

        delays = [backoff.next_delay() for _ in range(10)]
        backoff.reset()

        # Not all delays should be the same (statistical test)
        unique_delays = set(delays)
        assert len(unique_delays) > 1

    def test_custom_factor(self):
        """Test custom growth factor."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, base=1.0, factor=3.0, jitter=False)

        delays = [backoff.next_delay() for _ in range(4)]

        assert delays == [1.0, 3.0, 9.0, 27.0]


# =============================================================================
# Test Backoff wait() Method
# =============================================================================


@pytest.mark.unit
class TestBackoffWait:
    """Test Backoff wait() method."""

    def test_wait_blocks_for_delay(self):
        """Test wait() actually sleeps for the delay."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, base=0.1, jitter=False)

        start = time.monotonic()
        delay = backoff.wait()
        elapsed = time.monotonic() - start

        assert delay == 0.1
        assert elapsed >= 0.09  # Allow small tolerance

    def test_wait_returns_delay(self):
        """Test wait() returns the delay value."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, base=0.05, jitter=False)

        delay = backoff.wait()
        assert delay == 0.05

    def test_wait_increments_attempts(self):
        """Test wait() increments attempt counter."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, base=0.01, jitter=False)

        assert backoff.attempts == 0
        backoff.wait()
        assert backoff.attempts == 1

    def test_wait_logs(self):
        """Test wait() logs the backoff."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, base=0.01, jitter=False)

        backoff.wait()

        mock_logger.trace.assert_called_once()
        args, kwargs = mock_logger.trace.call_args
        assert "backoff wait" in args
        assert "extra" in kwargs
        assert "delay" in kwargs["extra"]
        assert "attempt" in kwargs["extra"]
        assert kwargs["extra"]["attempt"] == 1


# =============================================================================
# Test Backoff reset() Method
# =============================================================================


@pytest.mark.unit
class TestBackoffReset:
    """Test Backoff reset() method."""

    def test_reset_clears_attempts(self):
        """Test reset() sets attempts to 0."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, jitter=False)

        backoff.next_delay()
        backoff.next_delay()
        backoff.next_delay()
        assert backoff.attempts == 3

        backoff.reset()
        assert backoff.attempts == 0

    def test_reset_restarts_delay_sequence(self):
        """Test reset() restarts the delay sequence."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, base=1.0, factor=2.0, jitter=False)

        # Progress through sequence
        backoff.next_delay()  # 1
        backoff.next_delay()  # 2
        backoff.next_delay()  # 4

        backoff.reset()

        # Should start fresh
        assert backoff.next_delay() == 1.0
        assert backoff.next_delay() == 2.0


# =============================================================================
# Test Backoff Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestBackoffIntegration:
    """Test real-world backoff scenarios."""

    def test_retry_loop_pattern(self):
        """Test typical retry loop usage pattern."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, base=0.01, max_delay=0.1, jitter=False)
        attempts = 0
        max_attempts = 5

        # Simulate retry loop
        while attempts < max_attempts:
            attempts += 1
            # Simulate failure
            if attempts < 3:
                backoff.wait()
            else:
                # Success on attempt 3
                backoff.reset()
                break

        assert attempts == 3
        assert backoff.attempts == 0  # Reset after success

    def test_success_reset_pattern(self):
        """Test backoff reset after successful operation."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, base=0.01, jitter=False)

        # Fail twice
        backoff.wait()
        backoff.wait()
        assert backoff.attempts == 2

        # Success - reset
        backoff.reset()
        assert backoff.attempts == 0

        # Next failure starts fresh
        delay = backoff.next_delay()
        assert delay == 0.01  # Back to base delay

    def test_delay_progression_with_jitter(self):
        """Test delay progression with jitter stays within bounds."""
        mock_logger = Mock()
        backoff = Backoff(
            mock_logger, base=1.0, max_delay=10.0, factor=2.0, jitter=True
        )

        # Expected base delays: 1, 2, 4, 8, 10, 10
        # With full jitter (0.0-1.0 multiplier), bounds are:
        expected_bounds = [
            (0.0, 1.0),  # attempt 0: base=1
            (0.0, 2.0),  # attempt 1: base=2
            (0.0, 4.0),  # attempt 2: base=4
            (0.0, 8.0),  # attempt 3: base=8
            (0.0, 10.0),  # attempt 4: base=10 (capped)
            (0.0, 10.0),  # attempt 5: base=10 (capped)
        ]

        for min_bound, max_bound in expected_bounds:
            delay = backoff.next_delay()
            assert min_bound <= delay <= max_bound, (
                f"Delay {delay} not in [{min_bound}, {max_bound}]"
            )

    def test_multiple_backoff_instances_independent(self):
        """Test multiple backoff instances don't share state."""
        mock_logger = Mock()
        backoff1 = Backoff(mock_logger, base=1.0, jitter=False)
        backoff2 = Backoff(mock_logger, base=2.0, jitter=False)

        backoff1.next_delay()
        backoff1.next_delay()

        assert backoff1.attempts == 2
        assert backoff2.attempts == 0

        delay2 = backoff2.next_delay()
        assert delay2 == 2.0  # Uses its own base

    @patch("appinfra.rate_limit.time.sleep")
    def test_wait_uses_calculated_delay(self, mock_sleep):
        """Test wait() sleeps for the calculated delay."""
        mock_logger = Mock()
        backoff = Backoff(mock_logger, base=5.0, factor=2.0, jitter=False)

        backoff.wait()
        mock_sleep.assert_called_once_with(5.0)

        mock_sleep.reset_mock()
        backoff.wait()
        mock_sleep.assert_called_once_with(10.0)
