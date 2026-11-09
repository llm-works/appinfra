# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Comprehensive tests for ticker system.

Tests the Ticker and TickerHandler functionality including:
- Ticker initialization with validation
- Scheduled execution mode with intervals
- Continuous execution mode
- Lifecycle methods (start, tick, stop)
- Graceful stopping and cleanup
- Status monitoring
- Error handling
"""

import logging
import pickle
import threading
import time
from typing import Any
from unittest.mock import Mock

import pytest

import appinfra.time.ticker
from appinfra.errors import TickerAPIError, TickerConfigError, TickerStateError
from appinfra.log import create_lg
from appinfra.time.ticker import Ticker, TickerHandler, TickerMode

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_logger():
    """Create mock logger for tests."""
    logger = Mock(spec=logging.Logger)
    logger.exception = Mock()
    logger.error = Mock()
    logger.debug = Mock()
    logger.info = Mock()
    return logger


@pytest.fixture
def mock_handler():
    """Create mock ticker handler."""
    handler = Mock(spec=TickerHandler)
    handler.ticker_start = Mock()
    handler.ticker_before_first_tick = Mock()
    handler.ticker_tick = Mock()
    handler.ticker_stop = Mock()
    return handler


@pytest.fixture
def simple_handler():
    """Create simple TickerHandler implementation."""

    class SimpleHandler(TickerHandler):
        def __init__(self):
            self.tick_count = 0
            self.started = False
            self.stopped = False

        def ticker_start(self, *args, **kwargs):
            self.started = True

        def ticker_tick(self):
            self.tick_count += 1

        def ticker_stop(self):
            self.stopped = True

    return SimpleHandler()


# A monotonic timestamp for tests that pass ``now`` to try_tick() and
# time_until_next_tick(): those read no clock, so their results are exact on any clock
T0 = 1000.0


@pytest.fixture
def clock(fake_clock):
    """Put this module's sleeps on the fake clock with the ticker's, so they take no real time.

    Every assertion holds on the real clock as well: a tick comes no earlier than its
    schedule allows, and a time until the next tick is at most what the schedule left.
    """
    fake_clock.patch(__name__)


def _recording_delays(ticker: Ticker) -> list[float]:
    """Record every delay run() schedules a tick after; exact on any clock."""
    assert ticker._sched is not None
    delays: list[float] = []
    enter = ticker._sched.enter

    def recording(delay: float, *args, **kwargs):
        delays.append(delay)
        return enter(delay, *args, **kwargs)

    ticker._sched.enter = recording  # type: ignore[method-assign]
    return delays


class _TimeSpy:
    """Stands in for a module's ``time`` (real or the fake clock's): records the sleep()
    calls and passes everything on to it."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.sleeps: list[float] = []

    def sleep(self, secs: float) -> None:
        self.sleeps.append(secs)
        self.inner.sleep(secs)

    def __getattr__(self, name: str):
        return getattr(self.inner, name)


def _spy_on_waits(ticker: Ticker, monkeypatch) -> tuple[_TimeSpy, Mock]:
    """Record every sleep in the ticker module and every wait on ``ticker``'s stop event,
    which is how run() waits for its next tick."""
    sleeps = _TimeSpy(appinfra.time.ticker.time)
    monkeypatch.setattr(appinfra.time.ticker, "time", sleeps)
    waits = Mock(wraps=ticker._stop_event.wait)
    ticker._stop_event.wait = waits  # type: ignore[method-assign]
    return sleeps, waits


# =============================================================================
# Test TickerHandler Interface
# =============================================================================


class TestTickerHandler:
    """Test TickerHandler interface."""

    def test_default_ticker_start_is_noop(self):
        """Test default ticker_start does nothing."""
        handler = TickerHandler()
        # Should not raise
        handler.ticker_start()

    def test_default_ticker_before_first_tick_is_noop(self):
        """Test default ticker_before_first_tick does nothing."""
        handler = TickerHandler()
        # Should not raise
        handler.ticker_before_first_tick()

    def test_default_ticker_tick_is_noop(self):
        """Test default ticker_tick does nothing."""
        handler = TickerHandler()
        # Should not raise
        handler.ticker_tick()

    def test_default_ticker_stop_is_noop(self):
        """Test default ticker_stop does nothing."""
        handler = TickerHandler()
        # Should not raise
        handler.ticker_stop()

    def test_custom_handler_implements_all_methods(self, mock_logger, simple_handler):
        """Test custom handler can override all methods."""
        simple_handler.ticker_start()
        simple_handler.ticker_tick()
        simple_handler.ticker_stop()

        assert simple_handler.started is True
        assert simple_handler.tick_count == 1
        assert simple_handler.stopped is True


# =============================================================================
# Test Ticker Initialization
# =============================================================================


class TestTickerInitialization:
    """Test Ticker initialization."""

    def test_init_with_valid_handler_scheduled_mode(self, mock_logger, mock_handler):
        """Test initialization with handler in scheduled mode."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)
        assert ticker._handler == mock_handler
        assert ticker._secs == 1.0
        assert ticker._sched is not None
        assert ticker._running is False

    def test_init_with_valid_handler_continuous_mode(self, mock_logger, mock_handler):
        """Test initialization with handler in continuous mode."""
        ticker = Ticker(mock_logger, mock_handler)
        assert ticker._handler == mock_handler
        assert ticker._secs is None
        assert ticker._sched is None
        assert ticker._running is False

    def test_init_with_none_handler_for_iterator_mode(self, mock_logger):
        """Test initialization with None handler is allowed for iterator mode."""
        ticker = Ticker(mock_logger, secs=1.0)
        assert ticker._handler is None
        assert ticker._secs == 1.0

    def test_run_with_none_handler_raises_error(self, mock_logger):
        """Test run() with None handler raises ValueError."""
        ticker = Ticker(mock_logger, secs=1.0)
        with pytest.raises(
            TickerConfigError, match="Handler required for run\\(\\) mode"
        ):
            ticker.run()

    def test_init_with_invalid_mode_raises_error(self, mock_logger):
        """Test initialization with invalid mode raises error."""
        with pytest.raises(
            TickerConfigError, match="mode must be TickerMode enum, got str"
        ):
            Ticker(mock_logger, secs=1.0, mode="invalid")

    def test_init_with_negative_secs_raises_error(self, mock_logger):
        """Test initialization with negative secs raises error."""
        with pytest.raises(TickerConfigError, match="secs must be positive, got -1.0"):
            Ticker(mock_logger, secs=-1.0)

    def test_init_creates_stop_event(self, mock_logger, mock_handler):
        """Test initialization creates stop event."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)
        assert isinstance(ticker._stop_event, threading.Event)
        assert not ticker._stop_event.is_set()

    def test_init_sets_first_flag(self, mock_logger, mock_handler):
        """Test initialization sets first tick flag."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)
        assert ticker._first is True

    def test_init_with_initial_parameter(self, mock_logger, mock_handler):
        """Test initialization with initial parameter."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0, initial=False)
        assert ticker._initial is False

    def _first_tick(
        self, mock_logger, monkeypatch, secs: float, initial: bool
    ) -> dict[str, Any]:
        """Run a ticker until its first tick. Return how long after run() it fired
        (``offset``), and what run() scheduled, waited for and slept before it."""
        start = time.monotonic()
        before: dict[str, Any] = {}

        class TimingHandler(TickerHandler):
            def ticker_tick(self):
                before["offset"] = time.monotonic() - start
                before["scheduled"] = list(delays)
                before["waited"] = [c.args[0] for c in waits.call_args_list]
                before["slept"] = list(sleeps.sleeps)
                ticker.stop()

        ticker = Ticker(mock_logger, TimingHandler(), secs=secs, initial=initial)
        delays = _recording_delays(ticker)
        sleeps, waits = _spy_on_waits(ticker, monkeypatch)
        ticker.run()
        return before

    def test_initial_false_skips_immediate_tick(self, mock_logger, clock, monkeypatch):
        """Test initial=False skips the immediate tick and waits for interval."""
        before = self._first_tick(mock_logger, monkeypatch, 0.5, initial=False)

        # The first tick was scheduled a full interval out, waited for no longer than that,
        # and came no earlier
        assert before["scheduled"] == [0.5]
        assert before["waited"] and all(w <= 0.5 for w in before["waited"])
        assert before["slept"] == []
        assert before["offset"] >= 0.5

    def test_initial_true_fires_immediately(self, mock_logger, clock, monkeypatch):
        """Test initial=True (default) fires the first tick without waiting an interval."""
        before = self._first_tick(mock_logger, monkeypatch, 0.5, initial=True)

        # Nothing was scheduled, waited for or slept before the first tick
        assert before["scheduled"] == []
        assert before["waited"] == []
        assert before["slept"] == []


# =============================================================================
# Test Scheduled Execution Mode
# =============================================================================


# =============================================================================
# Test Continuous Execution Mode
# =============================================================================


# =============================================================================
# Test Ticker Control Methods
# =============================================================================


class TestTickerControl:
    """Test ticker control methods."""

    def test_is_running_returns_false_initially(self, mock_logger, mock_handler):
        """Test is_running returns False initially."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)
        assert ticker.is_running() is False

    def test_get_status_returns_dict(self, mock_logger, mock_handler):
        """Test get_status returns status dictionary."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)
        status = ticker.get_status()

        assert isinstance(status, dict)
        assert "running" in status
        assert "mode" in status
        assert "interval" in status
        assert "first_tick" in status
        assert "stop_requested" in status

    def test_get_status_shows_scheduled_mode(self, mock_logger, mock_handler):
        """Test get_status shows scheduled mode."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)
        status = ticker.get_status()

        assert status["mode"] == "scheduled"
        assert status["interval"] == 1.0

    def test_get_status_shows_continuous_mode(self, mock_logger, mock_handler):
        """Test get_status shows continuous mode."""
        ticker = Ticker(mock_logger, mock_handler)
        status = ticker.get_status()

        assert status["mode"] == "continuous"
        assert status["interval"] is None

    def test_stop_calls_ticker_stop_when_run_ends_first(self, mock_logger):
        """Test ticker_stop() runs even if run() finishes as soon as stop() wakes it."""
        handler = Mock(spec=TickerHandler)
        ticker = Ticker(mock_logger, handler, secs=10)
        ticker._running = True

        # Stand in for a run() thread that wakes on the event and finishes,
        # clearing _running, before stop() gets to its handler call
        real_set = ticker._stop_event.set

        def set_and_finish():
            real_set()
            ticker._running = False

        ticker._stop_event.set = set_and_finish

        ticker.stop()

        handler.ticker_stop.assert_called_once()


# =============================================================================
# Test Integration Scenarios
# =============================================================================


class TestIntegrationScenarios:
    """Test real-world ticker scenarios."""

    def test_update_params_from_kwargs(self, mock_logger, mock_handler):
        """Test updating ticker params from kwargs."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)

        # Update params
        kwargs = {"ticker_secs": 2.0, "ticker_initial": False, "other": "value"}
        result = ticker._update_params_from_kwargs(kwargs)

        assert ticker._secs == 2.0
        assert ticker._initial is False
        assert "ticker_secs" not in result
        assert "ticker_initial" not in result
        assert result["other"] == "value"

    def test_ticker_handles_handler_start_error(self, mock_logger, mock_handler):
        """Test ticker handles error in ticker_start."""
        mock_handler.ticker_start.side_effect = Exception("start error")
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        with pytest.raises(TickerStateError, match="Ticker execution failed"):
            ticker.run()

        # Should not be running after error
        assert not ticker.is_running()


# =============================================================================
# Test Callable Wrapper
# =============================================================================


class TestCallableWrapper:
    """Test automatic wrapping of plain callables."""

    def test_handler_instance_not_wrapped(self, mock_logger, mock_handler):
        """Test that TickerHandler instances are not wrapped."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)

        # Should use handler directly
        assert ticker._handler is mock_handler


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_update_params_from_kwargs_unit(self, mock_logger, mock_handler):
        """Test updating ticker params from kwargs (unit test version)."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)

        # Update params
        kwargs = {"ticker_secs": 2.0, "ticker_initial": False, "other": "value"}
        result = ticker._update_params_from_kwargs(kwargs)

        assert ticker._secs == 2.0
        assert ticker._initial is False
        assert "ticker_secs" not in result
        assert "ticker_initial" not in result
        assert result["other"] == "value"

    def test_ticker_handles_handler_start_error_unit(self, mock_logger, mock_handler):
        """Test ticker handles error in ticker_start (unit test version)."""
        mock_handler.ticker_start.side_effect = Exception("start error")
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        with pytest.raises(TickerStateError, match="Ticker execution failed"):
            ticker.run()

        # Should not be running after error
        assert not ticker.is_running()

    def test_ticker_with_zero_interval(self, mock_logger, simple_handler):
        """Test ticker with zero second interval raises error."""
        # secs=0.0 is invalid - causes division by zero in STRICT mode
        # Use secs=None for continuous mode instead
        with pytest.raises(TickerConfigError, match="secs must be positive, got 0.0"):
            Ticker(mock_logger, simple_handler, secs=0.0)

    def test_ticker_stop_when_not_running(self, mock_logger, mock_handler):
        """Test stop when ticker is not running."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)

        # Should not raise
        ticker.stop()

        # Stop event should be set (allows stopping iterator mode before iteration)
        assert ticker._stop_event.is_set()

    def test_scheduled_tick_without_secs_raises_error(self, mock_logger, mock_handler):
        """Test _tick_sched raises error without secs."""
        ticker = Ticker(mock_logger, mock_handler)  # No secs
        ticker._secs = None

        with pytest.raises(
            TickerConfigError, match="Cannot schedule tick without secs"
        ):
            ticker._tick_sched()


# =============================================================================
# Test Iterator and Context Manager Support
# =============================================================================


class TestTickerIterator:
    """Test Ticker iterator functionality."""

    @pytest.mark.integration
    def test_yields_tick_count(self, mock_logger):
        """Verify ticker yields incrementing tick numbers."""
        ticks = []
        with Ticker(mock_logger, secs=0.01) as t:
            for tick in t:
                ticks.append(tick)
                if tick >= 2:
                    t.stop()
        assert ticks == [0, 1, 2]

    @pytest.mark.integration
    def test_initial_false_skips_first_tick(self, mock_logger):
        """Verify initial=False waits before first tick."""
        ticks = []
        start = time.time()
        with Ticker(mock_logger, secs=0.05, initial=False) as t:
            for tick in t:
                ticks.append((tick, time.time() - start))
                if tick >= 0:
                    t.stop()
        # First tick should be delayed by approximately secs
        assert len(ticks) == 1
        assert ticks[0][0] == 0
        assert ticks[0][1] >= 0.04  # Allow some tolerance

    @pytest.mark.integration
    def test_initial_true_fires_immediately(self, mock_logger):
        """Verify initial=True (default) fires tick immediately."""
        ticks = []
        start = time.time()
        with Ticker(mock_logger, secs=1.0) as t:  # Long interval
            for tick in t:
                ticks.append((tick, time.time() - start))
                t.stop()
        # First tick should be almost immediate
        assert len(ticks) == 1
        assert ticks[0][0] == 0
        assert ticks[0][1] < 0.5  # Should fire within 500ms

    def test_works_without_context_manager(self, mock_logger):
        """Verify iteration works without with statement."""
        ticks = []
        ticker = Ticker(mock_logger, secs=0.01)
        for tick in ticker:
            ticks.append(tick)
            if tick >= 2:
                ticker.stop()
        assert ticks == [0, 1, 2]

    def test_iter_requires_secs(self, mock_logger):
        """Test iterator mode requires secs parameter."""
        ticker = Ticker(mock_logger)  # No secs
        with pytest.raises(TickerConfigError, match="secs parameter required"):
            for _ in ticker:
                pass

    def test_stop_before_iteration(self, mock_logger):
        """Test stopping ticker before iteration starts."""
        ticker = Ticker(mock_logger, secs=0.01)
        ticker.stop()

        ticks = list(ticker)
        # Should not yield anything since stopped before iteration
        assert ticks == []


class TestTickerIteratorIntegration:
    """Integration tests for Ticker iterator with SubprocessContext pattern."""

    @pytest.mark.integration
    def test_multiple_ticks_with_timing(self, mock_logger):
        """Test ticker yields correct tick values in order."""
        ticks = []

        with Ticker(mock_logger, secs=0.05) as t:
            for tick in t:
                ticks.append(tick)
                if tick >= 2:
                    t.stop()

        # Should have 3 ticks with values 0, 1, 2
        assert ticks == [0, 1, 2]


# =============================================================================
# Test Non-Blocking API (try_tick / time_until_next_tick)
# =============================================================================


class TestNonBlockingAPI:
    """Test non-blocking API for manual tick control."""

    def test_time_until_next_tick_continuous_mode(self, mock_logger):
        """Test time_until_next_tick returns 0 in continuous mode."""
        ticker = Ticker(mock_logger, secs=None)
        assert ticker.time_until_next_tick() == 0.0

    def test_time_until_next_tick_first_tick_immediate(self, mock_logger):
        """Test time_until_next_tick returns 0 for first tick with initial=True."""
        ticker = Ticker(mock_logger, secs=1.0, initial=True)
        assert ticker.time_until_next_tick() == 0.0

    def test_time_until_next_tick_first_tick_delayed(self, mock_logger):
        """Test time_until_next_tick returns full interval for initial=False."""
        ticker = Ticker(mock_logger, secs=1.0, initial=False)
        assert ticker.time_until_next_tick() == 1.0

    def test_time_until_next_tick_not_started(self, mock_logger):
        """Test time_until_next_tick returns remaining time after a tick."""
        ticker = Ticker(mock_logger, secs=2.0)
        ticker.try_tick(now=T0)
        assert ticker.time_until_next_tick(now=T0 + 0.5) == 1.5

    def test_time_until_next_tick_with_now_parameter(self, mock_logger, clock):
        """Test time_until_next_tick accepts optional now parameter."""
        ticker = Ticker(mock_logger, secs=1.0)
        now = time.monotonic()
        ticker.try_tick(now=now)  # First tick

        time.sleep(0.25)

        # The captured time is answered as of then; the default reads the clock now,
        # between the readings around the call: 0.75 on the fake clock
        assert ticker.time_until_next_tick(now=now) == 1.0
        before = time.monotonic()
        remaining = ticker.time_until_next_tick()
        after = time.monotonic()
        assert max(0.0, now + 1.0 - after) <= remaining <= now + 1.0 - before

    def test_try_tick_returns_false_when_not_ready(self, mock_logger):
        """Test try_tick returns False when interval hasn't elapsed."""
        ticker = Ticker(mock_logger, secs=1.0)

        # First tick succeeds
        assert ticker.try_tick() is True

        # Immediate retry fails (not enough time elapsed)
        assert ticker.try_tick() is False

    def test_try_tick_returns_true_when_ready(self, mock_logger):
        """Test try_tick returns True once the interval has elapsed."""
        ticker = Ticker(mock_logger, secs=0.25)

        # First tick
        assert ticker.try_tick(now=T0) is True

        # Not yet: just short of the interval
        assert ticker.try_tick(now=T0 + 0.125) is False

        # Exactly at the interval the tick is due
        assert ticker.try_tick(now=T0 + 0.25) is True

    def test_try_tick_without_handler(self, mock_logger):
        """Test try_tick works without handler (timing oracle mode)."""
        ticker = Ticker(mock_logger, secs=0.25)

        # Should work without handler
        assert ticker.try_tick(now=T0) is True
        assert ticker.try_tick(now=T0 + 0.25) is True

    def test_try_tick_calls_handler(self, mock_logger, mock_handler):
        """Test try_tick calls handler when present."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.05)

        ticker.try_tick()
        ticker.try_tick()  # Too soon, shouldn't call

        # Handler should be called once (first tick)
        assert mock_handler.ticker_tick.call_count == 1

    def test_try_tick_calls_before_first_tick(self, mock_logger, mock_handler):
        """Test try_tick calls ticker_before_first_tick on first execution."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.05)

        ticker.try_tick()

        mock_handler.ticker_before_first_tick.assert_called_once()
        mock_handler.ticker_tick.assert_called_once()

    def test_try_tick_handles_handler_errors(self, mock_logger, mock_handler):
        """Test try_tick handles handler exceptions gracefully."""
        mock_handler.ticker_tick.side_effect = Exception("tick error")
        ticker = Ticker(mock_logger, mock_handler, secs=0.05)

        # Should not raise, returns True
        assert ticker.try_tick() is True

        # Error should be logged
        mock_logger.error.assert_called()

    def test_flex_mode_waits_full_interval(self, mock_logger):
        """Test FLEX mode maintains interval from tick start with no catch-up."""
        ticker = Ticker(mock_logger, secs=2.0, mode=TickerMode.FLEX)

        # First tick at t=0
        assert ticker.try_tick(now=T0) is True

        # Partway through the interval: next tick at t=2.0
        assert ticker.time_until_next_tick(now=T0 + 1.0) == 1.0

        # Tick late, at t=2.5
        assert ticker.try_tick(now=T0 + 2.5) is True

        # FLEX restarts the interval from this tick: a full 2.0s, no catch-up
        assert ticker.time_until_next_tick(now=T0 + 2.5) == 2.0

    def test_strict_mode_maintains_rate(self, mock_logger):
        """Test STRICT mode keeps the schedule: a late tick shortens the next wait."""
        ticker = Ticker(mock_logger, secs=2.0, mode=TickerMode.STRICT)

        # First tick at t=0
        assert ticker.try_tick(now=T0) is True

        # Partway through the interval: next tick at t=2.0
        assert ticker.time_until_next_tick(now=T0 + 1.0) == 1.0

        # Tick late, at t=2.5
        assert ticker.try_tick(now=T0 + 2.5) is True

        # Unlike FLEX, the next tick stays on schedule at t=4.0
        assert ticker.time_until_next_tick(now=T0 + 2.5) == 1.5

    def test_strict_mode_catches_up(self, mock_logger):
        """Test STRICT mode catches up when tasks run slow."""
        ticker = Ticker(mock_logger, secs=0.25, mode=TickerMode.STRICT)

        # First tick at t=0
        assert ticker.try_tick(now=T0) is True

        # Slow task: t=0.625, two scheduled ticks (0.25, 0.5) already due
        now = T0 + 0.625

        # Both due ticks fire back to back
        assert ticker.time_until_next_tick(now=now) == 0.0
        assert ticker.try_tick(now=now) is True
        assert ticker.time_until_next_tick(now=now) == 0.0
        assert ticker.try_tick(now=now) is True

        # Caught up: the tick at t=0.75 is the next one
        assert ticker.time_until_next_tick(now=now) == 0.125

    def test_no_drift_with_fast_ticks(self, mock_logger):
        """Test that rapid try_tick polling doesn't accumulate drift."""
        ticker = Ticker(mock_logger, secs=0.25, mode=TickerMode.FLEX)

        now = T0
        tick_times = []

        # Poll in steps that divide the interval exactly (binary fractions)
        for _ in range(5):
            while not ticker.try_tick(now=now):
                now += 1 / 64
            tick_times.append(now - T0)

        assert tick_times == [0.0, 0.25, 0.5, 0.75, 1.0]

    def test_mixed_event_source_pattern(self, mock_logger):
        """Test typical mixed event source usage pattern."""
        ticker = Ticker(mock_logger, secs=0.25)

        # Simulate event loop with mock channel
        messages = ["msg1", None, "msg2", None]  # None = timeout
        tick_count = 0
        msg_count = 0

        for msg in messages:
            # Use ticker for timeout calculation
            timeout = ticker.time_until_next_tick()
            assert timeout >= 0.0

            if msg:
                msg_count += 1

            # Try to tick
            if ticker.try_tick():
                tick_count += 1

        assert msg_count == 2
        assert tick_count >= 1  # At least one tick should have fired

    def test_initial_false_with_try_tick(self, mock_logger):
        """Test initial=False delays first tick in non-blocking API."""
        ticker = Ticker(mock_logger, secs=2.0, initial=False)

        # First call should not tick immediately; the full interval remains
        assert ticker.try_tick(now=T0) is False
        assert ticker.time_until_next_tick(now=T0) == 2.0

        # Partway: still not ready, half the interval left
        assert ticker.try_tick(now=T0 + 1.0) is False
        assert ticker.time_until_next_tick(now=T0 + 1.0) == 1.0

        # At the interval the first tick is due
        assert ticker.try_tick(now=T0 + 2.0) is True

    def test_initial_true_with_try_tick(self, mock_logger):
        """Test initial=True fires immediately in non-blocking API."""
        ticker = Ticker(mock_logger, secs=1.0, initial=True)

        # First call should tick immediately
        assert ticker.try_tick() is True

        # Next call should not be ready
        assert ticker.try_tick() is False

    def test_try_tick_with_now_parameter(self, mock_logger):
        """Test try_tick accepts optional now parameter."""
        ticker = Ticker(mock_logger, secs=0.25)

        # First tick
        assert ticker.try_tick(now=T0) is True

        # Using same timestamp should not tick (not enough time)
        assert ticker.try_tick(now=T0) is False

        # A timestamp one interval later ticks
        assert ticker.try_tick(now=T0 + 0.25) is True

    def test_shared_timestamp_pattern(self, mock_logger):
        """Test pattern of sharing timestamp between methods."""
        ticker = Ticker(mock_logger, secs=0.5)

        # First tick using shared timestamp
        assert ticker.time_until_next_tick(now=T0) == 0.0
        assert ticker.try_tick(now=T0) is True

        # Check again with same timestamp: a full interval from that moment
        assert ticker.time_until_next_tick(now=T0) == 0.5
        assert ticker.try_tick(now=T0) is False

    def test_spaced_mode_waits_from_completion(self, mock_logger, clock):
        """Test SPACED mode waits full interval from task completion."""

        def handler():
            time.sleep(0.25)  # The task takes at least 0.25s

        ticker = Ticker(mock_logger, handler, secs=1.0, mode=TickerMode.SPACED)

        start = time.monotonic()
        assert ticker.try_tick() is True
        done = time.monotonic()

        # The interval counts from the task's completion, which lies between start + 0.25
        # and done: a full interval is left at the first, at most one at the second
        assert ticker.time_until_next_tick(now=start + 0.25) >= 1.0
        assert ticker.time_until_next_tick(now=done) <= 1.0
        # One interval after the call returned, the next tick is due
        assert ticker.try_tick(now=done + 1.0) is True

    def test_spaced_mode_with_slow_task(self, mock_logger, clock):
        """Test SPACED mode waits from completion even for slow tasks."""

        def slow_handler():
            time.sleep(0.5)  # Longer than the 0.25s interval

        ticker = Ticker(mock_logger, slow_handler, secs=0.25, mode=TickerMode.SPACED)

        start = time.monotonic()
        assert ticker.try_tick() is True
        done = time.monotonic()

        # The interval counts from completion, not from the tick start: a whole
        # interval after the start the task had not even finished. Completion lies
        # between start + 0.5 and done
        assert ticker.time_until_next_tick(now=start + 0.5) >= 0.25
        assert ticker.time_until_next_tick(now=done) <= 0.25
        assert ticker.try_tick(now=done + 0.25) is True

    def test_spaced_vs_flex_comparison(self, mock_logger, clock):
        """Test difference between SPACED and FLEX modes with task execution time."""

        def handler():
            time.sleep(0.25)  # Each task takes at least 0.25s

        flex_ticker = Ticker(mock_logger, handler, secs=1.0, mode=TickerMode.FLEX)
        spaced_ticker = Ticker(mock_logger, handler, secs=1.0, mode=TickerMode.SPACED)

        # FLEX counts the interval from the tick's start, before the handler; SPACED from
        # the handler's completion
        flex_start = time.monotonic()
        assert flex_ticker.try_tick() is True
        flex_done = time.monotonic()
        spaced_start = time.monotonic()
        assert spaced_ticker.try_tick() is True
        spaced_done = time.monotonic()

        # FLEX's reference lies between flex_start and flex_done - 0.25, the handler's
        # time before the call returned; counted from completion it would be later
        assert flex_ticker.time_until_next_tick(now=flex_start) >= 1.0
        assert flex_ticker.time_until_next_tick(now=flex_done - 0.25) <= 1.0
        # SPACED's lies between spaced_start + 0.25 and spaced_done
        assert spaced_ticker.time_until_next_tick(now=spaced_start + 0.25) >= 1.0
        assert spaced_ticker.time_until_next_tick(now=spaced_done) <= 1.0

    def test_spaced_mode_guarantees_minimum_spacing(self, mock_logger, clock):
        """Test SPACED mode guarantees minimum spacing between operations."""
        ticker = Ticker(mock_logger, secs=0.5, mode=TickerMode.SPACED)

        calls = []  # (before, after) each tick's try_tick()

        for _ in range(3):
            # Poll in steps that divide the interval exactly (binary fractions)
            while True:
                before = time.monotonic()
                if ticker.try_tick():
                    break
                time.sleep(1 / 64)
            after = time.monotonic()
            calls.append((before, after))

            # The tick completed within the call, and the interval counts from there
            assert ticker.time_until_next_tick(now=before) >= 0.5
            assert ticker.time_until_next_tick(now=after) <= 0.5

            # The task after the tick takes 0.125s
            time.sleep(0.125)

        # Each tick completed no earlier than its call began, and the next one comes at
        # least an interval after that
        gaps = [calls[i + 1][1] - calls[i][0] for i in range(len(calls) - 1)]
        assert all(gap >= 0.5 for gap in gaps), gaps

    def test_spaced_mode_handles_exceptions(self, mock_logger, clock):
        """Test SPACED mode handles handler exceptions and maintains spacing."""
        from unittest.mock import Mock

        # Handler that raises on first call, succeeds on second
        handler = Mock(side_effect=[Exception("boom"), None, None])
        ticker = Ticker(mock_logger, handler, secs=0.5, mode=TickerMode.SPACED)

        # First tick should not raise (exception caught)
        start = time.monotonic()
        assert ticker.try_tick() is True
        done = time.monotonic()

        # Exception should be logged
        assert mock_logger.error.called

        # Should still maintain spacing even after exception: the interval counts from
        # the failed task's completion, between start and done
        assert ticker.time_until_next_tick(now=start) >= 0.5
        assert ticker.time_until_next_tick(now=done) <= 0.5

        # Wait for next tick
        time.sleep(0.5)

        # Second tick should succeed
        assert ticker.try_tick() is True

        # Handler should have been called twice total
        assert handler.call_count == 2

    def test_cannot_mix_try_tick_and_run(self, mock_logger, mock_handler):
        """Test that mixing try_tick() and run() raises RuntimeError."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        # Use try_tick() first
        ticker.try_tick()

        # Attempting to use run() should raise
        with pytest.raises(
            TickerAPIError, match="Cannot call run.*after using try_tick"
        ):
            ticker.run()

    def test_cannot_mix_try_tick_and_iterator(self, mock_logger):
        """Test that mixing try_tick() and iterator raises RuntimeError."""
        ticker = Ticker(mock_logger, secs=0.1)

        # Use try_tick() first
        ticker.try_tick()

        # Attempting to use iterator should raise when starting iteration
        with pytest.raises(TickerAPIError, match="Cannot use iterator after.*try_tick"):
            it = iter(ticker)
            next(it)  # Exception raised on first iteration

    def test_time_until_next_tick_no_side_effects(self, mock_logger):
        """Test that time_until_next_tick() doesn't mutate state (query method invariant)."""
        ticker = Ticker(mock_logger, secs=1.0, initial=False)

        # Call time_until_next_tick() with different timestamps: this should NOT affect
        # the timing state, so both return the full interval
        assert ticker.time_until_next_tick(now=T0) == 1.0
        assert ticker.time_until_next_tick(now=T0 + 0.25) == 1.0

        # Now call try_tick() which WILL initialize the state
        result = ticker.try_tick(now=T0 + 0.25)
        assert result is False  # Not ready yet (initial=False requires full interval)

        # After initialization the interval counts from T0 + 0.25
        assert ticker.time_until_next_tick(now=T0 + 0.5) == 0.75

    def test_validates_negative_now_parameter(self, mock_logger):
        """Test that negative 'now' parameter triggers warning."""
        ticker = Ticker(mock_logger, secs=1.0)

        # Pass negative timestamp - should warn
        ticker.time_until_next_tick(now=-1.0)

        # Check warning was logged
        assert mock_logger.warning.called
        call_args = mock_logger.warning.call_args
        assert "negative value" in call_args[0][0]

    def test_validates_past_now_parameter(self, mock_logger):
        """Test that 'now' far in past triggers warning."""
        ticker = Ticker(mock_logger, secs=1.0)

        # Initialize ticker with a normal timestamp
        now = time.monotonic()
        ticker.try_tick(now=now)

        # Pass timestamp far in the past - should warn
        past_time = now - 20.0  # 20 seconds in the past (> 10s threshold)
        ticker.try_tick(now=past_time)

        # Check warning was logged
        assert mock_logger.warning.called
        warnings = [call[0][0] for call in mock_logger.warning.call_args_list]
        assert any("far in past" in msg for msg in warnings)


# =============================================================================
# Test Blocking API Timing Modes (run() with FLEX/STRICT/SPACED)
# =============================================================================


class TestBlockingAPITimingModes:
    """Test that blocking API (run()) respects timing modes."""

    # These run Ticker.run() in the test's own thread, its waits on the fake clock, and
    # the handler stops the ticker after the ticks the test needs. A handler records its
    # start after the ticker's own reading and its end before the ticker's, so a tick is
    # never earlier than the schedule computed from those readings.

    def test_blocking_flex_mode_no_catchup(self, mock_logger, clock, monkeypatch):
        """Test FLEX mode in blocking API doesn't catch up after slow tasks."""
        starts: list[float] = []
        ends: list[float] = []

        def slow_handler():
            starts.append(time.monotonic())
            if len(starts) == 2:
                time.sleep(0.5)  # Slow task, longer than the interval
            ends.append(time.monotonic())
            if len(starts) == 3:
                ticker.stop()

        ticker = Ticker(mock_logger, slow_handler, secs=0.25, mode=TickerMode.FLEX)
        delays = _recording_delays(ticker)
        sleeps, waits = _spy_on_waits(ticker, monkeypatch)
        start = time.monotonic()
        ticker.run()

        assert len(starts) == 3
        assert starts[1] >= start + 0.25
        # Tick 2 ended late; FLEX waits a full interval from there instead of firing
        # the missed tick at once
        assert starts[2] >= ends[1] + 0.25
        # What run() scheduled: at most an interval after the first tick, then a full
        # interval from each late tick's end; and it waited no longer than it scheduled
        assert delays[0] <= 0.25
        assert delays[1:] == [0.25, 0.25]
        assert all(c.args[0] <= max(delays) for c in waits.call_args_list)
        assert sleeps.sleeps == []

    def test_blocking_strict_mode_catches_up(self, mock_logger, clock, monkeypatch):
        """Test STRICT mode in blocking API catches up after slow tasks."""
        starts: list[float] = []
        ends: list[float] = []

        def slow_handler():
            starts.append(time.monotonic())
            if len(starts) == 2:
                time.sleep(0.625)  # Very slow task: two ticks fall due meanwhile
            ends.append(time.monotonic())
            if len(starts) == 5:
                ticker.stop()

        ticker = Ticker(mock_logger, slow_handler, secs=0.25, mode=TickerMode.STRICT)
        delays = _recording_delays(ticker)
        sleeps, waits = _spy_on_waits(ticker, monkeypatch)
        start = time.monotonic()
        ticker.run()

        # Tick k is due k intervals after the first, and none comes earlier
        assert len(starts) == 5
        assert all(t >= start + k * 0.25 for k, t in enumerate(starts)), starts
        # The ticks due during the slow task fire back to back, with no delay; then the
        # schedule resumes, the next tick at most what is left to its slot. And run()
        # waited no longer than it scheduled
        assert delays[0] <= 0.25
        assert delays[1:3] == [0.0, 0.0]
        assert delays[3] <= max(0.0, starts[0] + 1.0 - ends[3])
        assert all(c.args[0] <= max(delays) for c in waits.call_args_list)
        assert sleeps.sleeps == []

    def test_blocking_spaced_mode_guarantees_spacing(
        self, mock_logger, clock, monkeypatch
    ):
        """Test SPACED mode in blocking API guarantees spacing from completion."""
        starts: list[float] = []
        ends: list[float] = []

        def varying_handler():
            starts.append(time.monotonic())
            # Variable task duration: tick 2 is long
            time.sleep(0.25 if len(starts) == 2 else 0.0625)
            ends.append(time.monotonic())
            if len(starts) == 4:
                ticker.stop()

        ticker = Ticker(mock_logger, varying_handler, secs=0.25, mode=TickerMode.SPACED)
        delays = _recording_delays(ticker)
        sleeps, waits = _spy_on_waits(ticker, monkeypatch)
        ticker.run()

        # Every tick starts at least one interval after the previous one completed; run()
        # scheduled exactly one interval after each, and waited no longer than that
        gaps = [starts[i + 1] - ends[i] for i in range(3)]
        assert all(gap >= 0.25 for gap in gaps), gaps
        assert delays == [0.25] * 4
        assert all(c.args[0] <= 0.25 for c in waits.call_args_list)
        assert sleeps.sleeps == []


class TestNextTickDelay:
    """run()'s delay to the next tick, from a tick's start and end times; no clock read."""

    def _delays(
        self, mock_logger, mode: TickerMode, ticks: list[tuple[float, float]]
    ) -> list[float]:
        """The delays a 1s ticker in ``mode`` computes after each (start, end) tick."""
        ticker = Ticker(mock_logger, secs=1.0, mode=mode)
        return [ticker._calculate_next_tick_delay(T0 + s, T0 + e) for s, e in ticks]

    def test_flex_keeps_the_interval_from_the_start_and_resets_when_late(
        self, mock_logger
    ):
        # On time: the rest of the interval from the start; late (the second tick ends
        # at 2.5, past its successor's 2.0): a full interval from the end, no catch-up
        delays = self._delays(mock_logger, TickerMode.FLEX, [(0.0, 0.25), (1.0, 2.5)])
        assert delays == [0.75, 1.0]

    def test_strict_catches_up_back_to_back(self, mock_logger):
        # The first tick runs 2.5s: ticks due at 1.0 and 2.0 fire at once, then the
        # schedule resumes at 3.0
        delays = self._delays(
            mock_logger, TickerMode.STRICT, [(0.0, 2.5), (2.5, 2.5), (2.5, 2.75)]
        )
        assert delays == [0.0, 0.0, 0.25]

    def test_spaced_waits_a_full_interval_from_the_end(self, mock_logger):
        delays = self._delays(mock_logger, TickerMode.SPACED, [(0.0, 0.5), (1.5, 3.0)])
        assert delays == [1.0, 1.0]


class TestPickling:
    """A ticker crosses a spawn/forkserver process boundary by pickling."""

    @pytest.mark.parametrize("secs", [1.0, None])
    def test_round_trip_gets_fresh_sync_objects(self, secs):
        """The copy works and has its own event, lock and scheduler."""
        ticker = Ticker(create_lg("ticker-pickle", "info"), print, secs=secs)
        ticker.stop()

        copy = pickle.loads(pickle.dumps(ticker))

        assert copy._stop_event is not ticker._stop_event
        assert not copy._stop_event.is_set()
        assert copy._lifecycle.acquire(blocking=False)
        assert (copy._sched is None) == (secs is None)
        assert copy._secs == secs
