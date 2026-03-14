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

        # Performance optimizations: cache SQL statements and metadata
        self._sql_cache: dict[tuple, str] = {}  # Cache prepared statements
        self._table_metadata: Any = None  # Cache table metadata for bulk operations

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
                # Immediate database write
                with self.handler_config.db_interface.session() as session:
                    self._insert_single_record(session, row_data)
                    session.commit()

            finally:
                # Restore signal handler
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

        except Exception:
            # Fallback to console if database flush fails
            if self.handler_config.fallback_to_console:
                self._lg.critical(f"CRITICAL ERROR (DB flush failed): {row_data}")
            raise

    def _get_insert_sql(self, columns_tuple: tuple) -> str:
        """Get cached INSERT SQL statement for given columns."""
        if columns_tuple not in self._sql_cache:
            columns = list(columns_tuple)
            column_names = ", ".join(columns)
            placeholders = ", ".join([f":{col}" for col in columns])
            table_name = self.handler_config.table_name
            self._sql_cache[columns_tuple] = (
                f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"
            )
        return self._sql_cache[columns_tuple]

    def _insert_single_record(self, session: Any, row_data: dict[str, Any]) -> None:
        """Insert a single record into the database table."""
        if not row_data:
            return

        # Use cached SQL statement
        columns_tuple = tuple(sorted(row_data.keys()))
        insert_sql = self._get_insert_sql(columns_tuple)
        session.execute(sqlalchemy.text(insert_sql), row_data)

    def _flush_batch(self) -> None:
        """Flush the current batch to the database."""
        if not self.batch:
            return

        try:
            # Get database session
            with self.handler_config.db_interface.session() as session:
                # Insert batch data
                self._insert_batch(session, self.batch)
                session.commit()

        except Exception as e:
            # Log error but don't raise to avoid infinite recursion
            self._lg.error("database logging error", extra={"exception": e})
        finally:
            self.batch.clear()
            self.last_flush = datetime.now()

    def _get_table_metadata(self, session: Any) -> Any:
        """Get cached table metadata for bulk operations."""
        if self._table_metadata is None:
            try:
                metadata = sqlalchemy.MetaData()
                self._table_metadata = sqlalchemy.Table(
                    self.handler_config.table_name, metadata, autoload_with=session.bind
                )
            except Exception:
                # If we can't get metadata, we'll fall back to executemany
                self._table_metadata = False
        return self._table_metadata

    def _insert_batch(self, session: Any, batch_data: list[dict[str, Any]]) -> None:
        """Insert batch data using optimized bulk operations."""
        if not batch_data:
            return

        try:
            # Try to use SQLAlchemy bulk operations for best performance
            table = self._get_table_metadata(session)
            if table is not False:
                # Use bulk_insert_mappings for maximum performance
                session.bulk_insert_mappings(table.__class__, batch_data)
                return
        except Exception:
            # Fall back to executemany if bulk operations fail
            pass

        # Fallback: Use executemany which is still much faster than individual executes
        if batch_data:
            columns_tuple = tuple(sorted(batch_data[0].keys()))
            insert_sql = self._get_insert_sql(columns_tuple)

            # Use executemany for better performance than individual execute calls
            session.execute(sqlalchemy.text(insert_sql), batch_data)

    def close(self) -> None:
        """Close the handler and flush any remaining data."""
        self._flush_batch()
        super().close()
