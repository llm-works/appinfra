"""
Base logging builder for fluent configuration API.

This module provides the foundation for building loggers with a fluent, chainable API,
making it easy to configure complex logging setups with clean, readable code.
"""

import collections
from pathlib import Path
from typing import Any, Self

from ..config import LogConfig
from ..errors import LogConfigError
from ..factory import LoggerFactory
from ..logger import Logger
from .interface import HandlerConfig, LoggingBuilderInterface


def _get_handler_classes() -> dict[str, type[HandlerConfig]]:
    """Return mapping of handler type names to config classes."""
    from .console import ConsoleHandlerConfig
    from .file import (
        FileHandlerConfig,
        RotatingFileHandlerConfig,
        TimedRotatingFileHandlerConfig,
    )

    return {
        "console": ConsoleHandlerConfig,
        "file": FileHandlerConfig,
        "rotating_file": RotatingFileHandlerConfig,
        "timed_rotating_file": TimedRotatingFileHandlerConfig,
    }


def _deserialize_handler(handler_dict: dict[str, Any]) -> HandlerConfig | None:
    """Deserialize a handler config dict to a HandlerConfig instance."""
    import sys

    handler_classes = _get_handler_classes()
    handler_type = handler_dict.get("type")
    if handler_type not in handler_classes:
        return None

    handler_class = handler_classes[handler_type]
    kwargs = {k: v for k, v in handler_dict.items() if k != "type"}

    if handler_type == "console":
        stream_name = kwargs.pop("stream", "stdout")
        kwargs["stream"] = sys.stderr if stream_name == "stderr" else sys.stdout
        return handler_class(**kwargs)

    if handler_type in ("file", "rotating_file", "timed_rotating_file"):
        return handler_class(kwargs.pop("filename"), **kwargs)

    return None


class LoggingBuilder(LoggingBuilderInterface):
    """
    Base fluent builder for configuring loggers.

    Provides a clean, chainable API for setting up loggers with various
    configurations, handlers, and formatters.
    """

    def __init__(self, name: str):
        """
        Initialize the logging builder.

        Args:
            name: Logger name
        """
        self._name = name
        self._level: str | int = "info"
        self._location = 0
        self._micros = False
        self._colors = True
        self._location_color: str | None = None

        # Handler configurations
        self._handlers: list[HandlerConfig] = []

        # Logger class
        self._logger_class: type[Logger] = Logger

        # Extra fields to pre-populate in log records
        self._extra: dict[str, Any] | collections.OrderedDict = {}

    def with_level(self, level: str | int) -> Self:
        """
        Set the log level.

        Args:
            level: Log level (string name or numeric value)

        Returns:
            Self for method chaining
        """
        self._level = level
        return self

    def with_location(self, location: bool | int) -> Self:
        """
        Set the location display level.

        Args:
            location: Location display level (bool or int)

        Returns:
            Self for method chaining
        """
        self._location = location
        return self

    def with_micros(self, micros: bool = True) -> Self:
        """
        Enable or disable microsecond precision.

        Args:
            micros: Whether to show microsecond precision

        Returns:
            Self for method chaining
        """
        self._micros = micros
        return self

    def with_colors(self, enabled: bool = True) -> Self:
        """
        Enable or disable colored console output.

        Args:
            enabled: Whether to enable colors

        Returns:
            Self for method chaining
        """
        self._colors = enabled
        return self

    def with_location_color(self, color: str) -> Self:
        """
        Set the color for code location display.

        Args:
            color: ANSI color code (e.g., ColorManager.CYAN, ColorManager.BLACK)
                   Or use ColorManager.create_gray_level(n) for grayscale

        Returns:
            Self for method chaining

        Example:
            from ..colors import ColorManager

            logger = (LoggingBuilder("app")
                .with_location(1)
                .with_location_color(ColorManager.CYAN)
                .build())
        """
        self._location_color = color
        return self

    def with_config(self, config: dict[str, Any]) -> Self:
        """
        Set multiple configuration parameters at once.

        Args:
            config: Configuration dictionary with keys:
                - level: Log level (string name, numeric value, or False to disable logging)
                - location: Location display level (bool or int)
                - micros: Whether to show microsecond precision
                - colors: Whether to enable colored output
                - location_color: ANSI color code for code locations

        Returns:
            Self for method chaining
        """
        if "level" in config:
            self._level = config["level"]
        if "location" in config:
            self._location = config["location"]
        if "micros" in config:
            self._micros = config["micros"]
        if "colors" in config:
            self._colors = config["colors"]
        if "location_color" in config:
            self._location_color = config["location_color"]
        return self

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
        self._extra.update(kwargs)
        return self

    def with_handler(self, handler_config: HandlerConfig) -> Self:
        """
        Add a handler configuration.

        Args:
            handler_config: Handler configuration object

        Returns:
            Self for method chaining
        """
        self._handlers.append(handler_config)
        return self

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
        from .console import ConsoleHandlerConfig

        handler_config = ConsoleHandlerConfig(stream=stream, level=level)
        return self.with_handler(handler_config)

    def with_file_handler(  # type: ignore[override]
        self,
        filename: str | Path,
        level: str | int | None = None,
        **kwargs: Any,
    ) -> Self:
        """
        Add a file handler.

        Args:
            filename: Path to log file
            level: Handler level (defaults to logger level)
            **kwargs: Additional file handler arguments

        Returns:
            Self for method chaining
        """
        from .file import FileHandlerConfig

        handler_config = FileHandlerConfig(
            filename=filename,
            level=level,
            mode=kwargs.get("mode", "a"),
            encoding=kwargs.get("encoding"),
            delay=kwargs.get("delay", False),
        )
        return self.with_handler(handler_config)

    def with_rotating_file_handler(  # type: ignore[override]
        self,
        filename: str | Path,
        max_bytes: int = 0,
        backup_count: int = 0,
        level: str | int | None = None,
        **kwargs: Any,
    ) -> Self:
        """
        Add a rotating file handler.

        Args:
            filename: Path to log file
            max_bytes: Maximum file size before rotation
            backup_count: Number of backup files to keep
            level: Handler level (defaults to logger level)
            **kwargs: Additional handler arguments

        Returns:
            Self for method chaining
        """
        from .file import RotatingFileHandlerConfig

        handler_config = RotatingFileHandlerConfig(
            filename=filename,
            max_bytes=max_bytes,
            backup_count=backup_count,
            level=level,
            encoding=kwargs.get("encoding"),
            delay=kwargs.get("delay", False),
        )
        return self.with_handler(handler_config)

    def with_timed_rotating_file_handler(  # type: ignore[override]
        self,
        filename: str | Path,
        when: str = "h",
        interval: int = 1,
        backup_count: int = 0,
        level: str | int | None = None,
        **kwargs: Any,
    ) -> Self:
        """
        Add a timed rotating file handler.

        Args:
            filename: Path to log file
            when: Rotation interval ('S', 'M', 'H', 'D', 'W0'-'W6', 'midnight')
            interval: Number of intervals between rotations
            backup_count: Number of backup files to keep
            level: Handler level (defaults to logger level)
            **kwargs: Additional handler arguments

        Returns:
            Self for method chaining
        """
        from .file import TimedRotatingFileHandlerConfig

        handler_config = TimedRotatingFileHandlerConfig(
            filename=filename,
            when=when,
            interval=interval,
            backup_count=backup_count,
            level=level,
            encoding=kwargs.get("encoding"),
            delay=kwargs.get("delay", False),
            utc=kwargs.get("utc", False),
        )
        return self.with_handler(handler_config)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize builder configuration to a picklable dictionary.

        Used for passing logging configuration to subprocesses.
        Database handlers are excluded (they cannot be serialized).

        Returns:
            Dictionary with all configuration parameters

        Example:
            # Parent process
            builder = LoggingBuilder("app").with_level("debug").with_console_handler()
            config = builder.to_dict()

            # Subprocess
            builder = LoggingBuilder.from_dict(config)
            logger = builder.build()
        """
        # Serialize handler configs, skipping non-serializable ones
        handlers = []
        for handler_config in self._handlers:
            try:
                handlers.append(handler_config.to_dict())
            except NotImplementedError:
                # Skip handlers that can't be serialized (e.g., DatabaseHandler)
                pass

        return {
            "name": self._name,
            "level": self._level,
            "location": self._location,
            "micros": self._micros,
            "colors": self._colors,
            "location_color": self._location_color,
            "handlers": handlers,
            "extra": dict(self._extra) if self._extra else {},
        }

    @classmethod
    def from_dict(cls, config: dict[str, Any], name: str | None = None) -> Self:
        """
        Create a builder from a serialized configuration dictionary.

        Used for reconstructing logging configuration in subprocesses.

        Args:
            config: Configuration dictionary (from to_dict())
            name: Override logger name (optional, uses config name if not provided)

        Returns:
            LoggingBuilder instance with restored configuration

        Example:
            # Subprocess
            builder = LoggingBuilder.from_dict(config, name="worker-1")
            logger = builder.build()
        """
        builder = cls(name or config["name"])
        builder._level = config.get("level", "info")
        builder._location = config.get("location", 0)
        builder._micros = config.get("micros", False)
        builder._colors = config.get("colors", True)
        builder._location_color = config.get("location_color")
        builder._extra = config.get("extra", {})

        # Reconstruct handlers from serialized config
        for handler_dict in config.get("handlers", []):
            handler = _deserialize_handler(handler_dict)
            if handler is not None:
                builder.with_handler(handler)

        return builder

    def build(self) -> Logger:
        """
        Build and return the configured logger.

        Returns:
            Configured logger instance

        Raises:
            LogConfigError: If configuration is invalid
        """
        # Create base configuration
        config = LogConfig.from_params(
            level=self._level,
            location=self._location,
            micros=self._micros,
            colors=self._colors,
            location_color=self._location_color,
        )

        # Create logger
        logger = LoggerFactory.create(
            self._name, config, self._logger_class, self._extra
        )

        # Clear default handlers since we're configuring our own
        logger.handlers.clear()

        # Add configured handlers
        self._add_handlers(logger, config)

        return logger

    def _add_handlers(self, logger: Logger, config: LogConfig) -> None:
        """
        Add configured handlers to the logger.

        Args:
            logger: Logger instance
            config: Logger configuration
        """
        for handler_config in self._handlers:
            try:
                handler = handler_config.create_handler(config, logger=logger)
                logger.addHandler(handler)
            except Exception as e:
                raise LogConfigError(f"Failed to create handler: {e}")


def create_logger(name: str) -> LoggingBuilder:
    """
    Create a logging builder for the specified logger name.

    Args:
        name: Logger name

    Returns:
        LoggingBuilder instance
    """
    return LoggingBuilder(name)


# Convenience functions for common configurations
# Note: Quick functions have been moved to quick.py
