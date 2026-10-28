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
import threading
import time
from unittest.mock import Mock

import pytest

from appinfra.errors import TickerAPIError, TickerConfigError, TickerStateError
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


# =============================================================================
# Test TickerHandler Interface
# =============================================================================


@pytest.mark.unit
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


@pytest.mark.unit
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

    def _first_tick_offset(self, mock_logger, fake_clock, initial: bool) -> float:
        """Run a 1s ticker on the fake clock; return when its first tick fired."""
        start = fake_clock.monotonic()
        tick_times: list[float] = []

        class TimingHandler(TickerHandler):
            def ticker_tick(self):
                tick_times.append(fake_clock.monotonic() - start)
                ticker.stop()

        ticker = Ticker(mock_logger, TimingHandler(), secs=1, initial=initial)
        ticker.run()
        return tick_times[0]

    def test_initial_false_skips_immediate_tick(self, mock_logger, fake_clock):
        """Test initial=False skips the immediate tick and waits for interval."""
        assert self._first_tick_offset(mock_logger, fake_clock, initial=False) == 1.0

    def test_initial_true_fires_immediately(self, mock_logger, fake_clock):
        """Test initial=True (default) fires tick immediately on start."""
        assert self._first_tick_offset(mock_logger, fake_clock, initial=True) == 0.0


# =============================================================================
# Test Scheduled Execution Mode
# =============================================================================


@pytest.mark.unit
class TestScheduledMode:
    """Test scheduled execution mode."""

    def test_scheduled_mode_calls_ticker_start(self, mock_logger, mock_handler):
        """Test scheduled mode calls ticker_start."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        # Run in thread and stop quickly
        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.05)
        ticker.stop()
        thread.join(timeout=1.0)

        mock_handler.ticker_start.assert_called_once()

    def test_scheduled_mode_calls_before_first_tick(self, mock_logger, mock_handler):
        """Test scheduled mode calls ticker_before_first_tick."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.15)  # Wait for first tick
        ticker.stop()
        thread.join(timeout=1.0)

        mock_handler.ticker_before_first_tick.assert_called_once()

    def test_scheduled_mode_executes_multiple_ticks(self, mock_logger, simple_handler):
        """Test scheduled mode executes multiple ticks."""
        ticker = Ticker(mock_logger, simple_handler, secs=0.05)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.25)  # Allow multiple ticks
        ticker.stop()
        thread.join(timeout=1.0)

        # Should have executed multiple ticks
        assert simple_handler.tick_count >= 2

    def test_scheduled_mode_calls_ticker_stop(self, mock_logger, mock_handler):
        """Test scheduled mode calls ticker_stop on cleanup."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.05)
        ticker.stop()
        thread.join(timeout=1.0)

        mock_handler.ticker_stop.assert_called_once()

    def test_scheduled_mode_handles_ticker_before_first_tick_error(
        self, mock_logger, mock_handler
    ):
        """Test scheduled mode handles errors in ticker_before_first_tick."""
        mock_handler.ticker_before_first_tick.side_effect = Exception(
            "before first tick error"
        )
        ticker = Ticker(mock_logger, mock_handler, secs=0.05)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.15)  # Wait for first tick and error
        ticker.stop()
        thread.join(timeout=1.0)

        # Should have called ticker_before_first_tick once
        mock_handler.ticker_before_first_tick.assert_called_once()
        # Should have logged the exception
        mock_logger.error.assert_called()
        # Ticker should continue and call ticker_tick despite error
        assert mock_handler.ticker_tick.call_count >= 1

    def test_scheduled_mode_handles_ticker_tick_error(self, mock_logger, mock_handler):
        """Test scheduled mode handles errors in ticker_tick."""
        mock_handler.ticker_tick.side_effect = Exception("tick error")
        ticker = Ticker(mock_logger, mock_handler, secs=0.05)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.15)  # Allow multiple attempts
        ticker.stop()
        thread.join(timeout=1.0)

        # Should have called ticker_tick multiple times despite errors
        assert mock_handler.ticker_tick.call_count >= 1

    def test_scheduled_mode_stops_gracefully(self, mock_logger, simple_handler):
        """Test scheduled mode stops gracefully."""
        ticker = Ticker(mock_logger, simple_handler, secs=0.1)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.05)

        initial_count = simple_handler.tick_count
        ticker.stop()
        thread.join(timeout=1.0)

        # Should stop cleanly
        assert simple_handler.stopped is True
        assert not ticker.is_running()


# =============================================================================
# Test Continuous Execution Mode
# =============================================================================


@pytest.mark.unit
class TestContinuousMode:
    """Test continuous execution mode."""

    def test_continuous_mode_calls_ticker_start(self, mock_logger, mock_handler):
        """Test continuous mode calls ticker_start."""
        ticker = Ticker(mock_logger, mock_handler)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.01)
        ticker.stop()
        thread.join(timeout=1.0)

        mock_handler.ticker_start.assert_called_once()

    def test_continuous_mode_calls_before_first_tick(self, mock_logger, mock_handler):
        """Test continuous mode calls ticker_before_first_tick."""
        ticker = Ticker(mock_logger, mock_handler)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.01)
        ticker.stop()
        thread.join(timeout=1.0)

        mock_handler.ticker_before_first_tick.assert_called_once()

    def test_continuous_mode_executes_many_ticks(self, mock_logger, simple_handler):
        """Test continuous mode executes many ticks rapidly."""
        ticker = Ticker(mock_logger, simple_handler)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.1)  # Short time but should execute many ticks
        ticker.stop()
        thread.join(timeout=1.0)

        # Continuous mode should execute many times
        assert simple_handler.tick_count > 10

    def test_continuous_mode_stops_on_stop_event(self, mock_logger, simple_handler):
        """Test continuous mode stops when stop event is set."""
        ticker = Ticker(mock_logger, simple_handler)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.05)
        ticker.stop()
        thread.join(timeout=1.0)

        # Should have stopped
        assert ticker._stop_event.is_set()
        assert simple_handler.stopped is True

    def test_continuous_mode_handles_ticker_tick_error(self, mock_logger, mock_handler):
        """Test continuous mode handles errors in ticker_tick."""
        # First few calls raise error, then we stop
        call_count = [0]

        def side_effect():
            call_count[0] += 1
            if call_count[0] < 5:
                raise Exception("tick error")

        mock_handler.ticker_tick.side_effect = side_effect
        ticker = Ticker(mock_logger, mock_handler)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.01)
        ticker.stop()
        thread.join(timeout=1.0)

        # Should have called ticker_tick multiple times despite errors
        assert mock_handler.ticker_tick.call_count >= 1

    def test_continuous_mode_calls_ticker_stop(self, mock_logger, mock_handler):
        """Test continuous mode calls ticker_stop on cleanup."""
        ticker = Ticker(mock_logger, mock_handler)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.01)
        ticker.stop()
        thread.join(timeout=1.0)

        mock_handler.ticker_stop.assert_called_once()


# =============================================================================
# Test Ticker Control Methods
# =============================================================================


@pytest.mark.unit
class TestTickerControl:
    """Test ticker control methods."""

    def test_is_running_returns_false_initially(self, mock_logger, mock_handler):
        """Test is_running returns False initially."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)
        assert ticker.is_running() is False

    def test_is_running_returns_true_while_running(self, mock_logger, mock_handler):
        """Test is_running returns True while running."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.05)

        assert ticker.is_running() is True

        ticker.stop()
        thread.join(timeout=1.0)

    def test_is_running_returns_false_after_stop(self, mock_logger, mock_handler):
        """Test is_running returns False after stopping."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.05)
        ticker.stop()
        thread.join(timeout=1.0)

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

    def test_get_status_shows_running_state(self, mock_logger, mock_handler):
        """Test get_status shows running state."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        # Initially not running
        status = ticker.get_status()
        assert status["running"] is False

        # Start ticker
        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.05)

        # Should be running
        status = ticker.get_status()
        assert status["running"] is True

        ticker.stop()
        thread.join(timeout=1.0)

    def test_run_raises_if_already_running(self, mock_logger, mock_handler):
        """Test run raises RuntimeError if already running."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.05)

        # Try to run again
        with pytest.raises(TickerStateError, match="already running"):
            ticker.run()

        ticker.stop()
        thread.join(timeout=1.0)

    def test_stop_cancels_scheduled_events(self, mock_logger, mock_handler):
        """Test stop wakes run() mid-interval and cancels pending events."""
        # Real time and a real thread: stop() comes from another thread while
        # run() waits out a 10s interval
        ticker = Ticker(mock_logger, mock_handler, secs=10, initial=True)
        # run() clears the stop event on entry; waiting for the first tick
        # (initial=True) guarantees stop() comes after that, not before
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set

        thread = threading.Thread(target=ticker.run, daemon=True)
        thread.start()
        assert ticked.wait(timeout=1.0)

        # Stop before next tick
        ticker.stop()
        thread.join(timeout=1.0)

        assert not thread.is_alive()
        assert ticker._sched.queue == []

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

    def test_stop_from_handler_ends_run(self, mock_logger):
        """Test stop() during a tick drops the tick queued after it."""
        # The tick queues its successor after stop() returns; run() must drop it
        # rather than wait for (or spin until) its deadline. A real thread, so a
        # regression fails the join instead of hanging the test
        handler = Mock(spec=TickerHandler)
        ticker = Ticker(mock_logger, handler, secs=10, initial=True)
        handler.ticker_tick.side_effect = ticker.stop

        thread = threading.Thread(target=ticker.run, daemon=True)
        thread.start()
        thread.join(timeout=1.0)

        assert not thread.is_alive()
        assert handler.ticker_tick.call_count == 1
        assert ticker._sched.queue == []


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestIntegrationScenarios:
    """Test real-world ticker scenarios."""

    def test_ticker_with_args_and_kwargs(self, mock_logger, mock_handler):
        """Test ticker passes args and kwargs to handler."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        def run_and_stop():
            ticker.run("arg1", "arg2", key="value")

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.05)
        ticker.stop()
        thread.join(timeout=1.0)

        mock_handler.ticker_start.assert_called_once_with("arg1", "arg2", key="value")

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


@pytest.mark.unit
class TestCallableWrapper:
    """Test automatic wrapping of plain callables."""

    def test_callable_is_wrapped_in_handler(self, mock_logger):
        """Test that a plain callable is wrapped in a TickerHandler."""
        call_count = [0]

        def my_tick():
            call_count[0] += 1

        ticker = Ticker(mock_logger, my_tick, secs=0.05)

        # Handler should be wrapped
        from appinfra.time.ticker import _CallableWrapper

        assert isinstance(ticker._handler, _CallableWrapper)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.1)
        ticker.stop()
        thread.join(timeout=1.0)

        # Should have executed the callable
        assert call_count[0] >= 1

    def test_lambda_is_wrapped(self, mock_logger):
        """Test that a lambda is wrapped in a TickerHandler."""
        results = []

        ticker = Ticker(mock_logger, lambda: results.append("tick"), secs=0.05)

        from appinfra.time.ticker import _CallableWrapper

        assert isinstance(ticker._handler, _CallableWrapper)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.1)
        ticker.stop()
        thread.join(timeout=1.0)

        assert len(results) >= 1
        assert results[0] == "tick"

    def test_callable_in_continuous_mode(self, mock_logger):
        """Test callable works in continuous mode."""
        call_count = [0]

        def my_tick():
            call_count[0] += 1

        ticker = Ticker(mock_logger, my_tick)  # No secs = continuous

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.05)
        ticker.stop()
        thread.join(timeout=1.0)

        # Continuous mode should execute many times
        assert call_count[0] > 10

    def test_handler_instance_not_wrapped(self, mock_logger, mock_handler):
        """Test that TickerHandler instances are not wrapped."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)

        # Should use handler directly
        assert ticker._handler is mock_handler


# =============================================================================
# Test Edge Cases
# =============================================================================


@pytest.mark.unit
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

    def test_ticker_stop_handles_handler_stop_error(self, mock_logger, mock_handler):
        """Test ticker handles error in ticker_stop gracefully."""
        mock_handler.ticker_stop.side_effect = Exception("stop error")
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.05)
        ticker.stop()
        # Should not raise, error is caught
        thread.join(timeout=1.0)

    def test_first_flag_reset_after_first_tick(self, mock_logger, mock_handler):
        """Test first flag is reset after first tick."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.05)
        assert ticker._first is True

        def run_and_stop():
            ticker.run()

        thread = threading.Thread(target=run_and_stop, daemon=True)
        thread.start()
        time.sleep(0.1)  # Wait for first tick
        ticker.stop()
        thread.join(timeout=1.0)

        assert ticker._first is False


# =============================================================================
# Test Iterator and Context Manager Support
# =============================================================================


@pytest.mark.unit
class TestTickerIterator:
    """Test Ticker iterator functionality."""

    def test_yields_tick_count(self, mock_logger):
        """Verify ticker yields incrementing tick numbers."""
        ticks = []
        with Ticker(mock_logger, secs=0.01) as t:
            for tick in t:
                ticks.append(tick)
                if tick >= 2:
                    t.stop()
        assert ticks == [0, 1, 2]

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


@pytest.mark.unit
class TestTickerContextManager:
    """Test Ticker context manager functionality."""

    def test_context_manager_installs_signal_handlers(self, mock_logger):
        """Verify context manager installs signal handlers."""
        import signal as sig

        original_sigterm = sig.getsignal(sig.SIGTERM)
        original_sigint = sig.getsignal(sig.SIGINT)

        with Ticker(mock_logger, secs=1.0) as ticker:
            # Signal handlers should be installed
            current_sigterm = sig.getsignal(sig.SIGTERM)
            current_sigint = sig.getsignal(sig.SIGINT)
            assert current_sigterm != original_sigterm
            assert current_sigint != original_sigint
            ticker.stop()

        # Signal handlers should be restored
        assert sig.getsignal(sig.SIGTERM) == original_sigterm
        assert sig.getsignal(sig.SIGINT) == original_sigint

    def test_context_manager_restores_handlers_on_exception(self, mock_logger):
        """Verify signal handlers are restored even on exception."""
        import signal as sig

        original_sigterm = sig.getsignal(sig.SIGTERM)

        try:
            with Ticker(mock_logger, secs=1.0):
                raise ValueError("test error")
        except ValueError:
            pass

        # Signal handlers should be restored
        assert sig.getsignal(sig.SIGTERM) == original_sigterm

    def test_signal_handler_sets_stop_event(self, mock_logger):
        """Verify signal handler sets stop event when called."""
        ticker = Ticker(mock_logger, secs=1.0)

        with ticker:
            # Manually invoke the signal handler (simulating signal delivery)
            ticker._handle_iter_signal(15, None)  # 15 = SIGTERM

            # Stop event should be set
            assert ticker._stop_event.is_set()

        # Logger should have logged the signal
        mock_logger.debug.assert_called()

    def test_nested_context_managers(self, mock_logger):
        """Test nested ticker context managers restore handlers correctly."""
        import signal as sig

        original_sigterm = sig.getsignal(sig.SIGTERM)

        with Ticker(mock_logger, secs=1.0) as outer:
            outer_handler = sig.getsignal(sig.SIGTERM)

            with Ticker(mock_logger, secs=1.0) as inner:
                inner_handler = sig.getsignal(sig.SIGTERM)
                # Inner should have its own handler
                assert inner_handler != outer_handler
                inner.stop()

            # After inner exits, outer's handler should be restored
            assert sig.getsignal(sig.SIGTERM) == outer_handler
            outer.stop()

        # After outer exits, original handler should be restored
        assert sig.getsignal(sig.SIGTERM) == original_sigterm


@pytest.mark.integration
class TestTickerIteratorIntegration:
    """Integration tests for Ticker iterator with SubprocessContext pattern."""

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

    def test_callback_and_iterator_are_separate_modes(self, mock_logger):
        """Test that callback mode and iterator mode are independent."""
        # Callback mode
        call_count = [0]
        ticker1 = Ticker(
            mock_logger, lambda: call_count.__setitem__(0, call_count[0] + 1), secs=0.01
        )
        thread = threading.Thread(target=ticker1.run, daemon=True)
        thread.start()
        time.sleep(0.05)
        ticker1.stop()
        thread.join(timeout=1.0)
        assert call_count[0] >= 1

        # Iterator mode (no handler)
        iter_count = 0
        ticker2 = Ticker(mock_logger, secs=0.01)
        for tick in ticker2:
            iter_count += 1
            if tick >= 2:
                ticker2.stop()
        assert iter_count == 3


# =============================================================================
# Test Non-Blocking API (try_tick / time_until_next_tick)
# =============================================================================


@pytest.mark.unit
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

    def test_time_until_next_tick_not_started(self, mock_logger, fake_clock):
        """Test time_until_next_tick returns remaining time after a tick."""
        ticker = Ticker(mock_logger, secs=2.0)
        ticker.try_tick()
        fake_clock.sleep(0.5)
        assert ticker.time_until_next_tick() == 1.5

    def test_time_until_next_tick_with_now_parameter(self, mock_logger, fake_clock):
        """Test time_until_next_tick accepts optional now parameter."""
        ticker = Ticker(mock_logger, secs=1.0)
        ticker.try_tick()  # First tick

        now = fake_clock.monotonic()
        fake_clock.sleep(0.25)

        # The captured time is answered as of then; the default reads the clock now
        assert ticker.time_until_next_tick(now=now) == 1.0
        assert ticker.time_until_next_tick() == 0.75

    def test_try_tick_returns_false_when_not_ready(self, mock_logger):
        """Test try_tick returns False when interval hasn't elapsed."""
        ticker = Ticker(mock_logger, secs=1.0)

        # First tick succeeds
        assert ticker.try_tick() is True

        # Immediate retry fails (not enough time elapsed)
        assert ticker.try_tick() is False

    def test_try_tick_returns_true_when_ready(self, mock_logger, fake_clock):
        """Test try_tick returns True once the interval has elapsed."""
        ticker = Ticker(mock_logger, secs=0.25)

        # First tick
        assert ticker.try_tick() is True

        # Not yet: just short of the interval
        fake_clock.sleep(0.125)
        assert ticker.try_tick() is False

        # Exactly at the interval the tick is due
        fake_clock.sleep(0.125)
        assert ticker.try_tick() is True

    def test_try_tick_without_handler(self, mock_logger, fake_clock):
        """Test try_tick works without handler (timing oracle mode)."""
        ticker = Ticker(mock_logger, secs=0.25)

        # Should work without handler
        assert ticker.try_tick() is True
        fake_clock.sleep(0.25)
        assert ticker.try_tick() is True

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

    def test_flex_mode_waits_full_interval(self, mock_logger, fake_clock):
        """Test FLEX mode maintains interval from tick start with no catch-up."""
        ticker = Ticker(mock_logger, secs=2.0, mode=TickerMode.FLEX)

        # First tick at t=0
        assert ticker.try_tick() is True

        # Partway through the interval: next tick at t=2.0
        fake_clock.sleep(1.0)
        assert ticker.time_until_next_tick() == 1.0

        # Tick late, at t=2.5
        fake_clock.sleep(1.5)
        assert ticker.try_tick() is True

        # FLEX restarts the interval from this tick: a full 2.0s, no catch-up
        assert ticker.time_until_next_tick() == 2.0

    def test_strict_mode_maintains_rate(self, mock_logger, fake_clock):
        """Test STRICT mode keeps the schedule: a late tick shortens the next wait."""
        ticker = Ticker(mock_logger, secs=2.0, mode=TickerMode.STRICT)

        # First tick at t=0
        assert ticker.try_tick() is True

        # Partway through the interval: next tick at t=2.0
        fake_clock.sleep(1.0)
        assert ticker.time_until_next_tick() == 1.0

        # Tick late, at t=2.5
        fake_clock.sleep(1.5)
        assert ticker.try_tick() is True

        # Unlike FLEX, the next tick stays on schedule at t=4.0
        assert ticker.time_until_next_tick() == 1.5

    def test_strict_mode_catches_up(self, mock_logger, fake_clock):
        """Test STRICT mode catches up when tasks run slow."""
        ticker = Ticker(mock_logger, secs=0.25, mode=TickerMode.STRICT)

        # First tick at t=0
        assert ticker.try_tick() is True

        # Slow task: t=0.625, two scheduled ticks (0.25, 0.5) already due
        fake_clock.sleep(0.625)

        # Both due ticks fire back to back
        assert ticker.time_until_next_tick() == 0.0
        assert ticker.try_tick() is True
        assert ticker.time_until_next_tick() == 0.0
        assert ticker.try_tick() is True

        # Caught up: the tick at t=0.75 is the next one
        assert ticker.time_until_next_tick() == 0.125

    def test_no_drift_with_fast_ticks(self, mock_logger, fake_clock):
        """Test that rapid try_tick polling doesn't accumulate drift."""
        ticker = Ticker(mock_logger, secs=0.25, mode=TickerMode.FLEX)

        start = fake_clock.monotonic()
        tick_times = []

        # Poll in steps that divide the interval exactly (binary fractions)
        for _ in range(5):
            while not ticker.try_tick():
                fake_clock.sleep(1 / 64)
            tick_times.append(fake_clock.monotonic() - start)

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

    def test_initial_false_with_try_tick(self, mock_logger, fake_clock):
        """Test initial=False delays first tick in non-blocking API."""
        ticker = Ticker(mock_logger, secs=2.0, initial=False)

        # First call should not tick immediately; the full interval remains
        assert ticker.try_tick() is False
        assert ticker.time_until_next_tick() == 2.0

        # Partway: still not ready, half the interval left
        fake_clock.sleep(1.0)
        assert ticker.try_tick() is False
        assert ticker.time_until_next_tick() == 1.0

        # At the interval the first tick is due
        fake_clock.sleep(1.0)
        assert ticker.try_tick() is True

    def test_initial_true_with_try_tick(self, mock_logger):
        """Test initial=True fires immediately in non-blocking API."""
        ticker = Ticker(mock_logger, secs=1.0, initial=True)

        # First call should tick immediately
        assert ticker.try_tick() is True

        # Next call should not be ready
        assert ticker.try_tick() is False

    def test_try_tick_with_now_parameter(self, mock_logger, fake_clock):
        """Test try_tick accepts optional now parameter."""
        ticker = Ticker(mock_logger, secs=0.25)

        # First tick
        now = fake_clock.monotonic()
        assert ticker.try_tick(now=now) is True

        # Using same timestamp should not tick (not enough time)
        assert ticker.try_tick(now=now) is False

        # A timestamp one interval later ticks
        fake_clock.sleep(0.25)
        assert ticker.try_tick(now=fake_clock.monotonic()) is True

    def test_shared_timestamp_pattern(self, mock_logger):
        """Test pattern of sharing timestamp between methods."""
        ticker = Ticker(mock_logger, secs=0.5)

        # Capture time once
        now = time.monotonic()

        # First tick using shared timestamp
        remaining = ticker.time_until_next_tick(now=now)
        assert remaining == 0.0
        assert ticker.try_tick(now=now) is True

        # Check again with same timestamp - should not be ready
        remaining = ticker.time_until_next_tick(now=now)
        assert 0.4 < remaining <= 0.5  # ~0.5 (full interval from that moment)
        assert ticker.try_tick(now=now) is False

    def test_spaced_mode_waits_from_completion(self, mock_logger, fake_clock):
        """Test SPACED mode waits full interval from task completion."""

        def handler():
            fake_clock.sleep(1.0)  # The task takes 1s

        ticker = Ticker(mock_logger, handler, secs=2.0, mode=TickerMode.SPACED)

        # First tick at t=0 completes at t=1.0
        start = fake_clock.monotonic()
        assert ticker.try_tick() is True
        assert fake_clock.monotonic() - start == 1.0

        # A full interval from completion remains
        assert ticker.time_until_next_tick() == 2.0

        # Due exactly one interval after completion
        fake_clock.sleep(2.0)
        assert ticker.try_tick() is True

    def test_spaced_mode_with_slow_task(self, mock_logger, fake_clock):
        """Test SPACED mode waits from completion even for slow tasks."""

        def slow_handler():
            fake_clock.sleep(1.5)  # Longer than the 1s interval

        ticker = Ticker(mock_logger, slow_handler, secs=1.0, mode=TickerMode.SPACED)

        # First tick at t=0 completes at t=1.5
        start = fake_clock.monotonic()
        assert ticker.try_tick() is True
        assert fake_clock.monotonic() - start == 1.5

        # The full interval counts from completion, not from the tick start
        assert ticker.time_until_next_tick() == 1.0
        assert ticker.try_tick() is False

        fake_clock.sleep(1.0)
        assert ticker.try_tick() is True

    def test_spaced_vs_flex_comparison(self, mock_logger, fake_clock):
        """Test difference between SPACED and FLEX modes with task execution time."""

        def handler():
            fake_clock.sleep(0.5)  # Each task takes 0.5s

        flex_ticker = Ticker(mock_logger, handler, secs=2.0, mode=TickerMode.FLEX)
        spaced_ticker = Ticker(mock_logger, handler, secs=2.0, mode=TickerMode.SPACED)

        # FLEX ticks at t=0 (interval counted from the start, before the handler);
        # SPACED ticks at t=0.5 and completes at t=1.0 (counted from completion)
        assert flex_ticker.try_tick() is True
        assert spaced_ticker.try_tick() is True

        # Now t=1.0: FLEX's next tick is at t=2.0, SPACED's at t=3.0
        assert flex_ticker.time_until_next_tick() == 1.0
        assert spaced_ticker.time_until_next_tick() == 2.0

    def test_spaced_mode_guarantees_minimum_spacing(self, mock_logger, fake_clock):
        """Test SPACED mode guarantees minimum spacing between operations."""
        ticker = Ticker(mock_logger, secs=0.5, mode=TickerMode.SPACED)

        completion_times = []

        for _ in range(3):
            # Poll in steps that divide the interval exactly (binary fractions)
            while not ticker.try_tick():
                fake_clock.sleep(1 / 64)

            completion_times.append(fake_clock.monotonic())

            # The task after the tick takes 0.125s
            fake_clock.sleep(0.125)

        # Each tick comes exactly one interval after the previous one completed
        intervals = [
            completion_times[i + 1] - completion_times[i]
            for i in range(len(completion_times) - 1)
        ]
        assert intervals == [0.5, 0.5]

    def test_spaced_mode_handles_exceptions(self, mock_logger, fake_clock):
        """Test SPACED mode handles handler exceptions and maintains spacing."""
        from unittest.mock import Mock

        # Handler that raises on first call, succeeds on second
        handler = Mock(side_effect=[Exception("boom"), None, None])
        ticker = Ticker(mock_logger, handler, secs=0.5, mode=TickerMode.SPACED)

        # First tick should not raise (exception caught)
        assert ticker.try_tick() is True

        # Exception should be logged
        assert mock_logger.error.called

        # Should still maintain spacing even after exception
        assert ticker.time_until_next_tick() == 0.5

        # Wait for next tick
        fake_clock.sleep(0.5)

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

    def test_cannot_mix_run_and_try_tick(self, mock_logger, mock_handler):
        """Test that mixing run() and try_tick() raises RuntimeError."""
        import threading

        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        # Start run() in background
        thread = threading.Thread(target=ticker.run, daemon=True)
        thread.start()
        time.sleep(0.05)  # Let it start

        # Attempting to use try_tick() should raise
        try:
            with pytest.raises(
                TickerAPIError, match="Cannot call try_tick.*after using run"
            ):
                ticker.try_tick()
        finally:
            ticker.stop()
            thread.join(timeout=1.0)

    def test_cannot_mix_iterator_and_run(self, mock_logger, mock_handler):
        """Test that mixing iterator and run() raises RuntimeError."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        # Start iterator in a thread so it doesn't block
        import threading

        def iterate():
            for _ in ticker:
                ticker.stop()  # Stop after first tick
                break

        thread = threading.Thread(target=iterate, daemon=True)
        thread.start()
        time.sleep(0.05)  # Let iterator start and set mode

        # Attempting to use run() should raise
        try:
            with pytest.raises(
                TickerAPIError, match="Cannot call run.*after using iterator"
            ):
                ticker.run()
        finally:
            ticker.stop()
            thread.join(timeout=1.0)

    def test_cannot_mix_iterator_and_try_tick(self, mock_logger):
        """Test that mixing iterator and try_tick() raises RuntimeError."""
        ticker = Ticker(mock_logger, secs=0.1)

        # Start iterator in a thread so it doesn't block
        import threading

        def iterate():
            for _ in ticker:
                ticker.stop()  # Stop after first tick
                break

        thread = threading.Thread(target=iterate, daemon=True)
        thread.start()
        time.sleep(0.05)  # Let iterator start and set mode

        # Attempting to use try_tick() should raise
        try:
            with pytest.raises(
                TickerAPIError, match="Cannot call try_tick.*after using iterator"
            ):
                ticker.try_tick()
        finally:
            ticker.stop()
            thread.join(timeout=1.0)

    def test_cannot_mix_run_and_iterator(self, mock_logger, mock_handler):
        """Test that mixing run() and iterator raises RuntimeError."""
        import threading

        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        # Start run() in background
        thread = threading.Thread(target=ticker.run, daemon=True)
        thread.start()
        time.sleep(0.05)  # Let it start

        # Attempting to use iterator should raise when starting iteration
        try:
            with pytest.raises(TickerAPIError, match="Cannot use iterator after run"):
                it = iter(ticker)
                next(it)  # Exception raised on first iteration
        finally:
            ticker.stop()
            thread.join(timeout=1.0)

    def test_cannot_mix_try_tick_and_iterator(self, mock_logger):
        """Test that mixing try_tick() and iterator raises RuntimeError."""
        ticker = Ticker(mock_logger, secs=0.1)

        # Use try_tick() first
        ticker.try_tick()

        # Attempting to use iterator should raise when starting iteration
        with pytest.raises(TickerAPIError, match="Cannot use iterator after.*try_tick"):
            it = iter(ticker)
            next(it)  # Exception raised on first iteration

    def test_time_until_next_tick_no_side_effects(self, mock_logger, fake_clock):
        """Test that time_until_next_tick() doesn't mutate state (query method invariant)."""
        ticker = Ticker(mock_logger, secs=1.0, initial=False)

        # Call time_until_next_tick() multiple times with different timestamps
        # This should NOT affect the timing state
        now1 = fake_clock.monotonic()
        remaining1 = ticker.time_until_next_tick(now=now1)

        fake_clock.sleep(0.25)
        now2 = fake_clock.monotonic()
        remaining2 = ticker.time_until_next_tick(now=now2)

        # Both calls should return the full interval (1.0s) since ticker hasn't initialized yet
        assert remaining1 == 1.0
        assert remaining2 == 1.0

        # Now call try_tick() which WILL initialize the state
        result = ticker.try_tick(now=now2)
        assert result is False  # Not ready yet (initial=False requires full interval)

        # After initialization the interval counts from now2
        fake_clock.sleep(0.25)
        assert ticker.time_until_next_tick(now=fake_clock.monotonic()) == 0.75

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


@pytest.mark.unit
class TestBlockingAPITimingModes:
    """Test that blocking API (run()) respects timing modes."""

    # These run Ticker.run() on the fake clock in the test's own thread: the
    # scheduler's waits advance virtual time, and the handler stops the ticker
    # after the ticks the test needs, which makes run() return.

    def test_blocking_flex_mode_no_catchup(self, mock_logger, fake_clock):
        """Test FLEX mode in blocking API doesn't catch up after slow tasks."""
        start = fake_clock.monotonic()
        tick_times: list[float] = []

        def slow_handler():
            tick_times.append(fake_clock.monotonic() - start)
            if len(tick_times) == 2:
                fake_clock.sleep(0.5)  # Slow task, longer than the interval
            if len(tick_times) == 3:
                ticker.stop()

        ticker = Ticker(mock_logger, slow_handler, secs=0.25, mode=TickerMode.FLEX)
        ticker.run()

        # Tick 2 ends late at t=0.75; FLEX waits a full interval from there
        # (t=1.0) instead of firing the missed tick at once
        assert tick_times == [0.0, 0.25, 1.0]

    def test_blocking_strict_mode_catches_up(self, mock_logger, fake_clock):
        """Test STRICT mode in blocking API catches up after slow tasks."""
        start = fake_clock.monotonic()
        tick_times: list[float] = []

        def slow_handler():
            tick_times.append(fake_clock.monotonic() - start)
            if len(tick_times) == 2:
                fake_clock.sleep(0.625)  # Very slow task: ends at t=0.875
            if len(tick_times) == 5:
                ticker.stop()

        ticker = Ticker(mock_logger, slow_handler, secs=0.25, mode=TickerMode.STRICT)
        ticker.run()

        # Ticks due at t=0.5 and t=0.75 fire back to back at t=0.875, then the
        # schedule resumes at t=1.0
        assert tick_times == [0.0, 0.25, 0.875, 0.875, 1.0]

    def test_blocking_spaced_mode_guarantees_spacing(self, mock_logger, fake_clock):
        """Test SPACED mode in blocking API guarantees spacing from completion."""
        start = fake_clock.monotonic()
        tick_times: list[float] = []
        completion_times: list[float] = []

        def varying_handler():
            tick_times.append(fake_clock.monotonic() - start)
            # Variable task duration: tick 2 is long
            fake_clock.sleep(0.25 if len(tick_times) == 2 else 0.0625)
            completion_times.append(fake_clock.monotonic() - start)
            if len(tick_times) == 4:
                ticker.stop()

        ticker = Ticker(mock_logger, varying_handler, secs=0.25, mode=TickerMode.SPACED)
        ticker.run()

        # Every tick starts exactly one interval after the previous one completed
        gaps = [tick_times[i + 1] - completion_times[i] for i in range(3)]
        assert gaps == [0.25, 0.25, 0.25]
