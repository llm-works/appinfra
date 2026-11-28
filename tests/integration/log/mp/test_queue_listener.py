# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for LogQueueListener running its listener thread or feeding its queue."""

import logging
import queue as queue_module
import threading
import time
from multiprocessing import Queue
from unittest.mock import MagicMock

import pytest

from appinfra.log import Logger
from appinfra.log.mp import LogQueueListener

# Waits on the listener thread end on an event its handler sets; running out of this
# timeout is the failure, never the expected path.
_TIMEOUT = 5.0


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
        second_handled = threading.Event()

        def error_then_succeed(record):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Unexpected error")
            original_handle(record)
            second_handled.set()

        listener._handle_record = error_then_succeed
        listener.start()

        try:
            # First record causes error; the listener handles records in order, so once
            # the second is handled the first one's error has been written
            record1 = logging.LogRecord(
                "test", logging.INFO, "test.py", 1, "First", (), None
            )
            record2 = logging.LogRecord(
                "test", logging.INFO, "test.py", 2, "Second", (), None
            )
            queue.put(record1)
            queue.put(record2)
            assert second_handled.wait(timeout=_TIMEOUT)

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


def _raises(error: type[Exception]) -> None:
    """Rebuilds an Undecodable: raises *error*, as unpickling it in get() does."""
    raise error("cannot decode")


class Undecodable:
    """Pickles fine; unpickling it raises the error it was made with."""

    def __init__(self, error: type[Exception]) -> None:
        self.error = error

    def __reduce__(self) -> tuple[object, tuple[type[Exception]]]:
        return (_raises, (self.error,))


class TestLogQueueListenerDecodeErrors:
    """A record get() cannot decode is reported and skipped: the listener goes on."""

    @pytest.mark.parametrize("error", [AttributeError, ValueError])
    def test_a_record_after_an_undecodable_one_is_handled(
        self, queue, mock_logger, error, capsys
    ):
        listener = LogQueueListener(queue, mock_logger)
        handled = threading.Event()
        listener._handle_record = lambda record: handled.set()
        listener.start()
        try:
            queue.put(Undecodable(error))
            queue.put(logging.LogRecord("t", logging.INFO, "t.py", 1, "ok", (), None))
            assert handled.wait(_TIMEOUT)
            assert listener.is_alive
            assert "error decoding record" in capsys.readouterr().err
        finally:
            listener.stop()

    def test_a_queue_closed_under_it_ends_the_listener(self, queue, mock_logger):
        """Closed, the queue raises from get() on every read: the listener
        ends instead of reporting it forever."""
        listener = LogQueueListener(queue, mock_logger)
        listener.start()
        thread = listener._thread
        queue.close()
        thread.join(_TIMEOUT)
        assert not thread.is_alive()


class TestLogQueueListenerCloseQueue:
    """stop(close_queue=True) closes the queue once nothing is left to read."""

    def test_a_listener_never_started_closes_the_queue_at_once(
        self, queue, mock_logger
    ):
        LogQueueListener(queue, mock_logger).stop(close_queue=True)
        assert queue._closed

    def test_a_running_listener_closes_the_queue_as_it_ends(self, queue, mock_logger):
        listener = LogQueueListener(queue, mock_logger)
        listener.start()
        thread = listener._thread
        listener.stop(close_queue=True)
        thread.join(_TIMEOUT)
        assert queue._closed


class TestLogQueueListenerStopDrains:
    """stop() lets the listener handle every record queued before its sentinel."""

    def test_records_queued_behind_a_slow_one_are_handled(self, mock_logger):
        """The handler is still on the first record when stop() is called: the
        two queued behind it are handled before the listener ends."""
        records = queue_module.Queue()
        listener = LogQueueListener(records, mock_logger)
        handled: list[str] = []
        entered, release = threading.Event(), threading.Event()

        def slow_first(record: logging.LogRecord) -> None:
            if not handled:
                entered.set()
                release.wait(_TIMEOUT)
            handled.append(record.getMessage())

        listener._handle_record = slow_first
        listener.start()
        for i in range(3):
            records.put(
                logging.LogRecord("t", logging.INFO, "t.py", i, f"r{i}", (), None)
            )
        assert entered.wait(_TIMEOUT)
        stopping = threading.Thread(target=listener.stop)
        stopping.start()
        assert listener._stop_event.wait(_TIMEOUT)  # stop() is under way
        release.set()
        stopping.join(_TIMEOUT)
        assert handled == ["r0", "r1", "r2"]


class TestLogQueueListenerIntegration:
    """Integration tests for LogQueueListener."""

    def test_full_queue_flow(self, queue):
        """Test complete flow: put record on queue, listener processes it."""
        # Create real handler to capture output
        captured = []
        both_captured = threading.Event()

        class CaptureHandler(logging.Handler):
            def emit(self, record):
                captured.append(record)
                if len(captured) == 2:
                    both_captured.set()

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

            assert both_captured.wait(timeout=_TIMEOUT)

            assert len(captured) == 2
            assert captured[0].msg == "First"
            assert captured[1].msg == "Second"

        finally:
            listener.stop()
