# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for LogQueueListener running its listener thread or feeding its queue."""

import logging
import time
from multiprocessing import Queue
from unittest.mock import MagicMock

import pytest

from appinfra.log import Logger
from appinfra.log.mp import LogQueueListener


@pytest.fixture
def queue():
    """Create a multiprocessing queue for testing."""
    return Queue()


@pytest.fixture
def mock_logger():
    """Create a mock logger with handlers."""
    logger = MagicMock(spec=Logger)
    handler = MagicMock(spec=logging.Handler)
    handler.level = logging.DEBUG
    logger.handlers = [handler]
    logger._root_logger = None
    return logger


@pytest.fixture
def listener(queue, mock_logger):
    """Create a LogQueueListener for testing."""
    return LogQueueListener(queue, mock_logger)


class TestLogQueueListenerStartStop:
    """Test start() and stop() methods."""

    def test_start_creates_daemon_thread(self, listener):
        """Test start creates a daemon thread."""
        listener.start()

        try:
            assert listener._thread is not None
            assert listener._thread.is_alive()
            assert listener._thread.daemon is True
        finally:
            listener.stop()

    def test_start_idempotent(self, listener):
        """Test calling start multiple times is safe."""
        listener.start()
        first_thread = listener._thread

        listener.start()  # Should not create new thread

        try:
            assert listener._thread is first_thread
        finally:
            listener.stop()

    def test_stop_terminates_thread(self, listener):
        """Test stop terminates the listener thread."""
        listener.start()
        assert listener.is_alive

        listener.stop()

        assert not listener.is_alive
        assert listener._thread is None

    def test_stop_without_start(self, listener):
        """Test stop is safe when not started."""
        listener.stop()  # Should not raise


class TestLogQueueListenerIsAlive:
    """Test is_alive property."""

    def test_is_alive_true_when_running(self, listener):
        """Test is_alive is True when running."""
        listener.start()

        try:
            assert listener.is_alive
        finally:
            listener.stop()

    def test_is_alive_false_after_stop(self, listener):
        """Test is_alive is False after stop."""
        listener.start()
        listener.stop()

        assert not listener.is_alive


class TestLogQueueListenerErrorHandling:
    """Test error handling in LogQueueListener."""

    def test_listen_handles_unexpected_errors(self, queue, mock_logger, capsys):
        """Test _listen continues after unexpected errors."""
        listener = LogQueueListener(queue, mock_logger)

        # Mock _handle_record to raise on first call
        original_handle = listener._handle_record
        call_count = [0]

        def error_then_succeed(record):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Unexpected error")
            original_handle(record)

        listener._handle_record = error_then_succeed
        listener.start()

        try:
            # First record causes error
            record1 = logging.LogRecord(
                "test", logging.INFO, "test.py", 1, "First", (), None
            )
            queue.put(record1)
            time.sleep(0.2)

            # Listener should still be alive after error
            assert listener.is_alive

            # Check error was written to stderr
            captured = capsys.readouterr()
            assert "error handling record" in captured.err
        finally:
            listener.stop()

    def test_listen_handles_queue_empty_timeout(self, queue, mock_logger):
        """Test _listen handles queue.Empty timeout gracefully."""
        listener = LogQueueListener(queue, mock_logger)
        listener.start()

        try:
            # Don't put anything on queue - let it timeout a few times
            time.sleep(0.7)  # > 0.5s timeout * 1

            # Listener should still be alive
            assert listener.is_alive
        finally:
            listener.stop()


class TestLogQueueListenerIntegration:
    """Integration tests for LogQueueListener."""

    def test_full_queue_flow(self, queue):
        """Test complete flow: put record on queue, listener processes it."""
        # Create real handler to capture output
        captured = []

        class CaptureHandler(logging.Handler):
            def emit(self, record):
                captured.append(record)

        logger = MagicMock(spec=Logger)
        handler = CaptureHandler()
        handler.setLevel(logging.DEBUG)
        logger.handlers = [handler]
        logger._root_logger = None

        listener = LogQueueListener(queue, logger)
        listener.start()

        try:
            # Put records on queue
            record1 = logging.LogRecord(
                "test", logging.INFO, "test.py", 1, "First", (), None
            )
            record2 = logging.LogRecord(
                "test", logging.WARNING, "test.py", 2, "Second", (), None
            )

            queue.put(record1)
            queue.put(record2)

            # Give listener time to process
            time.sleep(0.1)

            assert len(captured) == 2
            assert captured[0].msg == "First"
            assert captured[1].msg == "Second"

        finally:
            listener.stop()

    def test_stop_with_pending_records(self, queue):
        """Test stop processes remaining records before stopping."""
        captured = []

        class CaptureHandler(logging.Handler):
            def emit(self, record):
                captured.append(record)

        logger = MagicMock(spec=Logger)
        handler = CaptureHandler()
        handler.setLevel(logging.DEBUG)
        logger.handlers = [handler]
        logger._root_logger = None

        listener = LogQueueListener(queue, logger)
        listener.start()

        try:
            # Put record
            record = logging.LogRecord(
                "test", logging.INFO, "test.py", 1, "Before stop", (), None
            )
            queue.put(record)

            time.sleep(0.1)

        finally:
            listener.stop()

        # Record should have been processed
        assert len(captured) >= 1
