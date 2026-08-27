# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/core/shutdown.py.

Tests shutdown manager functionality including:
- Signal handler registration
- Signal handling (SIGTERM, SIGINT)
- Duplicate signal handling
- Return code mapping
"""

import signal
import threading
import time
from unittest.mock import Mock, patch

import pytest

from appinfra.app.core.shutdown import ShutdownManager


@pytest.mark.unit
class TestShutdownManagerInit:
    """Test ShutdownManager initialization."""

    def test_basic_initialization(self):
        """Test basic initialization."""
        manager = ShutdownManager()

        assert manager._shutting_down is False
        assert manager._signal_return_code == 130  # Default
        assert manager._original_handlers == {}


@pytest.mark.unit
class TestSignalRegistration:
    """Test signal handler registration."""

    def test_register_signal_handlers(self):
        """Test register_signal_handlers registers SIGTERM and SIGINT."""
        manager = ShutdownManager()

        with patch("signal.signal") as mock_signal:
            mock_signal.return_value = Mock()  # Original handler
            manager.register_signal_handlers()

            # Should register both SIGTERM and SIGINT
            assert mock_signal.call_count == 2
            calls = mock_signal.call_args_list
            signals_registered = [call[0][0] for call in calls]
            assert signal.SIGTERM in signals_registered
            assert signal.SIGINT in signals_registered

    def test_original_handlers_preserved(self):
        """Test that original signal handlers are preserved."""
        manager = ShutdownManager()

        mock_term_handler = Mock()
        mock_int_handler = Mock()

        with patch("signal.signal") as mock_signal:

            def signal_side_effect(signum, handler):
                if signum == signal.SIGTERM:
                    return mock_term_handler
                elif signum == signal.SIGINT:
                    return mock_int_handler

            mock_signal.side_effect = signal_side_effect
            manager.register_signal_handlers()

            assert manager._original_handlers[signal.SIGTERM] is mock_term_handler
            assert manager._original_handlers[signal.SIGINT] is mock_int_handler


@pytest.mark.unit
class TestSignalHandling:
    """Test signal handling logic."""

    def test_handle_sigint_stores_return_code_130(self):
        """Test SIGINT handler stores return code 130 and raises KeyboardInterrupt."""
        manager = ShutdownManager()

        with pytest.raises(KeyboardInterrupt):
            manager._handle_signal(signal.SIGINT, None)

        assert manager.get_signal_return_code() == 130

    def test_handle_sigterm_stores_return_code_143(self):
        """Test SIGTERM handler stores return code 143 and raises KeyboardInterrupt."""
        manager = ShutdownManager()

        with pytest.raises(KeyboardInterrupt):
            manager._handle_signal(signal.SIGTERM, None)

        assert manager.get_signal_return_code() == 143

    def test_handle_signal_sets_shutting_down_flag(self):
        """Test signal handler sets shutting_down flag before raising."""
        manager = ShutdownManager()

        assert manager._shutting_down is False
        with pytest.raises(KeyboardInterrupt):
            manager._handle_signal(signal.SIGINT, None)
        assert manager._shutting_down is True

    def test_duplicate_signal_ignored(self):
        """Test duplicate signal is ignored when already shutting down."""
        manager = ShutdownManager()
        manager._shutting_down = True  # Already shutting down

        # Should not raise - just returns silently
        manager._handle_signal(signal.SIGINT, None)

    def test_get_signal_return_code_default(self):
        """Test get_signal_return_code returns 130 as default."""
        manager = ShutdownManager()

        # Before any signal, should return default 130
        assert manager.get_signal_return_code() == 130


@pytest.mark.unit
class TestIsShuttingDown:
    """Test is_shutting_down method."""

    def test_is_shutting_down_false_initially(self):
        """Test is_shutting_down returns False initially."""
        manager = ShutdownManager()

        assert manager.is_shutting_down() is False

    def test_is_shutting_down_true_after_signal(self):
        """Test is_shutting_down returns True after signal handled."""
        manager = ShutdownManager()

        with pytest.raises(KeyboardInterrupt):
            manager._handle_signal(signal.SIGINT, None)

        assert manager.is_shutting_down() is True


@pytest.mark.unit
class TestSleep:
    """Test the shutdown-aware sleep primitive."""

    def test_sleep_raises_on_negative_duration(self):
        """sleep() raises ValueError for negative durations."""
        manager = ShutdownManager()

        with pytest.raises(ValueError, match="non-negative"):
            manager.sleep(-1)

    def test_sleep_returns_false_when_full_time_slept(self):
        """sleep() returns False when the timeout elapses without shutdown."""
        manager = ShutdownManager()

        assert manager.sleep(0.01) is False

    def test_sleep_returns_true_when_already_shutting_down(self):
        """sleep() returns True immediately when shutdown was already signaled."""
        manager = ShutdownManager()
        manager._shutting_down = True

        # Would hang for 60s if the flag were not honored.
        assert manager.sleep(60) is True

    def test_sleep_returns_true_when_shutdown_fires_during_wait(self):
        """sleep() wakes early and returns True when shutdown fires mid-wait."""
        manager = ShutdownManager()

        def trigger_shutdown() -> None:
            time.sleep(0.01)
            manager._shutting_down = True

        threading.Thread(target=trigger_shutdown).start()
        start = time.monotonic()
        result = manager.sleep(5.0)
        elapsed = time.monotonic() - start

        assert result is True
        assert elapsed < 0.5  # woke well before the 5s timeout

    def test_worker_thread_sleep_wakes_when_main_thread_handles_signal(self):
        """
        Motivating scenario: worker thread parked in sleep() while the main
        thread runs the signal handler. Worker must wake early rather than
        stalling shutdown for the full sleep duration.

        The poll-based implementation (5ms interval) avoids deadlock risk from
        calling Event.set() in a signal handler.
        """
        manager = ShutdownManager()
        worker_result: dict[str, object] = {}
        entered_sleep = threading.Event()

        def worker() -> None:
            entered_sleep.set()
            start = time.monotonic()
            worker_result["returned"] = manager.sleep(5.0)
            worker_result["elapsed"] = time.monotonic() - start

        thread = threading.Thread(target=worker)
        thread.start()
        # Wait for worker to enter sleep() before firing signal.
        assert entered_sleep.wait(timeout=1.0), "worker did not enter sleep"

        with pytest.raises(KeyboardInterrupt):
            manager._handle_signal(signal.SIGTERM, None)

        thread.join(timeout=1.0)
        assert not thread.is_alive(), "worker did not wake within 1s"
        assert worker_result["returned"] is True
        assert worker_result["elapsed"] < 0.5  # woke well before 5s timeout
