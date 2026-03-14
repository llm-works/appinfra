"""
Handler Factory for creating logging handlers from configuration.

This module provides a factory system that maps handler type strings
to their corresponding handler configuration classes.
"""

import logging
import sys
from typing import Any, cast

from .builder.console import ConsoleHandlerConfig
from .builder.database import DatabaseHandlerConfig
from .builder.file import (
    FileHandlerConfig,
    RotatingFileHandlerConfig,
    TimedRotatingFileHandlerConfig,
)

# Import for type checking in _create_handler_with_required_params
from .builder.file import FileHandlerConfig as FileHandlerConfigClass
from .builder.file import RotatingFileHandlerConfig as RotatingFileHandlerConfigClass
from .builder.file import (
    TimedRotatingFileHandlerConfig as TimedRotatingFileHandlerConfigClass,
)
from .builder.interface import HandlerConfig
from .errors import LogConfigError

# Helper functions for HandlerRegistry.add_handler_from_config()


def _validate_handler_type(handler_config: dict[str, Any]) -> None:
    """Validate handler configuration has required 'type' field."""
    if "type" not in handler_config:
        raise LogConfigError("Handler configuration must include 'type' field")


def _is_handler_enabled(handler_config: dict[str, Any]) -> bool:
    """Check if handler is enabled."""
    return cast(bool, handler_config.get("enabled", True))


def _filter_metadata_fields(handler_config: dict[str, Any]) -> dict[str, Any]:
    """Remove metadata fields that are not constructor parameters."""
    metadata_fields = {"type", "enabled"}
    return {k: v for k, v in handler_config.items() if k not in metadata_fields}


def _resolve_log_level(
    filtered_config: dict[str, Any], global_level: int | None
) -> None:
    """
    Resolve and adjust handler log level.

    Modifies filtered_config in place to set numeric level.
    """
    if "level" not in filtered_config or filtered_config["level"] is None:
        return

    level = filtered_config["level"]
    if isinstance(level, str):
        handler_level = getattr(logging, level.upper(), logging.INFO)
    elif isinstance(level, bool):
        handler_level = logging.INFO if level else 1000
    else:
        handler_level = level

    # Use global level if more restrictive
    if global_level is not None and global_level > handler_level:
        filtered_config["level"] = global_level
    else:
        filtered_config["level"] = handler_level


def _preserve_special_fields(
    handler_type: str, handler_config: dict[str, Any], filtered_config: dict[str, Any]
) -> None:
    """Preserve special positional argument fields for specific handler types."""
    if handler_type == "file" and "file" in handler_config:
        filtered_config["file"] = handler_config["file"]

    if handler_type == "database" and "table" in handler_config:
        filtered_config["table"] = handler_config["table"]


def _convert_console_stream(filtered_config: dict[str, Any]) -> None:
    """Convert stream strings to actual stream objects for console handlers."""
    if "stream" not in filtered_config:
        return

    stream = filtered_config["stream"]
    if isinstance(stream, str):
        if stream.lower() == "stderr":
            filtered_config["stream"] = sys.stderr
        elif stream.lower() == "stdout":
            filtered_config["stream"] = sys.stdout


def _extract_json_format_options(filtered_config: dict[str, Any]) -> None:
    """Extract and reformat JSON-specific options for console handlers."""
    format_param = filtered_config.get("format", "text")
    if format_param.lower() != "json":
        filtered_config["format"] = format_param
        return

    # Extract JSON-specific configuration options
    json_keys = ["timestamp_format", "pretty_print", "custom_fields", "exclude_fields"]
    format_options = {}
    for key in json_keys:
        if key in filtered_config:
            format_options[key] = filtered_config.pop(key)

    filtered_config["format"] = format_param
    # Store format options with format_ prefix
    for key, value in format_options.items():
        filtered_config[f"format_{key}"] = value


def _set_handler_name(
    handler_instance: HandlerConfig, handler_config: dict[str, Any]
) -> None:
    """Set handler name if provided in configuration."""
    if "_handler_name" in handler_config:
        handler_instance._handler_name = handler_config["_handler_name"]  # type: ignore[attr-defined]


# Helper functions for HandlerFactory._create_handler_with_required_params()


def _create_file_handler(
    handler_class: type[HandlerConfig], config: dict[str, Any]
) -> HandlerConfig:
    """Create file handler with required filename parameter."""
    filename = config.get("file") or config.get("filename")
    if not filename:
        raise LogConfigError("File handler requires 'file' or 'filename' parameter")

    return handler_class(
        filename,
        **{k: v for k, v in config.items() if k not in {"file", "filename"}},
    )


def _create_rotating_file_handler(
    handler_class: type[HandlerConfig], config: dict[str, Any]
) -> HandlerConfig:
    """Create rotating file handler with required filename parameter."""
    filename = config.get("file") or config.get("filename")
    if not filename:
        raise LogConfigError(
            f"{handler_class.__name__} requires 'file' or 'filename' parameter"
        )

    return handler_class(
        filename,
        **{k: v for k, v in config.items() if k not in {"file", "filename"}},
    )


def _create_database_handler(
    handler_class: type[HandlerConfig], config: dict[str, Any]
) -> HandlerConfig:
    """Create database handler with required table_name and db_interface parameters."""
    table_name = config.get("table")
    db_interface = config.get("db")

    if not table_name:
        raise LogConfigError("Database handler requires 'table' parameter")
    if not db_interface:
        raise LogConfigError("Database handler requires 'db' parameter")

    return handler_class(  # type: ignore[call-arg]
        table_name,
        db_interface,
        **{k: v for k, v in config.items() if k not in {"table", "db"}},
    )


class HandlerFactory:
    """
    Factory for creating handler configurations from type strings.

    Maps handler type names to their corresponding configuration classes
    and handles the instantiation with proper parameters.
    """

    # Registry mapping type strings to handler configuration classes
    _TYPE_REGISTRY: dict[str, type[HandlerConfig]] = {
        "console": ConsoleHandlerConfig,
        "file": FileHandlerConfig,
        "rotating_file": RotatingFileHandlerConfig,
        "timed_rotating_file": TimedRotatingFileHandlerConfig,
        "database": DatabaseHandlerConfig,
    }

    @classmethod
    def get_handler_class(cls, handler_type: str) -> type[HandlerConfig]:
        """
        Get the handler configuration class for a given type.

        Args:
            handler_type: The type string from the configuration

        Returns:
            The handler configuration class

        Raises:
            LogConfigError: If the handler type is not supported
        """
        if handler_type not in cls._TYPE_REGISTRY:
            available_types = ", ".join(cls._TYPE_REGISTRY.keys())
            raise LogConfigError(
                f"Unknown handler type: '{handler_type}'. "
                f"Supported types: {available_types}"
            )

        return cls._TYPE_REGISTRY[handler_type]

    @classmethod
    def create_handler_config(
        cls,
        handler_type: str,
        handler_config: dict[str, Any],
        global_level: int | None = None,
    ) -> HandlerConfig:
        """
        Create a handler configuration instance from type and config dict.

        Args:
            handler_type: The type string from the configuration
            handler_config: The handler configuration dictionary
            global_level: The global logger level to consider when adjusting handler levels

        Returns:
            A handler configuration instance

        Raises:
            LogConfigError: If the handler type is not supported or config is invalid
        """
        handler_class = cls.get_handler_class(handler_type)

        try:
            # Filter config to only include valid parameters for this handler type
            filtered_config = cls._filter_valid_params(handler_class, handler_config)

            # Create the handler configuration with proper parameter handling
            return cls._create_handler_with_required_params(
                handler_class, filtered_config
            )

        except Exception as e:
            raise LogConfigError(
                f"Failed to create handler configuration for type '{handler_type}': {e}"
            )

    @classmethod
    def _filter_valid_params(
        cls, handler_class: type[HandlerConfig], config: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Filter configuration to only include valid constructor parameters for the handler type.

        Args:
            handler_class: The handler configuration class
            config: The raw configuration dictionary

        Returns:
            Dictionary with only valid constructor parameters
        """
        import inspect

        # Get the constructor parameters
        sig = inspect.signature(handler_class.__init__)
        valid_params = set(sig.parameters.keys()) - {"self"}  # Exclude 'self'

        # Special handling for file handlers - they accept 'file' as a parameter
        # even though their constructor signature shows 'filename'
        if handler_class == FileHandlerConfigClass and "file" in config:
            valid_params.add("file")

        # Filter config to only include valid parameters
        return {k: v for k, v in config.items() if k in valid_params}

    @classmethod
    def _get_valid_constructor_params(
        cls, handler_class: type[HandlerConfig], config: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Filter configuration to only include valid constructor parameters.

        Args:
            handler_class: The handler configuration class
            config: The raw configuration dictionary

        Returns:
            Dictionary with only valid constructor parameters
        """
        import inspect

        # Get the constructor parameters
        sig = inspect.signature(handler_class.__init__)
        valid_params = set(sig.parameters.keys()) - {"self"}  # Exclude 'self'

        # Filter config to only include valid parameters
        return {k: v for k, v in config.items() if k in valid_params}

    @classmethod
    def _create_handler_with_required_params(
        cls, handler_class: type[HandlerConfig], config: dict[str, Any]
    ) -> HandlerConfig:
        """
        Create handler with special handling for required positional parameters.

        Args:
            handler_class: The handler configuration class
            config: The raw configuration dictionary

        Returns:
            Handler configuration instance
        """
        if handler_class == FileHandlerConfigClass:
            return _create_file_handler(handler_class, config)
        elif handler_class in [
            RotatingFileHandlerConfigClass,
            TimedRotatingFileHandlerConfigClass,
        ]:
            return _create_rotating_file_handler(handler_class, config)
        elif handler_class == DatabaseHandlerConfig:
            return _create_database_handler(handler_class, config)
        else:
            return handler_class(**config)

    @classmethod
    def get_supported_types(cls) -> list:
        """
        Get a list of all supported handler types.

        Returns:
            List of supported handler type strings
        """
        return list(cls._TYPE_REGISTRY.keys())

    @classmethod
    def iter_supported_types(cls) -> Any:
        """
        Generator that yields all supported handler types.

        Yields:
            str: Each supported handler type string
        """
        yield from cls._TYPE_REGISTRY.keys()


class HandlerRegistry:
    """
    Registry for managing multiple handlers and their configurations.

    Handles the creation and management of multiple handlers from a
    list-based configuration structure.
    """

    def __init__(self, global_level: int | None = None):
        """Initialize the handler registry."""
        self.handlers: list[HandlerConfig] = []
        self.global_level = global_level

    def add_handler_from_config(
        self, handler_config: dict[str, Any], global_level: int | None = None
    ) -> None:
        """
        Add a handler from configuration dictionary.

        Args:
            handler_config: Handler configuration from YAML (must include 'type')
            global_level: The global logger level to consider when adjusting handler levels

        Raises:
            LogConfigError: If configuration is invalid
        """
        _validate_handler_type(handler_config)

        if not _is_handler_enabled(handler_config):
            return

        handler_type = handler_config["type"]

        # Prepare configuration
        filtered_config = _filter_metadata_fields(handler_config)
        _resolve_log_level(filtered_config, global_level)
        _preserve_special_fields(handler_type, handler_config, filtered_config)

        # Handle console-specific transformations
        if handler_type == "console":
            _convert_console_stream(filtered_config)
            _extract_json_format_options(filtered_config)

        # Create handler config instance
        effective_global_level = global_level or self.global_level
        handler_config_instance = HandlerFactory.create_handler_config(
            handler_type, filtered_config, effective_global_level
        )

        _set_handler_name(handler_config_instance, handler_config)
        self.handlers.append(handler_config_instance)

    def get_handler(self, index: int) -> HandlerConfig | None:
        """
        Get a handler by index.

        Args:
            index: Handler index in the list

        Returns:
            Handler configuration instance, or None if index is out of range
        """
        if 0 <= index < len(self.handlers):
            return self.handlers[index]
        return None

    def get_handler_by_name(self, name: str) -> HandlerConfig | None:
        """
        Get a handler by name (for dictionary-based configurations).

        Args:
            name: Handler name from the configuration

        Returns:
            Handler configuration instance, or None if name not found
        """
        for handler in self.handlers:
            if hasattr(handler, "_handler_name") and handler._handler_name == name:
                return handler
        return None

    def get_enabled_handlers(self) -> list[HandlerConfig]:
        """
        Get all enabled handlers.

        Returns:
            List of enabled handler configurations
        """
        enabled_handlers = []
        for handler in self.handlers:
            # Check if handler has 'enabled' field and it's True
            # For handlers without explicit enabled field, assume enabled
            if getattr(handler, "enabled", True):
                enabled_handlers.append(handler)

        return enabled_handlers

    def iter_handlers(self) -> Any:
        """
        Generator that yields all handlers in order.

        Yields:
            HandlerConfig: Each handler configuration in the registry
        """
        yield from self.handlers

    def iter_enabled_handlers(self) -> Any:
        """
        Generator that yields only enabled handlers.

        Yields:
            HandlerConfig: Each enabled handler configuration
        """
        for handler in self.handlers:
            # Check if handler has 'enabled' field and it's True
            # For handlers without explicit enabled field, assume enabled
            if getattr(handler, "enabled", True):
                yield handler

    def load_from_config(self, handlers_config: Any) -> None:
        """
        Load all handlers from a dictionary configuration.

        Args:
            handlers_config: Dictionary of handler configurations from YAML
                Format: {"handler_name": {"type": "console", ...}, ...}

        Raises:
            LogConfigError: If configuration is invalid
        """
        # Check if it's a dictionary-like object (including DotDict)
        if hasattr(handlers_config, "items") and hasattr(handlers_config, "keys"):
            # Dictionary format: iterate over handler name -> config pairs
            for handler_name, handler_config in handlers_config.items():
                # Add handler name to config for reference
                if hasattr(handler_config, "copy"):
                    handler_config_with_name = handler_config.copy()
                elif hasattr(handler_config, "to_dict"):
                    handler_config_with_name = handler_config.to_dict()
                else:
                    handler_config_with_name = dict(handler_config)
                handler_config_with_name["_handler_name"] = handler_name
                self.add_handler_from_config(
                    handler_config_with_name, self.global_level
                )
        else:
            raise LogConfigError(
                f"Handlers configuration must be a dictionary, got {type(handlers_config)}"
            )
