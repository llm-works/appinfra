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
from collections.abc import Callable
from unittest.mock import Mock

import pytest

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


# Tests that run a ticker on a thread of its own wait on events its handler sets, never
# for a fixed time; running out of the timeout is the failure, never the expected path.
_TIMEOUT = 5.0


def _start(ticker: Ticker, *args, **kwargs) -> threading.Thread:
    """Start ``ticker.run(*args, **kwargs)`` on a thread of its own."""
    thread = threading.Thread(target=ticker.run, args=args, kwargs=kwargs, daemon=True)
    thread.start()
    return thread


def _stop(ticker: Ticker, thread: threading.Thread) -> None:
    """Stop ``ticker`` and check its run() thread ends."""
    ticker.stop()
    thread.join(timeout=_TIMEOUT)
    assert not thread.is_alive()


def _signal_after(event: threading.Event, ticks: int) -> Callable[[], None]:
    """A tick function that sets ``event`` on its ``ticks``-th call."""
    count = 0

    def tick() -> None:
        nonlocal count
        count += 1
        if count == ticks:
            event.set()

    return tick


def _also_signal(handler: TickerHandler, event: threading.Event, ticks: int) -> None:
    """Make ``handler`` set ``event`` on its ``ticks``-th tick, after its own ticker_tick."""
    tick = handler.ticker_tick
    signal = _signal_after(event, ticks)

    def ticking() -> None:
        tick()
        signal()

    handler.ticker_tick = ticking  # type: ignore[method-assign]


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

    def _first_tick_offset(self, mock_logger, secs: float, initial: bool) -> float:
        """Run a ticker until its first tick; return how long after run() it fired."""
        start = time.monotonic()
        tick_times: list[float] = []

        class TimingHandler(TickerHandler):
            def ticker_tick(self):
                tick_times.append(time.monotonic() - start)
                ticker.stop()

        ticker = Ticker(mock_logger, TimingHandler(), secs=secs, initial=initial)
        ticker.run()
        return tick_times[0]

    def test_initial_false_skips_immediate_tick(self, mock_logger, clock):
        """Test initial=False skips the immediate tick and waits for interval."""
        assert self._first_tick_offset(mock_logger, 0.5, initial=False) >= 0.5

    def test_initial_true_fires_immediately(self, mock_logger, clock):
        """Test initial=True (default) fires the first tick without waiting an interval."""
        # A long interval: the tick comes well before it unless the first one waited
        assert self._first_tick_offset(mock_logger, 10.0, initial=True) < 10.0


# =============================================================================
# Test Scheduled Execution Mode
# =============================================================================


class TestScheduledMode:
    """Test scheduled execution mode."""

    def test_scheduled_mode_calls_ticker_start(self, mock_logger, mock_handler):
        """Test scheduled mode calls ticker_start."""
        started = threading.Event()
        mock_handler.ticker_start.side_effect = lambda *args, **kwargs: started.set()
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        thread = _start(ticker)
        assert started.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        mock_handler.ticker_start.assert_called_once()

    def test_scheduled_mode_calls_before_first_tick(self, mock_logger, mock_handler):
        """Test scheduled mode calls ticker_before_first_tick."""
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        mock_handler.ticker_before_first_tick.assert_called_once()

    def test_scheduled_mode_executes_multiple_ticks(self, mock_logger, simple_handler):
        """Test scheduled mode executes multiple ticks."""
        ticked_thrice = threading.Event()
        _also_signal(simple_handler, ticked_thrice, 3)
        ticker = Ticker(mock_logger, simple_handler, secs=0.05)

        thread = _start(ticker)
        assert ticked_thrice.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        assert simple_handler.tick_count >= 3

    def test_scheduled_mode_calls_ticker_stop(self, mock_logger, mock_handler):
        """Test scheduled mode calls ticker_stop on cleanup."""
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        mock_handler.ticker_stop.assert_called_once()

    def test_scheduled_mode_handles_ticker_before_first_tick_error(
        self, mock_logger, mock_handler
    ):
        """Test scheduled mode handles errors in ticker_before_first_tick."""
        mock_handler.ticker_before_first_tick.side_effect = Exception(
            "before first tick error"
        )
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler, secs=0.05)

        thread = _start(ticker)
        # The ticker carries on to its ticks despite the error
        assert ticked.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        mock_handler.ticker_before_first_tick.assert_called_once()
        mock_logger.error.assert_called()

    def test_scheduled_mode_handles_ticker_tick_error(self, mock_logger, mock_handler):
        """Test scheduled mode keeps ticking through errors in ticker_tick."""
        failed_thrice = threading.Event()
        signal = _signal_after(failed_thrice, 3)

        def failing_tick():
            signal()
            raise Exception("tick error")

        mock_handler.ticker_tick.side_effect = failing_tick
        ticker = Ticker(mock_logger, mock_handler, secs=0.05)

        thread = _start(ticker)
        assert failed_thrice.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        assert mock_handler.ticker_tick.call_count >= 3
        assert mock_logger.error.call_count >= 3

    def test_scheduled_mode_stops_gracefully(self, mock_logger, simple_handler):
        """Test scheduled mode stops gracefully."""
        ticked = threading.Event()
        _also_signal(simple_handler, ticked, 1)
        ticker = Ticker(mock_logger, simple_handler, secs=0.1)

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        assert simple_handler.stopped is True
        assert not ticker.is_running()


# =============================================================================
# Test Continuous Execution Mode
# =============================================================================


class TestContinuousMode:
    """Test continuous execution mode."""

    def test_continuous_mode_calls_ticker_start(self, mock_logger, mock_handler):
        """Test continuous mode calls ticker_start."""
        started = threading.Event()
        mock_handler.ticker_start.side_effect = lambda *args, **kwargs: started.set()
        ticker = Ticker(mock_logger, mock_handler)

        thread = _start(ticker)
        assert started.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        mock_handler.ticker_start.assert_called_once()

    def test_continuous_mode_calls_before_first_tick(self, mock_logger, mock_handler):
        """Test continuous mode calls ticker_before_first_tick."""
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler)

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        mock_handler.ticker_before_first_tick.assert_called_once()

    def test_continuous_mode_executes_many_ticks(self, mock_logger, simple_handler):
        """Test continuous mode executes many ticks rapidly."""
        ticked_often = threading.Event()
        _also_signal(simple_handler, ticked_often, 50)
        ticker = Ticker(mock_logger, simple_handler)

        thread = _start(ticker)
        assert ticked_often.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        assert simple_handler.tick_count >= 50

    def test_continuous_mode_stops_on_stop_event(self, mock_logger, simple_handler):
        """Test continuous mode stops when stop event is set."""
        ticked = threading.Event()
        _also_signal(simple_handler, ticked, 1)
        ticker = Ticker(mock_logger, simple_handler)

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        assert ticker.is_running() is False
        assert simple_handler.stopped is True

    def test_continuous_mode_handles_ticker_tick_error(self, mock_logger, mock_handler):
        """Test continuous mode keeps ticking through errors in ticker_tick."""
        # The first four calls raise; the sixth tells the test the ticker went on
        call_count = [0]
        went_on = threading.Event()
        signal = _signal_after(went_on, 6)

        def side_effect():
            call_count[0] += 1
            signal()
            if call_count[0] < 5:
                raise Exception("tick error")

        mock_handler.ticker_tick.side_effect = side_effect
        ticker = Ticker(mock_logger, mock_handler)

        thread = _start(ticker)
        assert went_on.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        assert mock_handler.ticker_tick.call_count >= 6
        assert mock_logger.error.call_count == 4

    def test_continuous_mode_calls_ticker_stop(self, mock_logger, mock_handler):
        """Test continuous mode calls ticker_stop on cleanup."""
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler)

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        mock_handler.ticker_stop.assert_called_once()


# =============================================================================
# Test Ticker Control Methods
# =============================================================================


class TestTickerControl:
    """Test ticker control methods."""

    def test_is_running_returns_false_initially(self, mock_logger, mock_handler):
        """Test is_running returns False initially."""
        ticker = Ticker(mock_logger, mock_handler, secs=1.0)
        assert ticker.is_running() is False

    def test_is_running_returns_true_while_running(self, mock_logger, mock_handler):
        """Test is_running returns True while running."""
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)

        assert ticker.is_running() is True

        _stop(ticker, thread)

    def test_is_running_returns_false_after_stop(self, mock_logger, mock_handler):
        """Test is_running returns False after stopping."""
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

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
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        # Initially not running
        status = ticker.get_status()
        assert status["running"] is False

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)

        # Should be running
        status = ticker.get_status()
        assert status["running"] is True

        _stop(ticker, thread)

    def test_run_raises_if_already_running(self, mock_logger, mock_handler):
        """Test run raises RuntimeError if already running."""
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)

        # Try to run again
        with pytest.raises(TickerStateError, match="already running"):
            ticker.run()

        _stop(ticker, thread)

    def test_stop_cancels_scheduled_events(self, mock_logger, mock_handler):
        """Test stop wakes run() mid-interval and cancels pending events."""
        # Real time and a real thread: stop() comes from another thread while
        # run() waits out a 10s interval
        ticker = Ticker(mock_logger, mock_handler, secs=10, initial=True)
        # A stop() before run() starts would end it before any interval; waiting
        # for the first tick (initial=True) guarantees stop() comes mid-interval
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

    def test_stop_before_run_ends_that_run(self, mock_logger, mock_handler):
        """Test a stop() while not running ends the next run() before it starts."""
        ticker = Ticker(mock_logger, mock_handler, secs=10)
        ticker.stop()

        thread = threading.Thread(target=ticker.run, daemon=True)
        thread.start()
        thread.join(timeout=1.0)

        assert not thread.is_alive()
        mock_handler.ticker_start.assert_not_called()
        mock_handler.ticker_stop.assert_not_called()
        assert ticker.is_running() is False
        # Consumed by that run(): the next one starts
        assert not ticker._stop_event.is_set()

    def test_stop_right_after_thread_start(self, mock_logger, mock_handler):
        """Test stop() ends run() whether it lands before or after run() starts."""
        for _ in range(50):
            ticker = Ticker(mock_logger, mock_handler, secs=10)
            starts = mock_handler.ticker_start.call_count
            stops = mock_handler.ticker_stop.call_count

            thread = threading.Thread(target=ticker.run, daemon=True)
            thread.start()
            ticker.stop()
            thread.join(timeout=1.0)

            assert not thread.is_alive()
            # A run that started is stopped exactly once; one ended by the
            # pending stop() calls neither hook
            started = mock_handler.ticker_start.call_count - starts
            assert mock_handler.ticker_stop.call_count - stops == started

    def test_repeated_stop_calls_ticker_stop_once(self, mock_logger):
        """Test only the first stop() of a run calls ticker_stop()."""
        handler = Mock(spec=TickerHandler)
        ticker = Ticker(mock_logger, handler, secs=10, initial=True)

        def stop_twice():
            ticker.stop()
            ticker.stop()

        handler.ticker_tick.side_effect = stop_twice

        thread = threading.Thread(target=ticker.run, daemon=True)
        thread.start()
        thread.join(timeout=1.0)

        assert not thread.is_alive()
        handler.ticker_stop.assert_called_once()

    def test_run_again_after_stop(self, mock_logger):
        """Test a stop() during a run is spent with it: the next run() starts."""
        handler = Mock(spec=TickerHandler)
        ticker = Ticker(mock_logger, handler, secs=10, initial=True)
        handler.ticker_tick.side_effect = ticker.stop

        for _ in range(2):
            thread = threading.Thread(target=ticker.run, daemon=True)
            thread.start()
            thread.join(timeout=1.0)
            assert not thread.is_alive()

        assert handler.ticker_start.call_count == 2
        assert handler.ticker_tick.call_count == 2
        assert handler.ticker_stop.call_count == 2

    def test_stop_after_run_ends_is_pending(self, mock_logger):
        """Test a stop() after a run ends is held for the next run()."""
        handler = Mock(spec=TickerHandler)
        ticker = Ticker(mock_logger, handler, secs=10, initial=True)
        handler.ticker_tick.side_effect = ticker.stop

        thread = threading.Thread(target=ticker.run, daemon=True)
        thread.start()
        thread.join(timeout=1.0)
        assert not thread.is_alive()

        ticker.stop()  # not running: pending, no ticker_stop() call
        ticker.run()  # returns at once

        handler.ticker_start.assert_called_once()
        handler.ticker_stop.assert_called_once()

    def test_failed_start_resets_state(self, mock_logger, mock_handler):
        """Test a run() whose ticker_start() raises leaves the ticker reusable."""
        mock_handler.ticker_start.side_effect = [RuntimeError("boom"), None]
        mock_handler.ticker_tick.side_effect = lambda: ticker.stop()
        ticker = Ticker(mock_logger, mock_handler, secs=10, initial=True)

        with pytest.raises(TickerStateError, match="Ticker execution failed"):
            ticker.run()
        assert ticker.is_running() is False

        thread = threading.Thread(target=ticker.run, daemon=True)
        thread.start()
        thread.join(timeout=1.0)
        assert not thread.is_alive()
        mock_handler.ticker_stop.assert_called_once()


# =============================================================================
# Test Integration Scenarios
# =============================================================================


class TestIntegrationScenarios:
    """Test real-world ticker scenarios."""

    def test_ticker_with_args_and_kwargs(self, mock_logger, mock_handler):
        """Test ticker passes args and kwargs to handler."""
        started = threading.Event()
        mock_handler.ticker_start.side_effect = lambda *args, **kwargs: started.set()
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        thread = _start(ticker, "arg1", "arg2", key="value")
        assert started.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

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


class TestCallableWrapper:
    """Test automatic wrapping of plain callables."""

    def test_callable_is_wrapped_in_handler(self, mock_logger):
        """Test that a plain callable is wrapped in a TickerHandler."""
        call_count = [0]
        ticked = threading.Event()

        def my_tick():
            call_count[0] += 1
            ticked.set()

        ticker = Ticker(mock_logger, my_tick, secs=0.05)

        # Handler should be wrapped
        from appinfra.time.ticker import _CallableWrapper

        assert isinstance(ticker._handler, _CallableWrapper)

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        # Should have executed the callable
        assert call_count[0] >= 1

    def test_lambda_is_wrapped(self, mock_logger):
        """Test that a lambda is wrapped in a TickerHandler."""
        results = []
        ticked = threading.Event()

        ticker = Ticker(
            mock_logger, lambda: (results.append("tick"), ticked.set()), secs=0.05
        )

        from appinfra.time.ticker import _CallableWrapper

        assert isinstance(ticker._handler, _CallableWrapper)

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        assert len(results) >= 1
        assert results[0] == "tick"

    def test_callable_in_continuous_mode(self, mock_logger):
        """Test callable works in continuous mode."""
        call_count = [0]
        ticked_often = threading.Event()
        signal = _signal_after(ticked_often, 50)

        def my_tick():
            call_count[0] += 1
            signal()

        ticker = Ticker(mock_logger, my_tick)  # No secs = continuous

        thread = _start(ticker)
        assert ticked_often.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        # Continuous mode should execute many times
        assert call_count[0] >= 50

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

    def test_ticker_stop_handles_handler_stop_error(self, mock_logger, mock_handler):
        """Test ticker handles error in ticker_stop gracefully."""
        mock_handler.ticker_stop.side_effect = Exception("stop error")
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)
        # Should not raise, error is caught
        _stop(ticker, thread)

    def test_first_flag_reset_after_first_tick(self, mock_logger, mock_handler):
        """Test first flag is reset after first tick."""
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler, secs=0.05)
        assert ticker._first is True

        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        assert ticker._first is False


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

    def test_callback_and_iterator_are_separate_modes(self, mock_logger):
        """Test that callback mode and iterator mode are independent."""
        # Callback mode
        call_count = [0]
        ticked = threading.Event()
        ticker1 = Ticker(
            mock_logger,
            lambda: (call_count.__setitem__(0, call_count[0] + 1), ticked.set()),
            secs=0.01,
        )
        thread = _start(ticker1)
        assert ticked.wait(timeout=_TIMEOUT)
        _stop(ticker1, thread)
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

        # The captured time is answered as of then; the default reads the clock now
        assert ticker.time_until_next_tick(now=now) == 1.0
        assert ticker.time_until_next_tick() <= 0.75

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

        # The task ended at least 0.25s after the start, and the interval counts from
        # there: just short of start + 0.25 + 1.0 the next tick is not due yet
        assert ticker.try_tick(now=start + 1.25 - 0.125) is False
        # One interval after the call returned, it is
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
        # interval after the start the task had not even finished
        assert ticker.time_until_next_tick() <= 0.25
        assert ticker.try_tick(now=start + 0.75 - 0.0625) is False
        assert ticker.try_tick(now=done + 0.25) is True

    def test_spaced_vs_flex_comparison(self, mock_logger, clock):
        """Test difference between SPACED and FLEX modes with task execution time."""

        def handler():
            time.sleep(0.25)  # Each task takes at least 0.25s

        flex_ticker = Ticker(mock_logger, handler, secs=1.0, mode=TickerMode.FLEX)
        spaced_ticker = Ticker(mock_logger, handler, secs=1.0, mode=TickerMode.SPACED)

        # FLEX counts the interval from the tick's start, before the handler; SPACED from
        # the handler's completion
        assert flex_ticker.try_tick() is True
        spaced_start = time.monotonic()
        assert spaced_ticker.try_tick() is True

        # FLEX started before SPACED did, so its next tick is due by then + 1.0; SPACED
        # finished no earlier than spaced_start + 0.25, so its tick is not due yet
        moment = spaced_start + 0.25 + 1.0 - 0.125
        assert spaced_ticker.try_tick(now=moment) is False
        assert flex_ticker.try_tick(now=moment) is True

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
            calls.append((before, time.monotonic()))

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

        # Exception should be logged
        assert mock_logger.error.called

        # Should still maintain spacing even after exception
        assert ticker.time_until_next_tick() <= 0.5
        assert ticker.try_tick(now=start + 0.5 - 0.125) is False

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

    def test_cannot_mix_run_and_try_tick(self, mock_logger, mock_handler):
        """Test that mixing run() and try_tick() raises RuntimeError."""
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        # Start run() in background, and wait until it is ticking
        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)

        # Attempting to use try_tick() should raise
        try:
            with pytest.raises(
                TickerAPIError, match="Cannot call try_tick.*after using run"
            ):
                ticker.try_tick()
        finally:
            _stop(ticker, thread)

    def test_cannot_mix_iterator_and_run(self, mock_logger, mock_handler):
        """Test that mixing iterator and run() raises RuntimeError."""
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)
        iterating = threading.Event()

        # Start iterator in a thread so it doesn't block
        def iterate():
            for _ in ticker:
                iterating.set()
                ticker.stop()  # Stop after first tick
                break

        thread = threading.Thread(target=iterate, daemon=True)
        thread.start()
        assert iterating.wait(timeout=_TIMEOUT)  # The iterator has set its mode

        # Attempting to use run() should raise
        try:
            with pytest.raises(
                TickerAPIError, match="Cannot call run.*after using iterator"
            ):
                ticker.run()
        finally:
            _stop(ticker, thread)

    def test_cannot_mix_iterator_and_try_tick(self, mock_logger):
        """Test that mixing iterator and try_tick() raises RuntimeError."""
        ticker = Ticker(mock_logger, secs=0.1)
        iterating = threading.Event()

        # Start iterator in a thread so it doesn't block
        def iterate():
            for _ in ticker:
                iterating.set()
                ticker.stop()  # Stop after first tick
                break

        thread = threading.Thread(target=iterate, daemon=True)
        thread.start()
        assert iterating.wait(timeout=_TIMEOUT)  # The iterator has set its mode

        # Attempting to use try_tick() should raise
        try:
            with pytest.raises(
                TickerAPIError, match="Cannot call try_tick.*after using iterator"
            ):
                ticker.try_tick()
        finally:
            _stop(ticker, thread)

    def test_cannot_mix_run_and_iterator(self, mock_logger, mock_handler):
        """Test that mixing run() and iterator raises RuntimeError."""
        ticked = threading.Event()
        mock_handler.ticker_tick.side_effect = ticked.set
        ticker = Ticker(mock_logger, mock_handler, secs=0.1)

        # Start run() in background, and wait until it is ticking
        thread = _start(ticker)
        assert ticked.wait(timeout=_TIMEOUT)

        # Attempting to use iterator should raise when starting iteration
        try:
            with pytest.raises(TickerAPIError, match="Cannot use iterator after run"):
                it = iter(ticker)
                next(it)  # Exception raised on first iteration
        finally:
            _stop(ticker, thread)

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

    def test_blocking_flex_mode_no_catchup(self, mock_logger, clock):
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
        start = time.monotonic()
        ticker.run()

        assert len(starts) == 3
        assert starts[1] >= start + 0.25
        # Tick 2 ended late; FLEX waits a full interval from there instead of firing
        # the missed tick at once
        assert starts[2] >= ends[1] + 0.25

    def test_blocking_strict_mode_never_ticks_early(self, mock_logger, clock):
        """Test STRICT mode in blocking API keeps every tick on or after its schedule."""
        starts: list[float] = []

        def slow_handler():
            starts.append(time.monotonic())
            if len(starts) == 2:
                time.sleep(0.625)  # Very slow task: two ticks fall due meanwhile
            if len(starts) == 5:
                ticker.stop()

        ticker = Ticker(mock_logger, slow_handler, secs=0.25, mode=TickerMode.STRICT)
        start = time.monotonic()
        ticker.run()

        # Tick k is due k intervals after the first; how it catches up after the slow
        # task is in TestNextTickDelay
        assert len(starts) == 5
        assert all(t >= start + k * 0.25 for k, t in enumerate(starts)), starts

    def test_blocking_spaced_mode_guarantees_spacing(self, mock_logger, clock):
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
        ticker.run()

        # Every tick starts at least one interval after the previous one completed
        gaps = [starts[i + 1] - ends[i] for i in range(3)]
        assert all(gap >= 0.25 for gap in gaps), gaps


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
