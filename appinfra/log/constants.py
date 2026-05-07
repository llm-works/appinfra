"""
Constants and configuration values for the logging system.

This module contains all the constant values used throughout the logging system,
including format strings, default values, and custom log level definitions.
"""

import logging


class LogConstants:
    """Constants for the logging system."""

    # Default format strings
    DEFAULT_FORMAT: str = "[%(asctime)s] [%(levelname).1s] %(message)s"

    # Rule widths for formatting
    DEFAULT_RULE_WIDTH: int = 70
    MICRO_RULE_WIDTH: int = 74

    # Default separator timing
    DEFAULT_SEPARATOR_SECS: float = 5.0

    # Custom log levels
    CUSTOM_LEVELS: dict[str, int] = {"TRACE": 5, "TRACE2": 4}

    # Log level names for resolution (will be populated after custom levels are defined)
    LEVEL_NAMES: dict[str, int | bool] = {
        "error": logging.ERROR,
        "warning": logging.WARNING,
        "info": logging.INFO,
        "debug": logging.DEBUG,
        "false": False,  # Special value to disable all logging
    }

    # Reserved keys that cannot be used in 'extra' dict
    # These are LogRecord attributes that would be overwritten
    RESERVED_EXTRA_KEYS: frozenset[str] = frozenset(
        {
            "args",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "taskName",
            "thread",
            "threadName",
            # Also reserve 'message' and 'asctime' which are checked by makeRecord()
            "message",
            "asctime",
        }
    )

    # ANSI escape sequences
    RESET: str = "\x1b[0m"

    # Color base codes
    COLOR_BASE: str = "\x1b[3"

    # Gray level range for trace logging
    GRAY_BASE: int = 232
    GRAY_MAX_LEVELS: int = 24
