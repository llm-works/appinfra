# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for the ticker that install signal handlers or run it in a spawned process.
"""

import functools
import logging
import multiprocessing
from unittest.mock import Mock

import pytest

from appinfra.log import create_lg
from appinfra.time.ticker import Ticker


@pytest.fixture
def mock_logger():
    """Create mock logger for tests."""
    logger = Mock(spec=logging.Logger)
    logger.exception = Mock()
    logger.error = Mock()
    logger.debug = Mock()
    logger.info = Mock()
    return logger


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
