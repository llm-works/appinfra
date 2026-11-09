# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for MPQueueHandler that put records on a multiprocessing queue, which starts its
feeder thread."""

import logging
from multiprocessing import Queue

import pytest

from appinfra.log.mp import MPQueueHandler


@pytest.fixture(autouse=True)
def reset_level_manager():
    """Reset LogLevelManager singleton before and after each test."""
    from appinfra.log import LogLevelManager

    LogLevelManager.reset_instance()
    yield
    LogLevelManager.reset_instance()


@pytest.fixture
def queue():
    """Create a multiprocessing queue for testing."""
    return Queue()


@pytest.fixture
def handler(queue):
    """Create an MPQueueHandler for testing."""
    return MPQueueHandler(queue)


@pytest.fixture
def log_record():
    """Create a basic log record for testing."""
    return logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="/test/file.py",
        lineno=42,
        msg="Test message",
        args=(),
        exc_info=None,
    )


class TestMPQueueHandlerEmit:
    """Test MPQueueHandler.emit() method."""

    def test_emit_puts_record_on_queue(self, handler, queue, log_record):
        """Test emit puts prepared record on queue."""
        handler.emit(log_record)

        result = queue.get(timeout=1)
        assert result.name == "test.logger"
        assert result.levelno == logging.INFO
        assert result.msg == "Test message"

    def test_emit_formats_message_args(self, handler, queue):
        """Test emit formats message with args."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg="Value: %s",
            args=("hello",),
            exc_info=None,
        )

        handler.emit(record)
        result = queue.get(timeout=1)

        assert result.msg == "Value: hello"
        assert result.args is None


class TestLoggerWithQueue:
    """Test Logger.with_queue() class method."""

    def test_with_queue_logs_to_queue(self, queue):
        """Test logger created with_queue sends records to queue."""
        from appinfra.log import Logger

        lg = Logger.with_queue(queue, name="test.queue")
        lg.info("test message")

        record = queue.get(timeout=1)
        assert record.msg == "test message"


class TestMPQueueHandlerIntegration:
    """Integration tests for MPQueueHandler."""

    def test_full_logging_flow(self, queue):
        """Test complete logging flow through queue handler."""
        logger = logging.getLogger("test.mp.handler")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        handler = MPQueueHandler(queue)
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        logger.info("Test info message")
        logger.warning("Test warning")

        record1 = queue.get(timeout=1)
        record2 = queue.get(timeout=1)

        assert record1.msg == "Test info message"
        assert record1.levelno == logging.INFO
        assert record2.msg == "Test warning"
        assert record2.levelno == logging.WARNING

    def test_exception_logging_flow(self, queue):
        """Test exception is properly captured and formatted."""
        logger = logging.getLogger("test.mp.exc")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()

        handler = MPQueueHandler(queue)
        logger.addHandler(handler)

        try:
            raise KeyError("missing key")
        except KeyError:
            logger.exception("Error occurred")

        record = queue.get(timeout=1)

        assert record.exc_info is None  # Cleared
        assert record.exc_text is not None  # Formatted
        assert "KeyError" in record.exc_text
        assert "missing key" in record.exc_text


class TestLoggerQueueConfig:
    """Test Logger.queue_config() and Logger.from_queue_config() methods."""

    def test_from_queue_config_logs_to_queue(self, queue):
        """Test logger from from_queue_config sends records to queue."""
        from appinfra.log import Logger

        config = {"queue": queue, "level": logging.INFO}
        lg = Logger.from_queue_config(config, name="worker")
        lg.info("test message from worker")

        record = queue.get(timeout=1)
        assert record.msg == "test message from worker"
        assert record.name == "worker"
