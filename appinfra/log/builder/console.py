# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Console logging builder for console-only output.

This module provides a specialized builder that extends the base LoggingBuilder
for console-only logging with various formatting options.
"""

import logging
import sys
from typing import Any, Self

from ..config import LogConfig
from ..formatters import LogFormatter
from .builder import LoggingBuilder
from .interface import HandlerConfig
from .json import JSONFormatter


def _create_text_formatter(config: LogConfig, logger: Any = None) -> LogFormatter:
    """Create text formatter with hot-reload support if logger has holder."""
    if logger is not None and hasattr(logger, "_holder") and logger._holder is not None:
        return LogFormatter(logger._holder)
    return LogFormatter(config)


class ConsoleHandlerConfig(HandlerConfig):
    """Configuration for console handlers."""

    def __init__(
        self,
        stream: Any | None = None,
        level: str | int | None = None,
        format: str = "text",
        colors: bool | None = None,
        **kwargs: Any,
    ):
        super().__init__(level)
        self.stream = stream if stream is not None else sys.stdout
        self.format = format
        self.colors = colors  # None means use LogConfig default

        # Extract format-specific options (those starting with "format_")
        self.format_options = {}
        format_keys = [key for key in kwargs.keys() if key.startswith("format_")]
        for key in format_keys:
            self.format_options[key[7:]] = kwargs[key]  # Remove "format_" prefix

    def to_dict(self) -> dict[str, Any]:
        """Serialize to picklable dictionary."""
        # Convert stream object to string identifier
        stream_name = "stderr" if self.stream is sys.stderr else "stdout"

        d: dict[str, Any] = {
            "type": "console",
            "stream": stream_name,
            "format": self.format,
        }
        if self.level is not None:
            d["level"] = self.level
        if self.colors is not None:
            d["colors"] = self.colors

        # Add format options with prefix
        for key, value in self.format_options.items():
            d[f"format_{key}"] = value

        return d

    def create_handler(self, config: LogConfig, logger: Any = None) -> logging.Handler:
        """Create a console handler."""
        from dataclasses import replace

        handler = logging.StreamHandler(self.stream)
        # Set handler level with proper resolution
        level = self.level or config.level
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        handler.setLevel(level)

        # Use appropriate formatter based on format parameter
        formatter: logging.Formatter
        if self.format.lower() == "json":
            # Create JSON formatter with custom configuration
            json_config = {
                "timestamp_format": self.format_options.get("timestamp_format", "iso"),
                "pretty_print": self.format_options.get("pretty_print", False),
                "custom_fields": self.format_options.get("custom_fields", {}),
                "exclude_fields": self.format_options.get("exclude_fields", []),
            }
            formatter = JSONFormatter(**json_config)
        else:
            # Apply handler-specific colors override if set
            effective_config = config
            if self.colors is not None:
                effective_config = replace(config, colors=self.colors)
            formatter = _create_text_formatter(effective_config, logger)

        handler.setFormatter(formatter)
        return handler


class ConsoleLoggingBuilder(LoggingBuilder):
    """
    Specialized builder for console-only logging.

    Provides convenient methods for configuring console output with
    various formatting options.
    """

    def __init__(self, name: str):
        """
        Initialize console logging builder.

        Args:
            name: Logger name
        """
        super().__init__(name)
        # Default to console handler
        self.with_console_handler()

    def with_colors(self, enabled: bool = True) -> Self:
        """
        Enable or disable colored console output.

        Args:
            enabled: Whether to enable colors

        Returns:
            Self for method chaining
        """
        return super().with_colors(enabled)

    def with_stream(self, stream: Any) -> Self:
        """
        Set the output stream for console logging.

        Args:
            stream: Output stream (e.g., sys.stdout, sys.stderr)

        Returns:
            Self for method chaining
        """
        # Remove existing console handler and add new one with stream
        self._handlers = [
            h for h in self._handlers if not isinstance(h, ConsoleHandlerConfig)
        ]
        self.with_console_handler(stream=stream)
        return self

    def stdout(self) -> Self:
        """
        Use stdout for console output.

        Returns:
            Self for method chaining
        """
        import sys

        return self.with_stream(sys.stdout)

    def stderr(self) -> Self:
        """
        Use stderr for console output.

        Returns:
            Self for method chaining
        """
        import sys

        return self.with_stream(sys.stderr)


# Convenience function for console builder
def create_console_logger(name: str) -> ConsoleLoggingBuilder:
    """
    Create a console logging builder.

    Args:
        name: Logger name

    Returns:
        ConsoleLoggingBuilder instance
    """
    return ConsoleLoggingBuilder(name)


# Quick setup function for console builder
# Note: Quick functions have been moved to quick.py
