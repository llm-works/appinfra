# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Quick setup functions for common logging configurations.

This module provides convenient functions for quickly setting up loggers
with common configurations without needing to use the builder pattern.
"""

from typing import Any

from ..logger import Logger
from .builder import LoggingBuilder
from .console import ConsoleLoggingBuilder
from .file import FileLoggingBuilder
from .json import JSONLoggingBuilder

# Helper for quick_custom_database_logger


def _create_data_mapper_from_columns(columns: dict) -> Any:
    """Create data mapper function from column definitions."""

    def data_mapper(record: Any) -> dict:
        from datetime import datetime

        data = {}
        for field, column_name in columns.items():
            if field == "timestamp":
                data[column_name] = datetime.fromtimestamp(record.created)
            elif field == "level":
                data[column_name] = record.levelname
            elif field == "logger":
                data[column_name] = record.name
            elif field == "message":
                data[column_name] = record.getMessage()
            elif field == "module" and record.module:
                data[column_name] = record.module
            elif field == "function" and record.funcName:
                data[column_name] = record.funcName
            elif field == "line" and record.lineno:
                data[column_name] = record.lineno
        return data

    return data_mapper


# Basic quick functions from builder.py
def quick_console_logger(name: str, config: dict[str, Any] | None = None) -> Logger:
    """
    Create a quick console logger.

    Args:
        name: Logger name
        config: Configuration dictionary with keys:
            - level: Log level (default: "info")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)

    Returns:
        Logger instance
    """
    if config is None:
        config = {"level": "info"}

    return LoggingBuilder(name).with_config(config).with_console_handler().build()


def quick_file_logger(
    name: str, filename: str, config: dict[str, Any] | None = None
) -> Logger:
    """
    Create a quick file logger.

    Args:
        name: Logger name
        filename: Log file path
        config: Configuration dictionary with keys:
            - level: Log level (default: "info")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)

    Returns:
        Logger instance
    """
    if config is None:
        config = {"level": "info"}

    return LoggingBuilder(name).with_config(config).with_file_handler(filename).build()


def quick_both_logger(
    name: str, filename: str, config: dict[str, Any] | None = None
) -> Logger:
    """
    Create a quick logger with both console and file output.

    Args:
        name: Logger name
        filename: Log file path
        config: Configuration dictionary with keys:
            - level: Log level (default: "info")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)

    Returns:
        Logger instance
    """
    if config is None:
        config = {"level": "info"}

    return (
        LoggingBuilder(name)
        .with_config(config)
        .with_console_handler()
        .with_file_handler(filename)
        .build()
    )


# Console quick functions from console.py
def quick_console_with_colors(
    name: str, config: dict[str, Any] | None = None
) -> Logger:
    """
    Create a quick console logger with colors enabled.

    Args:
        name: Logger name
        config: Configuration dictionary with keys:
            - level: Log level (default: "info")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)

    Returns:
        Logger instance
    """
    if config is None:
        config = {"level": "info"}

    # Always enable colors for this function, but allow override
    colors_enabled = config.get("colors", True)
    config_with_colors = config.copy()
    config_with_colors["colors"] = colors_enabled

    return ConsoleLoggingBuilder(name).with_config(config_with_colors).build()


# File quick functions from file.py
def quick_file_with_rotation(
    name: str,
    filename: str,
    config: dict[str, Any] | None = None,
    max_bytes: int = 1024 * 1024,
    backup_count: int = 5,
) -> Logger:
    """
    Create a quick file logger with rotation.

    Args:
        name: Logger name
        filename: Log file path
        config: Configuration dictionary with keys:
            - level: Log level (default: "info")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)
        max_bytes: Maximum file size before rotation
        backup_count: Number of backup files to keep

    Returns:
        Logger instance
    """
    if config is None:
        config = {"level": "info"}

    return (
        FileLoggingBuilder(name, filename)
        .with_config(config)
        .with_rotation(max_bytes=max_bytes, backup_count=backup_count)
        .build()
    )


def quick_daily_file_logger(
    name: str,
    filename: str,
    config: dict[str, Any] | None = None,
    backup_count: int = 7,
) -> Logger:
    """
    Create a quick file logger with daily rotation.

    Args:
        name: Logger name
        filename: Log file path
        config: Configuration dictionary with keys:
            - level: Log level (default: "info")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)
        backup_count: Number of backup files to keep

    Returns:
        Logger instance
    """
    if config is None:
        config = {"level": "info"}

    return (
        FileLoggingBuilder(name, filename)
        .with_config(config)
        .daily_rotation(backup_count=backup_count)
        .build()
    )


# Multi-output quick functions from multi_output.py
def quick_console_and_file(
    name: str, filename: str, config: dict[str, Any] | None = None
) -> Logger:
    """
    Create a quick logger with both console and file output.

    Args:
        name: Logger name
        filename: Log file path
        config: Configuration dictionary with keys:
            - level: Log level (default: "info")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)

    Returns:
        Logger instance
    """
    if config is None:
        config = {"level": "info"}

    return (
        LoggingBuilder(name)
        .with_config(config)
        .with_console_handler()
        .with_file_handler(filename)
        .build()
    )


# Database quick functions from database.py
# Note: These functions require the [sql] extra: pip install appinfra[sql]
def quick_audit_logger(
    name: str, db_interface: Any, config: dict[str, Any] | None = None
) -> Logger:
    """
    Create a quick audit logger.

    Args:
        name: Logger name
        db_interface: Database interface
        config: Configuration dictionary with keys:
            - level: Log level (default: "info")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)

    Returns:
        Logger instance

    Raises:
        DependencyError: If sqlalchemy is not installed
    """
    from .database import DatabaseLoggingBuilder

    if config is None:
        config = {"level": "info"}

    return (
        DatabaseLoggingBuilder(name)
        .with_config(config)
        .with_audit_table(db_interface)
        .build()
    )


def quick_error_logger(
    name: str, db_interface: Any, config: dict[str, Any] | None = None
) -> Logger:
    """
    Create a quick error logger.

    Args:
        name: Logger name
        db_interface: Database interface
        config: Configuration dictionary with keys:
            - level: Log level (default: "error")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)

    Returns:
        Logger instance

    Raises:
        DependencyError: If sqlalchemy is not installed
    """
    from .database import DatabaseLoggingBuilder

    if config is None:
        config = {"level": "error"}

    return (
        DatabaseLoggingBuilder(name)
        .with_config(config)
        .with_error_table(db_interface)
        .build()
    )


def quick_custom_database_logger(
    name: str,
    db_interface: Any,
    table_name: str,
    config: dict[str, Any] | None = None,
    columns: dict | None = None,
) -> Logger:
    """
    Create a quick custom database logger.

    Args:
        name: Logger name
        db_interface: Database interface
        table_name: Custom table name
        config: Configuration dictionary with keys:
            - level: Log level (default: "info")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)
        columns: Custom column definitions

    Returns:
        Logger instance

    Raises:
        DependencyError: If sqlalchemy is not installed
    """
    from .database import DatabaseLoggingBuilder

    if config is None:
        config = {"level": "info"}

    # Create data mapper from columns if provided
    data_mapper = _create_data_mapper_from_columns(columns) if columns else None

    return (
        DatabaseLoggingBuilder(name)
        .with_config(config)
        .with_custom_table(table_name, db_interface, data_mapper)  # type: ignore[arg-type]
        .build()
    )


# JSON quick functions from json.py
def quick_json_console(name: str, config: dict[str, Any] | None = None) -> Logger:
    """
    Create a quick JSON console logger.

    Args:
        name: Logger name
        config: Configuration dictionary with keys:
            - level: Log level (default: "info")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)

    Returns:
        Logger instance
    """
    if config is None:
        config = {"level": "info"}

    return JSONLoggingBuilder(name).with_config(config).with_json_console(True).build()


def quick_json_file(
    name: str,
    filename: str,
    config: dict[str, Any] | None = None,
    pretty_print: bool = False,
) -> Logger:
    """
    Create a quick JSON file logger.

    Args:
        name: Logger name
        filename: Log file path
        config: Configuration dictionary with keys:
            - level: Log level (default: "info")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)
        pretty_print: Whether to pretty print JSON

    Returns:
        Logger instance
    """
    if config is None:
        config = {"level": "info"}

    builder = JSONLoggingBuilder(name).with_config(config).with_json_file(filename)

    if pretty_print:
        builder = builder.with_pretty_print(True)

    return builder.build()


def quick_both_outputs(
    name: str,
    filename: str,
    config: dict[str, Any] | None = None,
    pretty_print: bool = False,
) -> Logger:
    """
    Create a quick logger with both JSON console and file output.

    Args:
        name: Logger name
        filename: Log file path
        config: Configuration dictionary with keys:
            - level: Log level (default: "info")
            - location: Location display level (default: 0)
            - micros: Whether to show microsecond precision (default: False)
            - colors: Whether to enable colored output (default: True)
        pretty_print: Whether to pretty print JSON

    Returns:
        Logger instance
    """
    if config is None:
        config = {"level": "info"}

    builder = (
        JSONLoggingBuilder(name)
        .with_config(config)
        .with_json_console(True)
        .with_json_file(filename)
    )

    if pretty_print:
        builder = builder.with_pretty_print(True)

    return builder.build()
