"""
Advanced logging module with enhanced formatting, colored output, custom log levels, and fluent builder API.

This module extends Python's standard logging with:
- Custom TRACE and TRACE2 log levels for detailed debugging
- Colored console output with ANSI escape sequences
- Microsecond precision timestamps
- File location tracking in log messages
- Structured logging with extra fields
- Callback system for log event handling
- Fluent LoggingBuilder API for easy configuration
- JSON logging support for structured output
- Specialized builders for different output types
- Complete logging disable functionality (level=False or level="false")

The module has been refactored into a modular structure while maintaining
backward compatibility with the original API.

Log Level Control:
- Use standard levels: debug, info, warning, error, critical
- Use custom levels: trace, trace2
- Disable logging completely: False or "false"
"""

import logging
import sys
import warnings
from typing import Optional, Union

# Import LoggingBuilder components
from .builder import (
    ConsoleLoggingBuilder,
    FileLoggingBuilder,
    JSONFormatter,
    JSONLoggingBuilder,
    LoggingBuilder,
    create_console_logger,
    create_file_logger,
    create_json_logger,
    create_logger,
    quick_both_logger,
    quick_both_outputs,
    quick_console_and_file,
    quick_console_logger,
    quick_console_with_colors,
    quick_daily_file_logger,
    quick_file_logger,
    quick_file_with_rotation,
    quick_json_console,
    quick_json_file,
)
from .callback import CallbackRegistry, listens_for
from .config import ChildLogConfig, LogConfig

# Import new architecture components
from .constants import LogConstants
from .errors import (
    CallbackError,
    FormatterError,
    InvalidLogLevelError,
    LogConfigError,
    LogError,
    ReservedKeyError,
)
from .factory import LoggerFactory
from .level_manager import LevelRule, LogLevelManager
from .logger import Logger

# Multiprocessing support
from .mp import LogQueueListener, MPQueueHandler
from .reloader import LogConfigReloader

# Define custom log levels for more granular debugging
logging.TRACE = LogConstants.CUSTOM_LEVELS["TRACE"]  # type: ignore[attr-defined]
logging.addLevelName(logging.TRACE, "TRACE")  # type: ignore[attr-defined]

logging.TRACE2 = LogConstants.CUSTOM_LEVELS["TRACE2"]  # type: ignore[attr-defined]
logging.addLevelName(logging.TRACE2, "TRACE2")  # type: ignore[attr-defined]

# Update LEVEL_NAMES with custom levels
LogConstants.LEVEL_NAMES.update(
    {
        "trace": logging.TRACE,  # type: ignore[attr-defined]
        "trace2": logging.TRACE2,  # type: ignore[attr-defined]
    }
)

# Update colors for custom levels
from .colors import ColorManager

ColorManager.add_custom_level_colors()


def resolve_level(s: str | int | bool) -> int | bool:
    """
    Resolve log level from string, numeric value, or boolean.

    Args:
        s: Log level as string name, numeric value, or False to disable logging

    Returns:
        Union[int, bool]: Numeric log level or False to disable logging

    Raises:
        InvalidLogLevelError: If the log level is invalid
    """
    if isinstance(s, bool):
        return s

    if str(s).isnumeric():
        return int(s)

    # Convert to string for dict lookup
    s_str = str(s) if isinstance(s, int) else s
    if s_str in LogConstants.LEVEL_NAMES:
        return LogConstants.LEVEL_NAMES[s_str]

    raise InvalidLogLevelError(s)


# Convenience functions for simple logger creation
def create_root_lg(
    level: str | int = "info",
    location: bool | int = False,
    micros: bool = False,
    cls: type[Logger] = Logger,
) -> Logger:
    """
    Create a root logger with the specified configuration.

    Convenience function that wraps LoggerFactory.create_root() with simplified
    parameter passing. Recommended for simple logger creation without needing
    to construct a LogConfig object explicitly.

    Args:
        level: Log level (string or numeric)
        location: Whether to show file locations in logs
        micros: Whether to show microsecond precision
        cls: Logger class to use

    Returns:
        Logger: Configured root logger

    Example:
        >>> lg = create_root_lg("debug", location=True)

    Note:
        For more complex configurations, use LoggerFactory.create_root() with
        a custom LogConfig object.
    """
    config = LogConfig.from_params(level, location, micros)
    return LoggerFactory.create_root(config, cls)


def create_lg(
    name: str,
    level: str | int,
    location: int = 0,
    micros: bool = False,
    cls: type[Logger] = Logger,
) -> Logger:
    """
    Create a logger with the specified configuration.

    Convenience function that wraps LoggerFactory.create() with simplified
    parameter passing. Recommended for simple logger creation without needing
    to construct a LogConfig object explicitly.

    Args:
        name: Logger name
        level: Log level (string or numeric)
        location: Number of stack levels to show in location info
        micros: Whether to show microsecond precision
        cls: Logger class to use

    Returns:
        Logger: Configured logger instance

    Example:
        >>> lg = create_lg("myapp", "info", location=1)

    Note:
        For more complex configurations, use LoggerFactory.create() with
        a custom LogConfig object.
    """
    config = LogConfig.from_params(level, location, micros)
    return LoggerFactory.create(name, config, cls)


def derive_lg(lg: Logger, tags: str | list, cls: type[Logger] | None = None) -> Logger:
    """
    Derive a logger with tags from a parent logger.

    Convenience function that wraps LoggerFactory.derive() with automatic
    parent class detection. Recommended for simple logger derivation cases.

    Args:
        lg: Parent logger instance
        tags: Single tag or list of tags
        cls: Logger class to use (defaults to parent's class)

    Returns:
        Logger: Derived logger instance

    Example:
        >>> parent_lg = create_root_lg("info")
        >>> child_lg = derive_lg(parent_lg, "subsystem")

    Note:
        For more control over derived logger configuration, use
        LoggerFactory.derive() directly.
    """
    if cls is None:
        cls = lg.__class__

    return LoggerFactory.derive(lg, tags)


def _create_capture_handler(
    config: LogConfig, numeric_level: int
) -> logging.StreamHandler:
    """Create handler with appinfra formatter for capture_all_loggers."""
    from .config_holder import LogConfigHolder
    from .formatters import LogFormatter

    holder = LogConfigHolder(config)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(LogFormatter(holder))
    handler.setLevel(numeric_level)
    return handler


def capture_all_loggers(
    level: str | int = "info",
    clear_handlers: bool = True,
    colors: bool = True,
    location: bool | int = False,
    micros: bool = False,
) -> None:
    """
    Capture all Python logging and route through appinfra's formatted handler.

    Useful for unifying log output from third-party libraries (requests, sqlalchemy, boto3, etc.)
    with your application's logging format.

    Args:
        level: Log level for the root logger (e.g., "info", "debug", or False to disable)
        clear_handlers: If True, remove existing handlers from all loggers
        colors: Enable colored console output
        location: Show file locations in log messages
        micros: Show microsecond precision in timestamps

    Example:
        >>> from appinfra.log import capture_all_loggers
        >>> capture_all_loggers(level="info")
        >>> # Now all loggers (including third-party) use appinfra formatting
    """
    numeric_level = resolve_level(level)
    if numeric_level is False:
        logging.disable(logging.CRITICAL)
        return

    config = LogConfig.from_params(level, location, micros, colors=colors)
    handler = _create_capture_handler(config, numeric_level)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric_level)

    for name in list(logging.Logger.manager.loggerDict.keys()):
        logger = logging.getLogger(name)
        if clear_handlers:
            logger.handlers.clear()
        logger.propagate = True


def capture_logger(name: str, level: str | int | None = None) -> None:
    """
    Pre-capture a logger to ensure it uses appinfra formatting.

    Call this before a third-party library creates its logger. The logger will
    propagate to the root handler set by capture_all_loggers().

    Args:
        name: Logger name (e.g., "urllib3", "sqlalchemy.engine")
        level: Optional level override. If None, inherits from root.

    Example:
        >>> from appinfra.log import capture_all_loggers, capture_logger
        >>> capture_all_loggers(level="info")
        >>> capture_logger("urllib3", level="warning")  # Pre-capture before import
        >>> import urllib3  # Logger already configured
    """
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = True

    if level is not None:
        numeric_level = resolve_level(level)
        if numeric_level is not False:
            logger.setLevel(numeric_level)


# Export all public classes and functions
__all__ = [
    # Core classes
    "Logger",
    "LoggerFactory",
    "CallbackRegistry",
    "LogConfig",
    "ChildLogConfig",
    "LogConstants",
    "LogLevelManager",
    "LevelRule",
    "LogConfigReloader",
    # Multiprocessing support
    "MPQueueHandler",
    "LogQueueListener",
    # Exception classes
    "LogError",
    "InvalidLogLevelError",
    "LogConfigError",
    "FormatterError",
    "CallbackError",
    "ReservedKeyError",
    # LoggingBuilder classes
    "LoggingBuilder",
    "ConsoleLoggingBuilder",
    "FileLoggingBuilder",
    "JSONLoggingBuilder",
    "JSONFormatter",
    # Builder factory functions
    "create_logger",
    "create_console_logger",
    "create_file_logger",
    "create_multi_output_logger",
    "create_json_logger",
    # Quick setup functions
    "quick_console_logger",
    "quick_file_logger",
    "quick_both_logger",
    "quick_console_with_colors",
    "quick_file_with_rotation",
    "quick_daily_file_logger",
    "quick_console_and_file",
    "quick_json_console",
    "quick_json_file",
    "quick_both_outputs",
    # Utility functions
    "resolve_level",
    "capture_all_loggers",
    "capture_logger",
    "listens_for",
    # Backward compatibility functions
    "create_root_lg",
    "create_lg",
    "derive_lg",
]
