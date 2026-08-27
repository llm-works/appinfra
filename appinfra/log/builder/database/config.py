# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Database handler configuration for logging to database tables.

Provides configuration objects for database logging handlers with customizable
table structure and data mapping.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ...config import LogConfig
from ..interface import HandlerConfig

if TYPE_CHECKING:
    from .handler import DatabaseHandler


class DatabaseHandlerConfig(HandlerConfig):
    """
    Configuration for database logging handlers.

    Provides configuration for logging to database tables with customizable
    table structure and data mapping.
    """

    def __init__(
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
    ) -> None:
        """
        Initialize database handler configuration.

        Args:
            table_name: Name of the database table to log to
            db_interface: Database interface instance (e.g., PG)
            level: Handler level (defaults to logger level)
            columns: Column mapping for log data (defaults to standard columns)
            data_mapper: Custom function to map log record to database row
            batch_size: Number of records to batch before inserting
            flush_interval: Time in seconds to flush batched records
            critical_flush_enabled: Enable immediate flush for critical errors
            critical_trigger_fields: Fields in 'extra' that trigger immediate flush
            critical_flush_timeout: Max time to wait for critical flush in seconds
            fallback_to_console: If DB flush fails, log to console
        """
        super().__init__(level)
        self.table_name = table_name
        self.db_interface = db_interface
        self.columns = columns or self._default_columns()
        self.data_mapper = data_mapper or self._default_data_mapper
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.critical_flush_enabled = critical_flush_enabled
        self.critical_trigger_fields = critical_trigger_fields or ["exception"]
        self.critical_flush_timeout = critical_flush_timeout
        self.fallback_to_console = fallback_to_console

    def _default_columns(self) -> dict[str, str]:
        """Get default column mapping for log data."""
        return {
            "timestamp": "timestamp",
            "level": "level",
            "logger": "logger_name",
            "message": "message",
            "module": "module",
            "function": "function",
            "line": "line_number",
            "process_id": "process_id",
            "thread_id": "thread_id",
            "extra": "extra_data",
            "exception": "exception_info",
        }

    def _map_optional_fields(
        self, record: logging.LogRecord, data: dict[str, Any]
    ) -> None:
        """Map optional fields from log record to data dict."""
        if record.module:
            data[self.columns["module"]] = record.module
        if record.funcName:
            data[self.columns["function"]] = record.funcName
        if record.lineno:
            data[self.columns["line"]] = record.lineno
        if record.process:
            data[self.columns["process_id"]] = record.process
        if record.thread:
            data[self.columns["thread_id"]] = record.thread

    def _map_exception_info(
        self, record: logging.LogRecord, data: dict[str, Any]
    ) -> None:
        """Map exception info from log record to data dict."""
        if record.exc_info:
            import traceback

            data[self.columns["exception"]] = "".join(
                traceback.format_exception(*record.exc_info)
            )

    def _default_data_mapper(self, record: logging.LogRecord) -> dict[str, Any]:
        """Default data mapper for log records."""
        data: dict[str, Any] = {}

        # Map standard fields
        data[self.columns["timestamp"]] = datetime.fromtimestamp(record.created)
        data[self.columns["level"]] = record.levelname
        data[self.columns["logger"]] = record.name
        data[self.columns["message"]] = record.getMessage()

        # Map optional fields
        self._map_optional_fields(record, data)

        # Extra fields
        extra = getattr(record, "__infra__extra", None)
        if extra:
            data[self.columns["extra"]] = json.dumps(extra)

        # Exception info
        self._map_exception_info(record, data)

        return data

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to picklable dictionary.

        Raises:
            NotImplementedError: Database handlers cannot be serialized because
                                 db_interface and data_mapper are not picklable.
        """
        raise NotImplementedError(
            "DatabaseHandlerConfig cannot be serialized for subprocess logging. "
            "Database handlers must be configured independently in each subprocess "
            "with their own database connection."
        )

    def create_handler(
        self, config: LogConfig, logger: Any = None, lifecycle_manager: Any = None
    ) -> DatabaseHandler:
        """Create a database handler instance.

        Args:
            config: Logger configuration
            logger: Logger instance for error logging (required)
            lifecycle_manager: Optional lifecycle manager for shutdown registration
        """
        if logger is None:
            raise ValueError(
                "DatabaseHandler requires a logger instance for error logging"
            )
        # Import here to avoid circular dependency
        from .handler import DatabaseHandler

        return DatabaseHandler(logger, self, config, lifecycle_manager)
