# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Logging fixtures for testing.

Provides fixtures for loggers, log handlers, and log capturing.
"""

import logging
from collections.abc import Generator
from io import StringIO

import pytest

from appinfra.log import LogConfig, Logger


@pytest.fixture(autouse=True)
def reset_logging_state() -> Generator[None, None, None]:
    """
    Reset Python logging global state before and after each test.

    This prevents test pollution from loggers created by previous tests.
    Resets: loggerDict, root handlers, root level, and logger class.
    """
    # Store original state
    original_class = logging.getLoggerClass()
    original_handlers = logging.root.handlers[:]
    original_level = logging.root.level

    yield

    # Reset logger class
    logging.setLoggerClass(original_class)

    # Clear all custom loggers from loggerDict
    for name in list(logging.root.manager.loggerDict.keys()):
        if name.startswith("/") or name.startswith("test"):
            del logging.root.manager.loggerDict[name]

    # Restore root logger state
    logging.root.handlers = original_handlers
    logging.root.setLevel(original_level)


@pytest.fixture
def capture_logs() -> Generator[StringIO, None, None]:
    """
    Capture log output for testing.

    Yields:
        StringIO: Stream capturing log output
    """
    log_stream = StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.DEBUG)

    # Add handler to root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    original_level = root_logger.level
    root_logger.setLevel(logging.DEBUG)

    yield log_stream

    # Cleanup
    root_logger.removeHandler(handler)
    root_logger.setLevel(original_level)
    handler.close()


@pytest.fixture
def sample_log_config() -> LogConfig:
    """
    Provide a sample LogConfig for testing.

    Returns:
        LogConfig: Sample log configuration
    """
    return LogConfig.from_params(
        level="debug",
        location=False,
        micros=False,
    )


@pytest.fixture
def test_logger(sample_log_config: LogConfig) -> Logger:
    """
    Provide a test logger instance.

    Args:
        sample_log_config: Sample log configuration fixture

    Returns:
        Logger: Test logger instance
    """
    from appinfra.log import LoggerFactory

    return LoggerFactory.create("test_logger", sample_log_config)


@pytest.fixture
def log_messages() -> list[str]:
    """
    Provide a list to collect log messages during testing.

    Returns:
        list: Empty list for collecting log messages
    """
    return []
