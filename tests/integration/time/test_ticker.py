# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for the ticker that run it on a thread of its own, install signal handlers or run it in
a spawned process.
"""

import functools
import logging
import multiprocessing
import threading
from collections.abc import Callable
from unittest.mock import Mock

import pytest

from appinfra.errors import TickerAPIError, TickerStateError
from appinfra.log import create_lg
from appinfra.time.ticker import Ticker, TickerHandler
from tests.helpers.ticker import SimpleHandler, spy_on_waits


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
    return SimpleHandler()


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


class TestSpawnProcess:
    """run_started in a spawn-context process, as TCPServer's ticker= mode starts it."""

    def test_ticks_in_spawned_process(self):
        ctx = multiprocessing.get_context("spawn")
        ticks = ctx.Queue()
        ticker = Ticker(
            create_lg("ticker-spawn", "info"),
            functools.partial(ticks.put, "tick"),
            secs=0.01,
        )

        proc = ctx.Process(target=ticker.run_started)
        proc.start()
        try:
            assert ticks.get(timeout=30) == "tick"
        finally:
            proc.terminate()
            proc.join(timeout=10)


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

    def test_continuous_mode_executes_many_ticks(
        self, mock_logger, simple_handler, monkeypatch
    ):
        """Test continuous mode executes many ticks rapidly."""
        ticked_often = threading.Event()
        _also_signal(simple_handler, ticked_often, 50)
        ticker = Ticker(mock_logger, simple_handler)
        # Rapidly: the loop never waits, neither on the stop event nor in a sleep
        assert ticker._sched is None
        sleeps, waits = spy_on_waits(ticker, monkeypatch)

        thread = _start(ticker)
        assert ticked_often.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        assert simple_handler.tick_count >= 50
        assert sleeps.sleeps == []
        waits.assert_not_called()

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


class TestTickerControl:
    """Test ticker control methods."""

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

    def test_callable_in_continuous_mode(self, mock_logger, monkeypatch):
        """Test callable works in continuous mode."""
        call_count = [0]
        ticked_often = threading.Event()
        signal = _signal_after(ticked_often, 50)

        def my_tick():
            call_count[0] += 1
            signal()

        ticker = Ticker(mock_logger, my_tick)  # No secs = continuous
        # Back to back: the loop never waits, neither on the stop event nor in a sleep
        assert ticker._sched is None
        sleeps, waits = spy_on_waits(ticker, monkeypatch)

        thread = _start(ticker)
        assert ticked_often.wait(timeout=_TIMEOUT)
        _stop(ticker, thread)

        # Continuous mode should execute many times
        assert call_count[0] >= 50
        assert sleeps.sleeps == []
        waits.assert_not_called()


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

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


class TestTickerIteratorIntegration:
    """Integration tests for Ticker iterator with SubprocessContext pattern."""

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


class TestNonBlockingAPI:
    """Test non-blocking API for manual tick control."""

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
