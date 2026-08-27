# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Interface for logging builders.

This module defines the abstract interface that all logging builders must implement,
ensuring consistent API across different builder implementations.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Self

from ..config import LogConfig
from ..logger import Logger


class HandlerConfig(ABC):
    """Base class for handler configurations."""

    def __init__(self, level: str | int | None = None) -> None:
        self.level = level

    @abstractmethod
    def create_handler(self, config: LogConfig, logger: Any = None) -> logging.Handler:
        """Create the actual handler instance.

        Args:
            config: Logger configuration
            logger: Optional logger instance for error logging (required for DatabaseHandler)
        """
        pass  # pragma: no cover

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """
        Serialize handler config to a picklable dictionary.

        Used for passing handler configuration to subprocesses.

        Returns:
            Dictionary with handler type and all parameters
        """
        pass  # pragma: no cover


class LoggingBuilderInterface(ABC):
    """
    Abstract interface for logging builders.

    Defines the contract that all logging builder implementations must follow,
    ensuring consistent API and behavior across different builder types.
    """

    @abstractmethod
    def with_level(self, level: str | int) -> Self:
        """
        Set the log level.

        Args:
            level: Log level (string name or numeric value)

        Returns:
            Self for method chaining
        """
        pass  # pragma: no cover

    @abstractmethod
    def with_location(self, location: bool | int) -> Self:
        """
        Set the location display level.

        Args:
            location: Location display level (bool or int)

        Returns:
            Self for method chaining
        """
        pass  # pragma: no cover

    @abstractmethod
    def with_micros(self, micros: bool = True) -> Self:
        """
        Enable or disable microsecond precision.

        Args:
            micros: Whether to show microsecond precision

        Returns:
            Self for method chaining
        """
        pass  # pragma: no cover

    @abstractmethod
    def with_colors(self, enabled: bool = True) -> Self:
        """
        Enable or disable colored output.

        Args:
            enabled: Whether to enable colors

        Returns:
            Self for method chaining
        """
        pass  # pragma: no cover

    @abstractmethod
    def with_config(self, config: dict[str, Any]) -> Self:
        """
        Set multiple configuration parameters at once.

        Args:
            config: Configuration dictionary with keys:
                - level: Log level (string name, numeric value, or False to disable logging)
                - location: Location display level (bool or int)
                - micros: Whether to show microsecond precision
                - colors: Whether to enable colored output

        Returns:
            Self for method chaining
        """
        pass  # pragma: no cover

    @abstractmethod
    def with_extra(self, **kwargs: Any) -> Self:
        """
        Add extra fields to pre-populate in log records.

        These fields will be automatically included in all log records
        created by this logger, and can be extended during individual log calls.

        Args:
            **kwargs: Extra fields to pre-populate (e.g., service="api", version="1.0.0")

        Returns:
            Self for method chaining
        """
        pass  # pragma: no cover

    @abstractmethod
    def with_handler(self, handler_config: HandlerConfig) -> Self:
        """
        Add a handler configuration.

        Args:
            handler_config: Handler configuration instance

        Returns:
            Self for method chaining
        """
        pass  # pragma: no cover

    @abstractmethod
    def with_console_handler(
        self, stream: Any = None, level: str | int | None = None
    ) -> Self:
        """
        Add a console handler.

        Args:
            stream: Output stream (defaults to stdout)
            level: Handler level (defaults to logger level)

        Returns:
            Self for method chaining
        """
        pass  # pragma: no cover

    @abstractmethod
    def with_file_handler(
        self,
        file_path: str | Path,
        level: str | int | None = None,
        **kwargs: Any,
    ) -> Self:
        """
        Add a file handler.

        Args:
            file_path: Path to log file
            level: Handler level (defaults to logger level)
            **kwargs: Additional file handler arguments

        Returns:
            Self for method chaining
        """
        pass  # pragma: no cover

    @abstractmethod
    def with_rotating_file_handler(
        self,
        file_path: str | Path,
        max_bytes: int = 0,
        backup_count: int = 0,
        level: str | int | None = None,
        **kwargs: Any,
    ) -> Self:
        """
        Add a rotating file handler.

        Args:
            file_path: Path to log file
            max_bytes: Maximum file size before rotation
            backup_count: Number of backup files to keep
            level: Handler level (defaults to logger level)
            **kwargs: Additional handler arguments

        Returns:
            Self for method chaining
        """
        pass  # pragma: no cover

    @abstractmethod
    def with_timed_rotating_file_handler(
        self,
        file_path: str | Path,
        when: str = "h",
        interval: int = 1,
        backup_count: int = 0,
        level: str | int | None = None,
        **kwargs: Any,
    ) -> Self:
        """
        Add a timed rotating file handler.

        Args:
            file_path: Path to log file
            when: Rotation interval
            interval: Number of intervals between rotations
            backup_count: Number of backup files to keep
            level: Handler level (defaults to logger level)
            **kwargs: Additional handler arguments

        Returns:
            Self for method chaining
        """
        pass  # pragma: no cover

    @abstractmethod
    def build(self) -> Logger:
        """
        Build and return the configured logger.

        Returns:
            Configured logger instance
        """
        pass  # pragma: no cover
