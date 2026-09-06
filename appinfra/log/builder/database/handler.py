# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Database logging handler implementation.

Handles logging to database tables with batching, performance optimization,
and critical error flush mechanism.

Requires: pip install appinfra[sql]
"""

import logging
import signal
from datetime import datetime
from typing import Any

from ....errors import DependencyError
from ...config import LogConfig
from .config import DatabaseHandlerConfig

# Lazy import sqlalchemy - it's an optional dependency
try:
    import sqlalchemy

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    sqlalchemy = None  # type: ignore[assignment]
    SQLALCHEMY_AVAILABLE = False


def _require_sqlalchemy() -> None:
    """Raise DependencyError if sqlalchemy is not installed."""
    if not SQLALCHEMY_AVAILABLE:
        raise DependencyError("sqlalchemy", "sql", "Database logging")


class DatabaseHandler(logging.Handler):
    """
    Database logging handler.

    Handles logging to database tables with batching and custom data mapping.
    """

    def __init__(
        self,
        lg: Any,
        handler_config: DatabaseHandlerConfig,
        log_config: LogConfig,
        lifecycle_manager: Any = None,
    ) -> None:
        """
        Initialize database handler.

        Args:
            lg: Logger instance for error logging
            handler_config: Database handler configuration
            log_config: Logger configuration
            lifecycle_manager: Optional lifecycle manager for shutdown registration

        Raises:
            DependencyError: If sqlalchemy is not installed
        """
        _require_sqlalchemy()
        super().__init__()
        self._lg = lg
        self.handler_config = handler_config
        self.log_config = log_config
        self.batch: list[dict[str, Any]] = []
        self.last_flush = datetime.now()

        # Cache INSERT statements per column set
        self._sql_cache: dict[tuple, str] = {}

        # Set handler level with proper resolution
        level = handler_config.level or log_config.level
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        self.setLevel(level)

        # Register with lifecycle manager if provided
        if lifecycle_manager and hasattr(lifecycle_manager, "register_db_handler"):
            lifecycle_manager.register_db_handler(self)

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to the database."""
        try:
            # Map record to database row
            row_data = self.handler_config.data_mapper(record)

            # Check if this is a critical error requiring immediate flush
            if self._is_critical_error(record):
                self._critical_flush(row_data)
            else:
                # Normal batching behavior
                self.batch.append(row_data)
                if self._should_flush_batch():
                    self._flush_batch()

        except Exception:
            self.handleError(record)

    def _should_flush_batch(self) -> bool:
        """Check if the batch should be flushed based on size or time."""
        return len(self.batch) >= self.handler_config.batch_size or (
            self.handler_config.flush_interval > 0
            and (datetime.now() - self.last_flush).total_seconds()
            >= self.handler_config.flush_interval
        )

    def _is_critical_error(self, record: logging.LogRecord) -> bool:
        """Check if this log record contains critical error information."""
        if not self.handler_config.critical_flush_enabled:
            return False

        # Check if record has exception information
        if hasattr(record, "exc_info") and record.exc_info:
            return True

        # Check if 'extra' dict contains trigger fields
        if hasattr(record, "extra") and record.extra:
            for field in self.handler_config.critical_trigger_fields:
                if field in record.extra:
                    return True

        return False

    def _critical_flush(self, row_data: dict[str, Any]) -> None:
        """Immediately flush critical error to database."""
        try:
            # Use a timeout to prevent hanging during app crash

            def timeout_handler(signum: int, frame: Any) -> None:
                raise TimeoutError("Critical flush timeout")

            # Set timeout
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(int(self.handler_config.critical_flush_timeout))

            try:
                # Immediate database write (session auto-commits on success)
                with self.handler_config.db_interface.session() as session:
                    self._insert_single_record(session, row_data)

            finally:
                # Restore signal handler
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

        except Exception:
            # Fallback to console if database flush fails
            if self.handler_config.fallback_to_console:
                self._lg.critical(f"CRITICAL ERROR (DB flush failed): {row_data}")
            raise

    @staticmethod
    def _quote_identifier(name: str) -> str:
        """Quote an identifier to handle reserved words and special characters.

        Uses ANSI SQL double-quote delimiters. Internal double-quotes are escaped
        by doubling them.
        """
        escaped = name.replace('"', '""')
        return f'"{escaped}"'

    @staticmethod
    def _normalize_bind_name(name: str) -> str:
        """Normalize a column name into a valid SQLAlchemy bind parameter name.

        SQLAlchemy's text() parses :name and stops at non-alphanumeric characters,
        so `event-type` would be parsed as just `event`. Replace any character
        that is not alphanumeric or underscore with an underscore.
        """
        import re

        return re.sub(r"[^a-zA-Z0-9_]", "_", name)

    def _get_insert_sql(self, columns_tuple: tuple) -> str:
        """Get cached INSERT SQL statement for given columns."""
        if columns_tuple not in self._sql_cache:
            columns = list(columns_tuple)
            quoted_table = self._quote_identifier(self.handler_config.table_name)
            quoted_cols = ", ".join(self._quote_identifier(c) for c in columns)
            # Use normalized bind names to avoid SQLAlchemy parsing issues
            placeholders = ", ".join(
                f":{self._normalize_bind_name(c)}" for c in columns
            )
            self._sql_cache[columns_tuple] = (
                f"INSERT INTO {quoted_table} ({quoted_cols}) VALUES ({placeholders})"
            )
        return self._sql_cache[columns_tuple]

    def _remap_row_keys(self, row: dict[str, Any]) -> dict[str, Any]:
        """Remap row keys to normalized bind parameter names."""
        return {self._normalize_bind_name(k): v for k, v in row.items()}

    def _insert_single_record(self, session: Any, row_data: dict[str, Any]) -> None:
        """Insert a single record into the database table."""
        if not row_data:
            return

        # Use cached SQL statement
        columns_tuple = tuple(sorted(row_data.keys()))
        insert_sql = self._get_insert_sql(columns_tuple)
        # Remap keys to normalized bind parameter names
        session.execute(sqlalchemy.text(insert_sql), self._remap_row_keys(row_data))

    def _flush_batch(self) -> None:
        """Flush the current batch to the database."""
        if not self.batch:
            return

        try:
            # Get database session (auto-commits on success)
            with self.handler_config.db_interface.session() as session:
                # Insert batch data
                self._insert_batch(session, self.batch)

        except Exception as e:
            # Log error but don't raise to avoid infinite recursion
            self._lg.error("database logging error", extra={"exception": e})
        finally:
            self.batch.clear()
            self.last_flush = datetime.now()

    def _insert_batch(self, session: Any, batch_data: list[dict[str, Any]]) -> None:
        """Insert a batch, grouping rows by column set.

        Rows with the same columns are inserted together via executemany.
        Grouping by column set avoids sending NULL for absent columns, which
        would bypass server defaults.
        """
        if not batch_data:
            return

        # Group rows by their column set so omitted columns stay omitted
        groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for row in batch_data:
            key = tuple(sorted(row.keys()))
            groups.setdefault(key, []).append(row)

        for columns_tuple, rows in groups.items():
            insert_sql = self._get_insert_sql(columns_tuple)
            # Remap keys to normalized bind parameter names
            remapped = [self._remap_row_keys(row) for row in rows]
            session.execute(sqlalchemy.text(insert_sql), remapped)

    def close(self) -> None:
        """Close the handler and flush any remaining data."""
        self._flush_batch()
        super().close()
