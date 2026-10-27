# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Custom exceptions for the logging system.

This module defines the exception hierarchy used throughout the logging system
for better error handling and debugging.

An exception with constructor arguments passes them, unchanged, to
``Exception.__init__`` and builds its message in ``__str__``: unpickling calls
``cls(*args)``, so this is what lets it cross a process boundary intact.
"""

from typing import Any


class LogError(Exception):
    """Base exception for logging-related errors."""


class InvalidLogLevelError(LogError):
    """Raised when an invalid log level is specified."""

    def __init__(self, level: Any) -> None:
        self.level = level
        super().__init__(level)

    def __str__(self) -> str:
        return f"Invalid log level: {self.level}"


class LogConfigError(LogError):
    """Raised when there's an error in logger configuration."""


class LoggerExistsError(LogConfigError):
    """
    An appinfra logger with this name already exists.

    Creating a logger never touches an existing appinfra one: a name used twice is
    almost always an accident, and reconfiguring silently would change the first logger
    under its owner. Use ``LoggerFactory.reconfigure`` to change it on purpose, or
    ``LoggerFactory.destroy`` before creating the name again. (A library's plain stdlib
    logger under the name is taken over instead; see ``LoggerFactory.create``.)
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(name)

    def __str__(self) -> str:
        return f"logger {self.name!r} already exists"


class LoggerNotFoundError(LogConfigError):
    """No appinfra logger with this name exists."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(name)

    def __str__(self) -> str:
        return f"no logger named {self.name!r}"


class FormatterError(LogError):
    """Raised when there's an error in log formatting."""


class CallbackError(LogError):
    """Raised when there's an error in callback execution."""


class ReservedKeyError(LogError):
    """Raised when a reserved key is used in log extra dict.

    Reserved keys are LogRecord attributes like 'name', 'message', 'levelname',
    etc. that cannot be overwritten via the 'extra' parameter.
    """

    def __init__(self, keys: set[str]) -> None:
        self.keys = frozenset(keys)
        super().__init__(self.keys)

    def __str__(self) -> str:
        keys_str = ", ".join(sorted(self.keys))
        return (
            f"Reserved key(s) in log extra: {keys_str}. "
            f"These are LogRecord attributes and cannot be used."
        )
