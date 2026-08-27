# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Database logging builder for fluent logger configuration.

Provides DatabaseLoggingBuilder class and utility functions for creating
database loggers from configuration.
"""

from collections.abc import Callable
from typing import Any, Self

from ...config import LogConfig
from ...factory import LoggerFactory
from ...logger import Logger
from ..builder import LoggingBuilder
from .config import DatabaseHandlerConfig


class DatabaseLoggingBuilder(LoggingBuilder):
    """
    Specialized builder for database logging configuration.

    Provides convenient methods for configuring loggers that output
    to database tables with customizable table structure and data mapping.
    """

    def __init__(self, name: str):
        """
        Initialize database logging builder.

        Args:
            name: Logger name
        """
        super().__init__(name)

    def with_database_table(
        self,
        table_name: str,
        db_interface: Any,
        level: str | int | None = None,
        columns: dict[str, str] | None = None,
        data_mapper: Callable | None = None,
        batch_size: int = 1,
        flush_interval: float = 0.0,
        # Critical flush parameters
        critical_flush_enabled: bool = False,
        critical_trigger_fields: list[str] | None = None,
        critical_flush_timeout: float = 5.0,
        fallback_to_console: bool = True,
    ) -> Self:
        """
        Add database table output.

        Args:
            table_name: Name of the database table to log to
            db_interface: Database interface instance (e.g., PG)
            level: Handler level (defaults to logger level)
            columns: Column mapping for log data
            data_mapper: Custom function to map log record to database row
            batch_size: Number of records to batch before inserting
            flush_interval: Time in seconds to flush batched records
            critical_flush_enabled: Enable immediate flush for critical errors
            critical_trigger_fields: Fields in 'extra' that trigger immediate flush
            critical_flush_timeout: Max time to wait for critical flush in seconds
            fallback_to_console: If DB flush fails, log to console

        Returns:
            Self for method chaining
        """
        handler_config = DatabaseHandlerConfig(
            table_name=table_name,
            db_interface=db_interface,
            level=level,
            columns=columns,
            data_mapper=data_mapper,
            batch_size=batch_size,
            flush_interval=flush_interval,
            critical_flush_enabled=critical_flush_enabled,
            critical_trigger_fields=critical_trigger_fields,
            critical_flush_timeout=critical_flush_timeout,
            fallback_to_console=fallback_to_console,
        )
        self.with_handler(handler_config)
        return self

    def with_audit_table(
        self,
        db_interface: Any,
        level: str | int | None = None,
        batch_size: int = 10,
        flush_interval: float = 5.0,
    ) -> Self:
        """
        Add audit table output with predefined audit columns.

        Args:
            db_interface: Database interface instance
            level: Handler level (defaults to logger level)
            batch_size: Number of records to batch before inserting
            flush_interval: Time in seconds to flush batched records

        Returns:
            Self for method chaining
        """
        audit_columns = {
            "timestamp": "created_at",
            "level": "log_level",
            "logger": "logger_name",
            "message": "action_description",
            "module": "module_name",
            "function": "function_name",
            "line": "line_number",
            "process_id": "process_id",
            "thread_id": "thread_id",
            "extra": "metadata",
            "exception": "error_details",
        }

        return self.with_database_table(
            table_name="audit_logs",
            db_interface=db_interface,
            level=level,
            columns=audit_columns,
            batch_size=batch_size,
            flush_interval=flush_interval,
        )

    def with_error_table(
        self,
        db_interface: Any,
        level: str | int | None = None,
        batch_size: int = 5,
        flush_interval: float = 2.0,
    ) -> Self:
        """
        Add error table output for error tracking.

        Args:
            db_interface: Database interface instance
            level: Handler level (defaults to logger level)
            batch_size: Number of records to batch before inserting
            flush_interval: Time in seconds to flush batched records

        Returns:
            Self for method chaining
        """
        error_columns = {
            "timestamp": "error_time",
            "level": "severity",
            "logger": "source_logger",
            "message": "error_message",
            "module": "module_name",
            "function": "function_name",
            "line": "line_number",
            "process_id": "process_id",
            "thread_id": "thread_id",
            "extra": "context_data",
            "exception": "stack_trace",
        }

        return self.with_database_table(
            table_name="error_logs",
            db_interface=db_interface,
            level=level,
            columns=error_columns,
            batch_size=batch_size,
            flush_interval=flush_interval,
        )

    def with_custom_table(
        self,
        table_name: str,
        db_interface: Any,
        data_mapper: Callable,
        level: str | int | None = None,
        batch_size: int = 1,
        flush_interval: float = 0.0,
    ) -> Self:
        """
        Add custom table output with custom data mapping.

        Args:
            table_name: Name of the database table to log to
            db_interface: Database interface instance
            data_mapper: Custom function to map log record to database row
            level: Handler level (defaults to logger level)
            batch_size: Number of records to batch before inserting
            flush_interval: Time in seconds to flush batched records

        Returns:
            Self for method chaining
        """
        return self.with_database_table(
            table_name=table_name,
            db_interface=db_interface,
            level=level,
            data_mapper=data_mapper,
            batch_size=batch_size,
            flush_interval=flush_interval,
        )

    def with_critical_error_flush(
        self,
        enabled: bool = True,
        trigger_fields: list[str] | None = None,
        timeout: float = 5.0,
        fallback_to_console: bool = True,
    ) -> Self:
        """
        Configure critical error immediate flush behavior.

        Args:
            enabled: Enable critical error immediate flush
            trigger_fields: Fields in 'extra' that trigger immediate flush
            timeout: Max time to wait for critical flush in seconds
            fallback_to_console: If DB flush fails, log to console

        Returns:
            Self for method chaining
        """
        # Apply to all database handlers in this builder
        for handler_config in self._handlers:
            if isinstance(handler_config, DatabaseHandlerConfig):
                handler_config.critical_flush_enabled = enabled
                handler_config.critical_trigger_fields = trigger_fields or ["exception"]
                handler_config.critical_flush_timeout = timeout
                handler_config.fallback_to_console = fallback_to_console
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
        for handler_config in self._handlers:
            handler = handler_config.create_handler(config, logger=logger)
            logger.addHandler(handler)

        return logger


# Convenience function for database logging builder
def create_database_logger(name: str) -> DatabaseLoggingBuilder:
    """
    Create a database logging builder.

    Args:
        name: Logger name

    Returns:
        DatabaseLoggingBuilder instance
    """
    return DatabaseLoggingBuilder(name)


# Helper functions for load_database_logging_config()


def _load_config_from_handler(handler_config: dict) -> dict:
    """Load database logging config from handler configuration."""
    critical_flush_config = handler_config.get("critical_flush", {})
    return {
        "default_batch_size": handler_config.get("batch_size", 10),
        "default_flush_interval": handler_config.get("flush_interval", 30),
        "critical_flush": {
            "enabled": critical_flush_config.get("enabled", True),
            "trigger_fields": critical_flush_config.get(
                "trigger_fields", ["exception"]
            ),
            "timeout": critical_flush_config.get("timeout", 5.0),
            "fallback_to_console": critical_flush_config.get(
                "fallback_to_console", True
            ),
        },
    }


def _load_config_from_top_level(config_dict: dict) -> dict:
    """Load database logging config from top-level configuration (backward compatibility)."""
    db_config = config_dict.get("database_logging", {})
    critical_flush = db_config.get("critical_flush", {})
    return {
        "default_batch_size": db_config.get("default_batch_size", 10),
        "default_flush_interval": db_config.get("default_flush_interval", 30),
        "critical_flush": {
            "enabled": critical_flush.get("enabled", True),
            "trigger_fields": critical_flush.get("trigger_fields", ["exception"]),
            "timeout": critical_flush.get("timeout", 5.0),
            "fallback_to_console": critical_flush.get("fallback_to_console", True),
        },
    }


def load_database_logging_config(
    config_dict: dict, handler_config: dict | None = None
) -> dict:
    """
    Load database logging configuration from config dictionary.

    Args:
        config_dict: Configuration dictionary (e.g., from Config class)
        handler_config: Specific handler configuration (optional)

    Returns:
        Dictionary with database logging configuration

    Example:
        from appinfra.config import Config
        config = Config("etc/infra.yaml")

        # From specific handler config
        handler_config = config.logging.handlers[0]  # database handler
        db_config = load_database_logging_config(config.dict(), handler_config)
    """
    if handler_config:
        return _load_config_from_handler(handler_config)
    else:
        return _load_config_from_top_level(config_dict)


def create_database_logger_from_config(
    name: str,
    config_dict: dict,
    db_interface: Any,
    table_name: str = "error_logs",
    handler_config: dict | None = None,
) -> DatabaseLoggingBuilder:
    """
    Create a database logging builder from configuration.

    Args:
        name: Logger name
        config_dict: Configuration dictionary
        db_interface: Database interface instance
        table_name: Database table name
        handler_config: Specific handler configuration (optional)

    Returns:
        Configured DatabaseLoggingBuilder instance
    """
    db_config = load_database_logging_config(config_dict, handler_config)

    builder = DatabaseLoggingBuilder(name)

    # Configure database table with critical flush
    builder.with_database_table(
        table_name=table_name,
        db_interface=db_interface,
        batch_size=db_config["default_batch_size"],
        flush_interval=db_config["default_flush_interval"],
        critical_flush_enabled=db_config["critical_flush"]["enabled"],
        critical_trigger_fields=db_config["critical_flush"]["trigger_fields"],
        critical_flush_timeout=db_config["critical_flush"]["timeout"],
        fallback_to_console=db_config["critical_flush"]["fallback_to_console"],
    )

    return builder
