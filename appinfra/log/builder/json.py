"""
JSON logging builder for structured JSON output.

This module provides a specialized builder for configuring JSON logging,
extending the base LoggingBuilder with JSON-specific functionality.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Self

from ..config import LogConfig
from ..factory import LoggerFactory
from ..logger import Logger
from .builder import LoggingBuilder

# Helper functions for JSONFormatter._record_to_dict()


def _add_timestamp(
    data: dict[str, Any], formatter: Any, record: logging.LogRecord
) -> None:
    """Add timestamp field if configured."""
    if formatter.should_include_field("timestamp"):
        data["timestamp"] = formatter._format_timestamp(record)


def _add_basic_fields(
    data: dict[str, Any], formatter: Any, record: logging.LogRecord
) -> None:
    """Add basic log fields (level, logger, message)."""
    if formatter.should_include_field("level"):
        data["level"] = record.levelname
    if formatter.should_include_field("logger"):
        data["logger"] = record.name
    if formatter.should_include_field("message"):
        data["message"] = record.getMessage()


def _add_module_fields(
    data: dict[str, Any], formatter: Any, record: logging.LogRecord
) -> None:
    """Add module information fields."""
    if formatter.should_include_field("module") and record.module:
        data["module"] = record.module
    if formatter.should_include_field("function") and record.funcName:
        data["function"] = record.funcName
    if formatter.should_include_field("line") and record.lineno:
        data["line"] = record.lineno


def _add_process_fields(
    data: dict[str, Any], formatter: Any, record: logging.LogRecord
) -> None:
    """Add process and thread information."""
    if formatter.include_process_info and formatter.should_include_field("process_id"):
        data["process_id"] = record.process
    if formatter.include_process_info and formatter.should_include_field("thread_id"):
        data["thread_id"] = record.thread


def _add_extra_fields(
    data: dict[str, Any], formatter: Any, record: logging.LogRecord
) -> None:
    """Add extra fields if present."""
    extra = getattr(record, "__infra__extra", None)
    if formatter.include_extra and formatter.should_include_field("extra") and extra:
        data["extra"] = formatter._sanitize_extra_fields(extra)


def _add_location_fields(
    data: dict[str, Any], formatter: Any, record: logging.LogRecord
) -> None:
    """Add location information."""
    if formatter.include_location and formatter.should_include_field("location"):
        location = formatter._extract_location(record)
        if location:
            data["location"] = location


def _add_exception_fields(
    data: dict[str, Any], formatter: Any, record: logging.LogRecord
) -> None:
    """Add exception information if present."""
    if (
        formatter.include_exception
        and formatter.should_include_field("exception")
        and record.exc_info
    ):
        data["exception"] = formatter._format_exception(record.exc_info)


def _add_custom_fields(data: dict[str, Any], formatter: Any) -> None:
    """Add custom fields defined in formatter configuration."""
    for key, value in formatter.custom_fields.items():
        if formatter.should_include_field(key):
            data[key] = value


class JSONFormatter(logging.Formatter):
    """
    Formatter that converts log records to JSON format.

    Provides structured JSON output suitable for log aggregation systems
    while maintaining compatibility with the existing logging infrastructure.
    """

    def __init__(
        self,
        include_extra: bool = True,
        include_location: bool = True,
        include_process_info: bool = True,
        include_exception: bool = True,
        include_fields: list[str] | None = None,
        exclude_fields: list[str] | None = None,
        pretty_print: bool = False,
        timestamp_format: str = "iso",
        custom_fields: dict[str, Any] | None = None,
    ):
        """
        Initialize JSON formatter.

        Args:
            include_extra: Whether to include extra fields from record._extra
            include_location: Whether to include file location information
            include_process_info: Whether to include process/thread IDs
            include_exception: Whether to include exception tracebacks
            include_fields: Specific fields to include (None = all)
            exclude_fields: Specific fields to exclude
            pretty_print: Whether to format JSON with indentation
            timestamp_format: Format for timestamps ("iso", "unix", "epoch")
            custom_fields: Additional custom fields to include
        """
        super().__init__()
        self.include_extra = include_extra
        self.include_location = include_location
        self.include_process_info = include_process_info
        self.include_exception = include_exception
        self.include_fields = set(include_fields) if include_fields else None
        self.exclude_fields = set(exclude_fields) if exclude_fields else None
        self.pretty_print = pretty_print
        self.timestamp_format = timestamp_format
        self.custom_fields = custom_fields or {}

        # Standard fields that are always included unless explicitly excluded
        self._standard_fields = {
            "timestamp",
            "level",
            "logger",
            "message",
            "module",
            "function",
            "line",
            "process_id",
            "thread_id",
            "extra",
            "exception",
            "location",
        }

    def should_include_field(self, field_name: str) -> bool:
        """Check if a field should be included in JSON output."""
        # If exclude_fields is specified and field is in it, exclude
        if self.exclude_fields and field_name in self.exclude_fields:
            return False

        # If include_fields is specified, only include fields in the list
        if self.include_fields and field_name not in self.include_fields:
            return False

        return True

    def format(self, record: logging.LogRecord) -> str:
        """
        Format a log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON string representation of the log record
        """
        try:
            json_data = self._record_to_dict(record)
            return self._dict_to_json(json_data)
        except Exception as e:
            # Fallback to basic JSON if formatting fails
            fallback_data = {
                "timestamp": self._format_timestamp(record),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "error": f"JSON formatting failed: {str(e)}",
            }
            return self._dict_to_json(fallback_data)

    def _record_to_dict(self, record: logging.LogRecord) -> dict[str, Any]:
        """Convert LogRecord to dictionary."""
        data: dict[str, Any] = {}

        _add_timestamp(data, self, record)
        _add_basic_fields(data, self, record)
        _add_module_fields(data, self, record)
        _add_process_fields(data, self, record)
        _add_extra_fields(data, self, record)
        _add_location_fields(data, self, record)
        _add_exception_fields(data, self, record)
        _add_custom_fields(data, self)

        return data

    def _format_timestamp(self, record: logging.LogRecord) -> str:
        """Format timestamp according to configuration."""
        from datetime import datetime

        if self.timestamp_format == "iso":
            return datetime.fromtimestamp(record.created).isoformat()
        elif self.timestamp_format == "unix":
            return str(record.created)
        elif self.timestamp_format == "epoch":
            return str(int(record.created))
        else:
            # Default to ISO format
            return datetime.fromtimestamp(record.created).isoformat()

    def _sanitize_extra_fields(self, extra: dict[str, Any]) -> dict[str, Any]:
        """Sanitize extra fields to ensure JSON serializability.

        Walks the value with ``coerce_tree`` first so opaque types with a
        preferred ``__str__`` form (or an opt-in ``__masked_str__``) reach the
        encoder as their string form rather than being destructured.
        """
        from ..serialize import coerce_tree

        sanitized = {}
        for key, value in extra.items():
            value = coerce_tree(value)
            try:
                json.dumps(value)
                sanitized[key] = value
            except (TypeError, ValueError):
                sanitized[key] = str(value)
        return sanitized

    def _extract_location(self, record: logging.LogRecord) -> list[str] | None:
        """Extract location information from the record."""
        locations = []

        # Use __infra__pathnames if available (multi-location trace from appinfra logger)
        pathnames = getattr(record, "__infra__pathnames", None)
        linenos = getattr(record, "__infra__linenos", None)

        if pathnames is not None and linenos is not None:
            for i, pathname in enumerate(pathnames):
                lineno = linenos[i]
                locations.append(f"{pathname}:{lineno}")
        elif hasattr(record, "pathname") and record.pathname:
            # Fallback to standard attributes for non-appinfra loggers
            locations.append(f"{record.pathname}:{record.lineno}")

        return locations if locations else None

    def _format_exception(self, exc_info: Any) -> str | None:
        """Format exception traceback as string."""
        if not exc_info:
            return None

        try:
            import traceback

            return "".join(traceback.format_exception(*exc_info))
        except Exception:
            return f"Exception formatting failed: {exc_info[1]}"

    def _dict_to_json(self, data: dict[str, Any]) -> str:
        """Convert dictionary to JSON string."""
        if self.pretty_print:
            return json.dumps(data, indent=2, ensure_ascii=False)
        else:
            return json.dumps(data, ensure_ascii=False)


class JSONLoggingBuilder(LoggingBuilder):
    """
    Specialized builder for JSON logging configuration.

    Provides a clean, chainable API for setting up loggers with JSON output,
    file handlers, and various configuration options.
    """

    def __init__(self, name: str):
        """
        Initialize JSON logging builder.

        Args:
            name: Logger name
        """
        super().__init__(name)

        # JSON configuration
        self._json_config: dict[str, Any] = {
            "include_extra": True,
            "include_location": True,
            "include_process_info": True,
            "include_exception": True,
            "include_fields": None,
            "exclude_fields": None,
            "pretty_print": False,
            "timestamp_format": "iso",
            "custom_fields": {},
        }

        # Output configuration
        self._console_output = True
        self._json_console = False
        self._json_file: str | Path | None = None
        self._file_kwargs: dict[str, Any] = {}

    def with_json_console(self, enabled: bool = True) -> Self:
        """
        Enable JSON output to console.

        Args:
            enabled: Whether to enable JSON console output

        Returns:
            Self for method chaining
        """
        self._json_console = enabled
        return self

    def with_json_file(self, file_path: str | Path, **kwargs: Any) -> Self:
        """
        Enable JSON output to file.

        Args:
            file_path: Path to JSON log file
            **kwargs: Additional file handler arguments

        Returns:
            Self for method chaining
        """
        self._json_file = file_path
        self._file_kwargs = kwargs
        return self

    def with_json_fields(
        self, include: list[str] | None = None, exclude: list[str] | None = None
    ) -> Self:
        """
        Configure JSON field inclusion/exclusion.

        Args:
            include: Fields to include (None = all)
            exclude: Fields to exclude

        Returns:
            Self for method chaining
        """
        self._json_config["include_fields"] = include
        self._json_config["exclude_fields"] = exclude
        return self

    def with_pretty_print(self, enabled: bool = True) -> Self:
        """
        Enable pretty printing for JSON output.

        Args:
            enabled: Whether to enable pretty printing

        Returns:
            Self for method chaining
        """
        self._json_config["pretty_print"] = enabled
        return self

    def with_timestamp_format(self, format_type: str) -> Self:
        """
        Set timestamp format for JSON output.

        Args:
            format_type: Timestamp format ("iso", "unix", "epoch")

        Returns:
            Self for method chaining
        """
        self._json_config["timestamp_format"] = format_type
        return self

    def with_custom_fields(self, fields: dict[str, Any]) -> Self:
        """
        Add custom fields to JSON output.

        Args:
            fields: Custom fields to include

        Returns:
            Self for method chaining
        """
        custom_fields = self._json_config["custom_fields"]
        if isinstance(custom_fields, dict):
            custom_fields.update(fields)
        return self

    def console_only(self) -> Self:
        """
        Configure for console output only (no JSON).

        Returns:
            Self for method chaining
        """
        self._console_output = True
        self._json_console = False
        self._json_file = None
        return self

    def json_only(self) -> Self:
        """
        Configure for JSON output only (no console).

        Returns:
            Self for method chaining
        """
        self._console_output = False
        self._json_console = False
        return self

    def both_outputs(self) -> Self:
        """
        Configure for both console and JSON output.

        Returns:
            Self for method chaining
        """
        self._console_output = True
        self._json_console = True
        return self

    def build(self) -> Logger:
        """
        Build and return the configured logger.

        Returns:
            Configured logger instance
        """
        # Create base configuration
        config = LogConfig.from_params(
            level=self._level,
            location=self._location,
            micros=self._micros,
            colors=self._colors,
        )

        # Create logger
        logger = LoggerFactory.create(
            self._name, config, self._logger_class, self._extra
        )

        # Clear default handlers since we're configuring our own
        logger.handlers.clear()

        # Add configured handlers
        self._add_json_handlers(logger, config)

        return logger

    def _add_regular_console_handler(self, logger: Logger, config: LogConfig) -> None:
        """Add regular (non-JSON) console handler."""
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(config.level)

        from ..formatters import LogFormatter

        formatter = LogFormatter(config)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    def _add_json_console_handler(
        self, logger: Logger, config: LogConfig, json_formatter: JSONFormatter
    ) -> None:
        """Add JSON console handler."""
        json_console_handler = logging.StreamHandler(sys.stdout)
        json_console_handler.setLevel(config.level)
        json_console_handler.setFormatter(json_formatter)
        logger.addHandler(json_console_handler)

    def _add_json_file_handler(
        self, logger: Logger, config: LogConfig, json_formatter: JSONFormatter
    ) -> None:
        """Add JSON file handler with directory creation."""
        assert self._json_file is not None  # Only called when _json_file is set

        # Ensure directory exists
        path = Path(self._json_file)
        if path.parent != path:  # Not just a filename
            path.parent.mkdir(parents=True, exist_ok=True)

        json_file_handler = logging.FileHandler(self._json_file, **self._file_kwargs)
        json_file_handler.setLevel(config.level)
        json_file_handler.setFormatter(json_formatter)
        logger.addHandler(json_file_handler)

    def _add_json_handlers(self, logger: Logger, config: LogConfig) -> None:
        """
        Add configured JSON handlers to the logger.

        Args:
            logger: Logger instance
            config: Logger configuration
        """
        json_formatter = JSONFormatter(**self._json_config)

        if self._console_output and not self._json_console:
            self._add_regular_console_handler(logger, config)

        if self._json_console:
            self._add_json_console_handler(logger, config, json_formatter)

        if self._json_file:
            self._add_json_file_handler(logger, config, json_formatter)


def create_json_logger(name: str) -> JSONLoggingBuilder:
    """
    Create a JSON logging builder for the specified logger name.

    Args:
        name: Logger name

    Returns:
        JSONLoggingBuilder instance
    """
    return JSONLoggingBuilder(name)


# Convenience functions for common JSON configurations
# Note: Quick functions have been moved to quick.py
