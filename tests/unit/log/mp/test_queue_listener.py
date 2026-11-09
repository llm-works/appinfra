# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for LogQueueListener - receives log records from subprocesses."""

import logging
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


class TestLogQueueListenerIsAlive:
    """Test is_alive property."""

    def test_is_alive_false_when_not_started(self, listener):
        """Test is_alive is False before start."""
        assert not listener.is_alive


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
