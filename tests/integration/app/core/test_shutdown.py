# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for ShutdownManager.sleep() woken from another thread."""

import signal
import threading
import time

import pytest

from appinfra.app.core.shutdown import ShutdownManager


class TestSleep:
    """Test the shutdown-aware sleep primitive."""

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
