# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Custom exceptions for the logging system.

This module defines the exception hierarchy used throughout the logging system
for better error handling and debugging.
"""

from typing import Any


class LogError(Exception):
    """Base exception for logging-related errors."""

    pass


class InvalidLogLevelError(LogError):
    """Raised when an invalid log level is specified."""

    def __init__(self, level: Any) -> None:
        self.level = level
        super().__init__(f"Invalid log level: {level}")


class LogConfigError(LogError):
    """Raised when there's an error in logger configuration."""

    pass


class LoggerExistsError(LogConfigError):
    """
    A logger with this name already exists.

    Creating a logger never touches an existing one: a name used twice is almost always
    an accident, and reconfiguring silently would change the first logger under its
    owner. Use ``LoggerFactory.reconfigure`` to change it on purpose, or
    ``LoggerFactory.destroy`` before creating the name again.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"logger {name!r} already exists")


class LoggerNotFoundError(LogConfigError):
    """No appinfra logger with this name exists."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"no logger named {name!r}")


class FormatterError(LogError):
    """Raised when there's an error in log formatting."""

    pass


class CallbackError(LogError):
    """Raised when there's an error in callback execution."""

    pass


class ReservedKeyError(LogError):
    """Raised when a reserved key is used in log extra dict.

    Reserved keys are LogRecord attributes like 'name', 'message', 'levelname',
    etc. that cannot be overwritten via the 'extra' parameter.
    """

    def __init__(self, keys: set[str]) -> None:
        self.keys = frozenset(keys)
        keys_str = ", ".join(sorted(keys))
        super().__init__(
            f"Reserved key(s) in log extra: {keys_str}. "
            f"These are LogRecord attributes and cannot be used."
        )
