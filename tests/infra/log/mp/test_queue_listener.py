# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for LogQueueListener - receives log records from subprocesses."""

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


@pytest.fixture
def log_record():
    """Create a basic log record for testing."""
    return logging.LogRecord(
        name="subprocess.logger",
        level=logging.INFO,
        pathname="/subprocess/file.py",
        lineno=100,
        msg="Message from subprocess",
        args=(),
        exc_info=None,
    )


@pytest.mark.unit
class TestLogQueueListenerInit:
    """Test LogQueueListener initialization."""

    def test_basic_initialization(self, queue, mock_logger):
        """Test listener initializes with queue and logger."""
        listener = LogQueueListener(queue, mock_logger)

        assert listener._queue is queue
        assert listener._logger is mock_logger
        assert listener._respect_handler_level is True
        assert listener._thread is None

    def test_initialization_with_respect_handler_level_false(self, queue, mock_logger):
        """Test listener can disable handler level filtering."""
        listener = LogQueueListener(queue, mock_logger, respect_handler_level=False)

        assert listener._respect_handler_level is False


@pytest.mark.unit
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


@pytest.mark.unit
class TestLogQueueListenerIsAlive:
    """Test is_alive property."""

    def test_is_alive_false_when_not_started(self, listener):
        """Test is_alive is False before start."""
        assert not listener.is_alive

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


@pytest.mark.unit
class TestLogQueueListenerHandleRecord:
    """Test _handle_record() method."""

    def test_handle_record_dispatches_to_handler(
        self, listener, log_record, mock_logger
    ):
        """Test record is dispatched to logger's handlers."""
        listener._handle_record(log_record)

        handler = mock_logger.handlers[0]
        handler.handle.assert_called_once_with(log_record)

    def test_handle_record_respects_handler_level(self, queue, mock_logger, log_record):
        """Test records below handler level are not dispatched."""
        handler = mock_logger.handlers[0]
        handler.level = logging.WARNING  # Higher than INFO

        listener = LogQueueListener(queue, mock_logger, respect_handler_level=True)
        listener._handle_record(log_record)

        handler.handle.assert_not_called()

    def test_handle_record_ignores_level_when_disabled(
        self, queue, mock_logger, log_record
    ):
        """Test handler level is ignored when respect_handler_level=False."""
        handler = mock_logger.handlers[0]
        handler.level = logging.WARNING  # Higher than INFO

        listener = LogQueueListener(queue, mock_logger, respect_handler_level=False)
        listener._handle_record(log_record)

        handler.handle.assert_called_once_with(log_record)

    def test_handle_record_uses_root_logger_handlers(self, queue, log_record):
        """Test view loggers use root logger's handlers."""
        root_handler = MagicMock(spec=logging.Handler)
        root_handler.level = logging.DEBUG

        root_logger = MagicMock(spec=Logger)
        root_logger.handlers = [root_handler]

        view_logger = MagicMock(spec=Logger)
        view_logger.handlers = []
        view_logger._root_logger = root_logger

        listener = LogQueueListener(queue, view_logger)
        listener._handle_record(log_record)

        root_handler.handle.assert_called_once_with(log_record)

    def test_handle_record_catches_handler_errors(
        self, listener, log_record, mock_logger
    ):
        """Test handler errors are caught and don't crash listener."""
        handler = mock_logger.handlers[0]
        handler.handle.side_effect = Exception("Handler failed")

        # Should not raise
        listener._handle_record(log_record)

        handler.handleError.assert_called_once_with(log_record)


@pytest.mark.unit
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


@pytest.mark.integration
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
