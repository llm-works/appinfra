# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
File logging builder for file-only output.

This module provides a specialized builder that extends the base LoggingBuilder
for file-only logging with various file handling options.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import LogConfig
from ..formatters import LogFormatter
from .builder import LoggingBuilder
from .interface import HandlerConfig


def _create_formatter(config: LogConfig, logger: Any = None) -> LogFormatter:
    """Create formatter with hot-reload support if logger has holder."""
    if logger is not None and hasattr(logger, "_holder") and logger._holder is not None:
        return LogFormatter(logger._holder)
    return LogFormatter(config)


if TYPE_CHECKING:
    from typing import Self


class FileHandlerConfig(HandlerConfig):
    """Configuration for file handlers."""

    def __init__(
        self,
        filename: str | Path,
        mode: str = "a",
        encoding: str | None = None,
        delay: bool = False,
        level: str | int | None = None,
    ):
        super().__init__(level)
        self.filename = filename
        self.mode = mode
        self.encoding = encoding
        self.delay = delay

    def to_dict(self) -> dict[str, Any]:
        """Serialize to picklable dictionary."""
        d: dict[str, Any] = {
            "type": "file",
            "filename": str(self.filename),
            "mode": self.mode,
            "delay": self.delay,
        }
        if self.level is not None:
            d["level"] = self.level
        if self.encoding is not None:
            d["encoding"] = self.encoding
        return d

    def create_handler(self, config: LogConfig, logger: Any = None) -> logging.Handler:
        """Create a file handler."""
        # Ensure directory exists
        path = Path(self.filename)
        if path.parent != path:  # Not just a filename
            path.parent.mkdir(parents=True, exist_ok=True)

        handler = logging.FileHandler(
            self.filename, mode=self.mode, encoding=self.encoding, delay=self.delay
        )
        # Set handler level with proper resolution
        level = self.level or config.level
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        handler.setLevel(level)

        formatter = _create_formatter(config, logger)
        handler.setFormatter(formatter)
        return handler


class RotatingFileHandlerConfig(HandlerConfig):
    """Configuration for rotating file handlers."""

    def __init__(
        self,
        filename: str | Path,
        max_bytes: int = 0,
        backup_count: int = 0,
        encoding: str | None = None,
        delay: bool = False,
        level: str | int | None = None,
    ):
        super().__init__(level)
        self.filename = filename
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.encoding = encoding
        self.delay = delay

    def to_dict(self) -> dict[str, Any]:
        """Serialize to picklable dictionary."""
        d: dict[str, Any] = {
            "type": "rotating_file",
            "filename": str(self.filename),
            "max_bytes": self.max_bytes,
            "backup_count": self.backup_count,
            "delay": self.delay,
        }
        if self.level is not None:
            d["level"] = self.level
        if self.encoding is not None:
            d["encoding"] = self.encoding
        return d

    def create_handler(self, config: LogConfig, logger: Any = None) -> logging.Handler:
        """Create a rotating file handler."""
        # Ensure directory exists
        path = Path(self.filename)
        if path.parent != path:  # Not just a filename
            path.parent.mkdir(parents=True, exist_ok=True)

        handler = logging.handlers.RotatingFileHandler(
            self.filename,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding=self.encoding,
            delay=self.delay,
        )
        # Set handler level with proper resolution
        level = self.level or config.level
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        handler.setLevel(level)

        formatter = _create_formatter(config, logger)
        handler.setFormatter(formatter)
        return handler


class TimedRotatingFileHandlerConfig(HandlerConfig):
    """Configuration for timed rotating file handlers."""

    def __init__(
        self,
        filename: str | Path,
        when: str = "h",
        interval: int = 1,
        backup_count: int = 0,
        encoding: str | None = None,
        delay: bool = False,
        utc: bool = False,
        level: str | int | None = None,
    ):
        super().__init__(level)
        self.filename = filename
        self.when = when
        self.interval = interval
        self.backup_count = backup_count
        self.encoding = encoding
        self.delay = delay
        self.utc = utc

    def to_dict(self) -> dict[str, Any]:
        """Serialize to picklable dictionary."""
        d: dict[str, Any] = {
            "type": "timed_rotating_file",
            "filename": str(self.filename),
            "when": self.when,
            "interval": self.interval,
            "backup_count": self.backup_count,
            "delay": self.delay,
            "utc": self.utc,
        }
        if self.level is not None:
            d["level"] = self.level
        if self.encoding is not None:
            d["encoding"] = self.encoding
        return d

    def create_handler(self, config: LogConfig, logger: Any = None) -> logging.Handler:
        """Create a timed rotating file handler."""
        # Ensure directory exists
        path = Path(self.filename)
        if path.parent != path:  # Not just a filename
            path.parent.mkdir(parents=True, exist_ok=True)

        handler = logging.handlers.TimedRotatingFileHandler(
            self.filename,
            when=self.when,
            interval=self.interval,
            backupCount=self.backup_count,
            encoding=self.encoding,
            delay=self.delay,
            utc=self.utc,
        )
        # Set handler level with proper resolution
        level = self.level or config.level
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        handler.setLevel(level)

        formatter = _create_formatter(config, logger)
        handler.setFormatter(formatter)
        return handler


class FileLoggingBuilder(LoggingBuilder):
    """
    Specialized builder for file-only logging.

    Provides convenient methods for configuring file output with
    various file handling options.
    """

    def __init__(self, name: str, file_path: str | Path):
        """
        Initialize file logging builder.

        Args:
            name: Logger name
            file_path: Path to log file
        """
        super().__init__(name)
        self._file_path = file_path
        # Default to file handler
        self.with_file_handler(file_path)

    def with_rotation(self, max_bytes: int = 0, backup_count: int = 0) -> Self:
        """
        Enable file rotation.

        Args:
            max_bytes: Maximum file size before rotation
            backup_count: Number of backup files to keep

        Returns:
            Self for method chaining
        """
        # Remove existing file handler and add rotating one
        self._handlers = [
            h
            for h in self._handlers
            if not isinstance(
                h,
                (
                    FileHandlerConfig,
                    RotatingFileHandlerConfig,
                    TimedRotatingFileHandlerConfig,
                ),
            )
        ]
        self.with_rotating_file_handler(self._file_path, max_bytes, backup_count)
        return self

    def with_timed_rotation(
        self, when: str = "h", interval: int = 1, backup_count: int = 0
    ) -> Self:
        """
        Enable time-based file rotation.

        Args:
            when: Rotation interval ('S', 'M', 'H', 'D', 'W0'-'W6', 'midnight')
            interval: Number of intervals between rotations
            backup_count: Number of backup files to keep

        Returns:
            Self for method chaining
        """
        # Remove existing file handler and add timed rotating one
        self._handlers = [
            h
            for h in self._handlers
            if not isinstance(
                h,
                (
                    FileHandlerConfig,
                    RotatingFileHandlerConfig,
                    TimedRotatingFileHandlerConfig,
                ),
            )
        ]
        self.with_timed_rotating_file_handler(
            self._file_path, when, interval, backup_count
        )
        return self

    def daily_rotation(self, backup_count: int = 7) -> Self:
        """
        Enable daily file rotation.

        Args:
            backup_count: Number of daily backup files to keep

        Returns:
            Self for method chaining
        """
        return self.with_timed_rotation(
            when="midnight", interval=1, backup_count=backup_count
        )

    def hourly_rotation(self, backup_count: int = 24) -> Self:
        """
        Enable hourly file rotation.

        Args:
            backup_count: Number of hourly backup files to keep

        Returns:
            Self for method chaining
        """
        return self.with_timed_rotation(when="H", interval=1, backup_count=backup_count)

    def weekly_rotation(self, backup_count: int = 4) -> Self:
        """
        Enable weekly file rotation.

        Args:
            backup_count: Number of weekly backup files to keep

        Returns:
            Self for method chaining
        """
        return self.with_timed_rotation(
            when="W0", interval=1, backup_count=backup_count
        )


# Convenience function for file builder
def create_file_logger(name: str, file_path: str | Path) -> FileLoggingBuilder:
    """
    Create a file logging builder.

    Args:
        name: Logger name
        file_path: Path to log file

    Returns:
        FileLoggingBuilder instance
    """
    return FileLoggingBuilder(name, file_path)


# Quick setup functions for file builder
# Note: Quick functions have been moved to quick.py
