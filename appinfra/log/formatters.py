"""
Log formatters for the logging system.

This module provides various formatter classes for handling different aspects
of log message formatting, including colors, fields, exceptions, and locations.
"""

import collections
import logging
import os
import re
import sys
import traceback
from typing import Any, cast

from .colors import ColorManager
from .config import LogConfig
from .config_holder import LogConfigHolder
from .constants import LogConstants
from .errors import FormatterError

# Type alias for config parameter that can be either LogConfig or LogConfigHolder
ConfigLike = LogConfig | LogConfigHolder

# Pattern to match ANSI escape sequences
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


def _visual_len(text: str) -> int:
    """Calculate visual width of text, excluding ANSI escape codes."""
    if "\x1b" not in text:
        return len(text)
    return len(_ANSI_PATTERN.sub("", text))


# Helper functions for FieldFormatter.format_field()


def _get_cache_key(
    value: Any, col: str, bold: str, name: str, quote: bool
) -> tuple[Any, str, str, str, bool] | None:
    """Generate cache key for simple, cacheable values."""
    if isinstance(value, (str, int, float, bool)) and not isinstance(value, dict):
        return (value, col, bold, name, quote)
    return None


def _format_header(col: str, name: str) -> str:
    """Format field header with color."""
    if name == "after":
        return ColorManager.RESET + col + "["
    return ColorManager.RESET + col + name + "["


def _format_value(formatter: Any, value: Any, col: str, bold: str, name: str) -> str:
    """Format value based on its type."""
    if isinstance(value, list):
        if all(isinstance(v, (str, int, float)) for v in value):
            return bold + ",".join(map(str, value))
        return bold + ",".join(str(v) for v in value)

    if isinstance(value, dict):
        return cast(str, formatter._format_fields_dict(value, col, bold))

    if name == "after" and isinstance(value, float):
        from .. import time as infratime

        return bold + infratime.delta.delta_str(value, precise=formatter._config.micros)

    return bold + str(value)


def _cache_result(
    formatter: Any, cache_key: tuple[Any, str, str, str, bool] | None, result: str
) -> None:
    """Cache result with LRU eviction when cache is full."""
    if cache_key is None:
        return

    cache = formatter._format_cache
    if cache_key in cache:
        # Move existing key to end (most recently used)
        cache.move_to_end(cache_key)
    else:
        # Evict oldest entry if cache is full
        if len(cache) >= formatter._max_cache_size:
            cache.popitem(last=False)  # Remove oldest (first) item
        cache[cache_key] = result


# Helper functions for LogFormatter._format_with_colors()


def _escape_percent(s: str) -> str:
    """Escape % as %% to prevent format string interpretation.

    Exception messages (e.g., SQLAlchemy errors) often contain %(param)s
    patterns that would cause KeyError during %-style formatting.
    """
    return s.replace("%", "%%")


def _format_extra_without_colors(record: logging.LogRecord) -> str:
    """Format extra fields without colors."""
    extra = getattr(record, "__infra__extra", None)
    if extra is None:
        return ""

    keys = extra.keys()
    if not isinstance(extra, collections.OrderedDict):
        keys = sorted(keys)

    # Keys that get special handling
    special_keys = {"after", "exception", "exception_formatted"}

    extra_parts = []
    for key in keys:
        if key in special_keys:
            continue
        value = extra[key]
        extra_parts.append(f"[{key}:{_escape_percent(str(value))}]")

    result = " " + " ".join(extra_parts) if extra_parts else ""

    # Append exception info (prefer pre-formatted from queue mode)
    if "exception_formatted" in extra:
        result += "\n" + _escape_percent(extra["exception_formatted"])
    elif "exception" in extra:
        exc = extra["exception"]
        if isinstance(exc, Exception):
            result += f"\n{_escape_percent(f'{exc.__class__.__name__}: {exc}')}"

    return result


def _format_without_colors(
    formatter: Any, record: logging.LogRecord, width: int
) -> str:
    """Format log record without colors."""
    fmt = LogConstants.DEFAULT_FORMAT
    rule = (
        LogConstants.MICRO_RULE_WIDTH
        if formatter._config.micros
        else LogConstants.DEFAULT_RULE_WIDTH
    )
    fmt += " " * (max(1, rule - width))

    # Handle extra fields
    fmt += _format_extra_without_colors(record)

    # Add process and logger name
    fmt += " [%(process)d] [%(name)s]"

    # Add location information
    fmt += cast(str, formatter._location_renderer.render_location(record))

    return fmt


def _setup_level_colors(record: logging.LogRecord) -> tuple[str, str]:
    """Setup colors for the log level."""
    col = ColorManager.get_color_for_level(record.levelno) or ColorManager.DEFAULT
    bold = ColorManager.create_bold_color(col)
    col += "m"
    return col, bold


def _format_extra_fields(
    formatter: Any, record: logging.LogRecord, col: str, bold: str
) -> tuple[str, bool]:
    """Format extra fields if present. Returns (formatted_string, had_content)."""
    extra = getattr(record, "__infra__extra", None)
    if extra is None:
        return "", False

    keys = extra.keys()
    if not isinstance(extra, collections.OrderedDict):
        keys = sorted(keys)

    add = formatter._field_formatter._format_fields_dict(extra, col, bold)
    return add, len(add) > 0


def _add_metadata_section(formatter: Any, fmt: str, content: bool) -> str:
    """Add process and logger name metadata with gray color."""
    col = ColorManager.create_gray_level(9) + "m"
    bold = ColorManager.create_gray_level(9) + ";1m"

    if content:
        fmt += " "

    fmt += formatter._field_formatter.format_field("%(process)d", col, bold)
    fmt += " " + formatter._field_formatter.format_field("%(name)s", col, bold)
    return fmt


def _format_colored(formatter: Any, record: logging.LogRecord, width: int) -> str:
    """Format log record with colors and styling."""
    col, bold = _setup_level_colors(record)

    # Format main fields
    fmt = formatter._field_formatter.format_field("%(asctime)s", col, "")
    fmt += " " + formatter._field_formatter.format_field("%(levelname).1s", col, bold)
    fmt += " " + bold + "%(message)s"

    # Add rule spacing
    rule = (
        LogConstants.MICRO_RULE_WIDTH
        if formatter._config.micros
        else LogConstants.DEFAULT_RULE_WIDTH
    )
    fmt += " " * (max(1, rule - width))

    # Handle extra fields
    add, content = _format_extra_fields(formatter, record, col, bold)
    fmt += add

    # Add process and logger metadata
    fmt = _add_metadata_section(formatter, fmt, content)

    # Add location information
    fmt += cast(str, formatter._location_renderer.render_location(record))

    fmt += ColorManager.RESET
    return col + fmt


class PreFormatter(logging.Formatter):
    """
    Custom formatter that adds microsecond precision to timestamps.

    Extends the standard logging formatter to optionally include
    microsecond precision in timestamp formatting.
    """

    def __init__(self, fmt: str, micros: bool) -> None:
        """
        Initialize the pre-formatter.

        Args:
            fmt: Log message format string
            micros: Whether to include microsecond precision
        """
        self._micros = micros
        super().__init__(fmt)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """
        Format timestamp with optional microsecond precision.

        Args:
            record: Log record object
            datefmt: Date format string (unused)

        Returns:
            Formatted timestamp string
        """
        s = super().formatTime(record)
        if self._micros:
            # Add millisecond precision to timestamp
            micros = int((record.created % 1) * 1000000) % 1000
            s += f".{micros:03d}"
        return s


class FieldFormatter:
    """Handles individual field formatting with colors and brackets."""

    def __init__(self, config: ConfigLike):
        """
        Initialize field formatter.

        Args:
            config: Formatter configuration (LogConfig or LogConfigHolder)
        """
        if isinstance(config, LogConfigHolder):
            self._holder = config
        else:
            self._holder = LogConfigHolder(config)
        # LRU cache: OrderedDict maintains insertion order for eviction
        # Most recently used items are moved to end, oldest are at front
        self._format_cache: collections.OrderedDict[Any, str] = (
            collections.OrderedDict()
        )
        self._max_cache_size = 1000  # LRU eviction threshold

    @property
    def _config(self) -> LogConfig:
        """Get current config (supports hot-reload via holder)."""
        return self._holder.config

    def format_field(
        self, value: Any, col: str, bold: str, name: str = "", quote: bool = False
    ) -> str:
        """
        Format a single field with color and brackets.

        Args:
            value: The value to format
            col: Color escape sequence
            bold: Bold color escape sequence
            name: Field name (empty for anonymous fields)
            quote: Whether to escape % characters for logging safety

        Returns:
            Formatted field string with colors and brackets
        """
        # Check cache for simple, frequently repeated values
        cache_key = _get_cache_key(value, col, bold, name, quote)
        if cache_key and cache_key in self._format_cache:
            # Move to end to mark as recently used (LRU)
            self._format_cache.move_to_end(cache_key)
            return self._format_cache[cache_key]

        # Format the field
        head = _format_header(col, name)
        mid = _format_value(self, value, col, bold, name)

        # Escape % characters to prevent logging format errors
        if quote:
            mid = mid.replace("%", "%%")

        tail = ColorManager.RESET + col + "]"
        result = head + mid + tail

        # Cache the result
        _cache_result(self, cache_key, result)

        return result

    def _format_fields_dict(self, fields: dict[str, Any], col: str, bold: str) -> str:
        """Format a dictionary of fields."""
        # Keys to exclude from normal field formatting
        special_keys = {"after", "exception", "exception_formatted"}

        seq = []
        if "after" in fields:
            seq.append(
                self.format_field(fields["after"], col, bold, "after", quote=True)
            )

        s = " ".join(
            seq
            + [
                self.format_field(v, col, bold, k, quote=True)
                for k, v in fields.items()
                if k not in special_keys
            ]
        )

        # Handle exception - prefer pre-formatted (from queue mode), fall back to live
        if "exception_formatted" in fields:
            # Pre-formatted exception from MPQueueHandler (cross-process)
            s += "\n" + _escape_percent(fields["exception_formatted"])
        elif "exception" in fields:
            # Live exception in same process
            s += "\n" + _escape_percent(self._render_exception(fields["exception"]))

        return s

    def _render_exception(self, e: Exception) -> str:
        """Render exception traceback."""
        if not isinstance(e, Exception):
            raise FormatterError(f"Not an exception: {type(e)}")

        exc_type, exc_value, exc_traceback = sys.exc_info()
        if exc_type is None:
            return str(e)
        out = f"{exc_type.__name__}: {exc_value}"

        for filename, lineno, function_name, text in traceback.extract_tb(
            exc_traceback
        ):
            out += f'\n  File "{filename}", line {lineno}, in {function_name}'
            if text:
                out += f"\n    {text.strip()}"

        return out


class LocationRenderer:
    """Handles file location display in log messages.

    Global display settings (location, location_color) are read from the
    holder's config to support hot-reload. The holder is shared with the
    root logger, so updates to the root's config are immediately visible.
    """

    def __init__(self, config: ConfigLike):
        """
        Initialize location renderer.

        Args:
            config: Formatter configuration (LogConfig or LogConfigHolder).
                    Should be the root logger's holder for hot-reload to work.
        """
        if isinstance(config, LogConfigHolder):
            self._holder = config
        else:
            self._holder = LogConfigHolder(config)

    @property
    def _location(self) -> int:
        """Get location depth from holder (supports hot-reload)."""
        return self._holder.location

    @property
    def _location_color(self) -> str:
        """Get location color from holder (supports hot-reload)."""
        color = self._holder.location_color
        return color if color is not None else ColorManager.create_gray_level(6)

    def render_location(self, record: logging.LogRecord) -> str:
        """
        Render file location information.

        Args:
            record: Log record object

        Returns:
            Formatted location string
        """
        if not self._location:
            return ""

        fmt = ""
        # Use configurable color - read fresh from config for hot-reload
        if self._holder.colors:
            fmt += ColorManager.RESET + self._location_color + "m"

        # Use __infra__pathnames if available (multi-location trace from appinfra logger)
        pathnames = getattr(record, "__infra__pathnames", None)
        linenos = getattr(record, "__infra__linenos", None)

        if pathnames is not None and linenos is not None:
            for i, pathname in enumerate(pathnames):
                name = self._render_pathname(pathname)
                lineno = linenos[i]
                fmt += f"[{name}:{lineno}]"
        else:
            # Fallback to standard attributes for non-appinfra loggers
            name = self._render_pathname(record.pathname)
            fmt += f"[{name}:{record.lineno}]"

        return fmt

    def _render_pathname(self, pathname: str) -> str:
        """Render a single pathname."""
        return "./" + os.path.relpath(pathname, os.getcwd())


class LogFormatter(logging.Formatter):
    """
    Advanced log formatter with colored output and structured field formatting.

    Provides rich console output with:
    - ANSI color codes for different log levels
    - Structured field formatting with brackets
    - Exception traceback rendering
    - File location display
    - Process and logger name information

    Supports hot-reload when initialized with a LogConfigHolder.
    """

    def __init__(self, config: ConfigLike):
        """
        Initialize the log formatter.

        Args:
            config: Logger configuration (LogConfig or LogConfigHolder).
                    Use LogConfigHolder to enable hot-reload support.
        """
        if isinstance(config, LogConfigHolder):
            self._holder = config
        else:
            self._holder = LogConfigHolder(config)

        # Share the holder with sub-formatters for synchronized hot-reload
        self._field_formatter = FieldFormatter(self._holder)
        self._location_renderer = LocationRenderer(self._holder)

        # Cache PreFormatter and track micros setting to detect config changes
        self._cached_micros = self._config.micros
        self._pre_formatter = PreFormatter(
            LogConstants.DEFAULT_FORMAT, self._cached_micros
        )

    @property
    def _config(self) -> LogConfig:
        """Get current config (supports hot-reload via holder)."""
        return self._holder.config

    def format(self, record: logging.LogRecord) -> str:
        """
        Format a log record.

        Args:
            record: Log record to format

        Returns:
            Formatted log message
        """
        width = self._calculate_width(record)
        fmt = self._format_with_colors(record, width)

        # Check if micros config changed (hot-reload support)
        current_micros = self._config.micros
        if current_micros != self._cached_micros:
            self._cached_micros = current_micros
            self._pre_formatter = PreFormatter(
                LogConstants.DEFAULT_FORMAT, current_micros
            )

        # Update the format string and use cached PreFormatter
        self._pre_formatter._fmt = fmt
        self._pre_formatter._style._fmt = fmt
        return self._pre_formatter.format(record)

    def _calculate_width(self, record: logging.LogRecord) -> int:
        """Calculate display width without full formatting.

        Format: "[%(asctime)s] [%(levelname).1s] %(message)s"
        Example: "[12:34:56,789] [I] Hello world"
        """
        # Timestamp: "HH:MM:SS,mmm" = 12 chars, or "HH:MM:SS,mmm.uuu" = 16 with micros
        timestamp_len = 16 if self._config.micros else 12
        # "[" + timestamp + "] [" + level(1) + "] " + message
        #  1  +    12/16   +  4  +     1     +  2  + msg_len
        return 1 + timestamp_len + 4 + 1 + 2 + _visual_len(record.getMessage())

    def _format_with_colors(self, record: logging.LogRecord, width: int) -> str:
        """Format record with colors and styling."""
        if not self._config.colors:
            return _format_without_colors(self, record, width)
        return _format_colored(self, record, width)
