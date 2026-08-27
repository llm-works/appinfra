# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Core initialization, configuration, and logging setup for PostgreSQL interface.

Handles configuration validation, query logging, event listeners, and
initialization helper functions.
"""

import re
import time
from functools import lru_cache
from typing import Any, cast

import sqlalchemy
import sqlalchemy.dialects.postgresql

from ...log import resolve_level


def validate_init_params(lg: Any, cfg: Any) -> None:
    """Validate logger and config parameters."""
    if lg is None:
        raise ValueError("Logger cannot be None")
    if cfg is None:
        raise ValueError("Configuration cannot be None")


def create_sqlalchemy_engine(url: str) -> sqlalchemy.engine.Engine:
    """Create SQLAlchemy engine from URL."""
    return sqlalchemy.create_engine(url, poolclass=sqlalchemy.pool.NullPool)


def initialize_performance_cache(pg_instance: Any) -> None:
    """Initialize performance-related cached attributes."""
    pg_instance._dialect = pg_instance._engine.dialect
    pg_instance._cached_regex = re.compile(r"\n\s+")


def create_engine_and_session(cfg: Any) -> tuple[sqlalchemy.engine.Engine, Any]:
    """Create SQLAlchemy engine and session factory."""
    engine_kwargs = {"poolclass": sqlalchemy.pool.NullPool}
    engine = sqlalchemy.create_engine(cfg.url, **engine_kwargs)
    session_cls = sqlalchemy.orm.sessionmaker(bind=engine)
    return engine, session_cls


def configure_readonly_mode(pg_instance: Any) -> None:
    """Configure readonly mode with validation."""
    if pg_instance.readonly is True:
        if getattr(pg_instance._cfg, "create_db", False) is True:
            raise ValueError("Cannot create database in read-only mode")

        # Use transaction-level readonly (fires when transaction begins)
        def set_transaction_readonly(conn: Any) -> None:
            """Set readonly at transaction level, not session level."""
            conn.execute(sqlalchemy.text("SET TRANSACTION READ ONLY"))

        # Store the listener so it can be removed later
        pg_instance._readonly_listener = set_transaction_readonly
        sqlalchemy.event.listen(pg_instance._engine, "begin", set_transaction_readonly)


def initialize_logging_context(pg_instance: Any, query_lg_level: Any) -> None:
    """Initialize logging context and query log level."""
    pg_instance._lg_extra = {
        "url": pg_instance._engine.url,
        "readonly": pg_instance.readonly,
    }
    pg_instance._query_lg_level = (
        resolve_level(query_lg_level) if query_lg_level is not None else None
    )


def initialize_connection_health(pg_instance: Any) -> None:
    """Initialize connection health tracking attributes."""
    pg_instance._connection_healthy = True
    pg_instance._auto_reconnect = getattr(pg_instance._cfg, "auto_reconnect", True)
    pg_instance._max_retries = getattr(pg_instance._cfg, "max_retries", 3)
    pg_instance._retry_delay = getattr(pg_instance._cfg, "retry_delay", 1.0)


def initialize_performance_optimizations(pg_instance: Any) -> None:
    """Initialize performance optimization caches."""
    pg_instance._whitespace_regex = re.compile(r"\s+")
    pg_instance._dialect = sqlalchemy.dialects.postgresql.dialect()


def log_query_with_timing(
    lg: Any, query_lg_level: int, secs: float, qstr: str, url: Any
) -> None:
    """Log query execution with timing information."""
    try:
        extra = {"after": secs, "query": qstr, "url": url}
        if lg.isEnabledFor(query_lg_level):
            lg._log(query_lg_level, "db query", (), extra=extra)
    except Exception as e:
        # Emergency fallback: write to stderr if custom logging fails
        import sys

        sys.stderr.write(
            f"!!!!!!! UNABLE TO LOG: error[{e}] msg[db query] extra[{extra}]\n"
        )


class QueryLogger:
    """
    Manages query logging and event listener setup.

    Encapsulates SQLAlchemy event listeners for tracking query execution
    and performance monitoring.
    """

    def __init__(
        self,
        engine: sqlalchemy.engine.Engine,
        logger: Any,
        query_lg_level: int | None,
    ):
        """
        Initialize query logger.

        Args:
            engine: SQLAlchemy engine instance
            logger: Logger for query events
            query_lg_level: Log level for query logging (None to disable)
        """
        self._engine = engine
        self._lg = logger
        self._query_lg_level = query_lg_level
        self._whitespace_regex = re.compile(r"\s+")
        self._dialect = sqlalchemy.dialects.postgresql.dialect()
        self._before_cursor_listener: Any = None
        self._after_execute_listener: Any = None

    @lru_cache(maxsize=1000)
    def format_query_string(self, query_str: str) -> str:
        """
        Format query string with caching for better performance.

        Args:
            query_str: Raw query string to format

        Returns:
            Formatted query string with normalized whitespace
        """
        # More efficient than multiple replace calls + regex
        formatted = self._whitespace_regex.sub(
            " ", query_str.replace("\n", " ").replace("\t", " ")
        )
        return cast(str, formatted.strip())

    def create_after_execute_hook(self) -> Any:
        """Create and return the after_execute event listener."""

        def _after_execute(
            conn: Any,
            clauseelement: Any,
            multiparams: Any,
            params: Any,
            execution_options: Any,
            result: Any,
        ) -> None:
            """Log query execution details after completion."""
            secs = time.monotonic() - conn.info["query_start_time"].pop(-1)
            if self._query_lg_level is None:
                return

            comp = clauseelement.compile(
                dialect=self._dialect, compile_kwargs={"literal_binds": True}
            )
            qstr = self.format_query_string(str(comp))
            log_query_with_timing(
                self._lg, self._query_lg_level, secs, qstr, self._engine.url
            )

        # Store the listener so it can be removed later
        self._after_execute_listener = _after_execute
        sqlalchemy.event.listen(self._engine, "after_execute", _after_execute)
        return _after_execute

    def setup_callbacks(self, lg_extra: dict[str, Any]) -> None:
        """
        Set up SQLAlchemy event listeners for query logging and monitoring.

        Args:
            lg_extra: Extra logging context
        """

        def _record_query_start(
            conn: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            """Record the start time of query execution."""
            conn.info.setdefault("query_start_time", []).append(time.monotonic())
            if self._query_lg_level is not None:
                self._lg.trace2("query start")

        # Store the listener so it can be removed later
        self._before_cursor_listener = _record_query_start
        sqlalchemy.event.listen(
            self._engine, "before_cursor_execute", _record_query_start
        )

        self._lg.debug("created db interface", extra={"url": self._engine.url})
        self.create_after_execute_hook()
        self._lg.trace2(
            "created after_execute hook for logging", extra={"url": self._engine.url}
        )


class ConfigValidator:
    """
    Validates database configuration.

    Encapsulates configuration validation logic for PostgreSQL connections.
    """

    @staticmethod
    def validate_config(cfg: Any) -> None:
        """
        Validate database configuration.

        Args:
            cfg: Database configuration object

        Raises:
            ValueError: If configuration is invalid
        """
        if not hasattr(cfg, "url") or not cfg.url:
            raise ValueError("Database URL is required")

        if not isinstance(cfg.url, str):
            raise ValueError("Database URL must be a string")

        if not cfg.url.startswith(("postgresql://", "postgres://")):
            raise ValueError(
                "Database URL must start with 'postgresql://' or 'postgres://'"
            )

    @staticmethod
    def get_engine_kwargs(cfg: Any) -> dict[str, Any]:
        """
        Get SQLAlchemy engine configuration parameters.

        Args:
            cfg: Database configuration object

        Returns:
            Engine configuration parameters
        """
        kwargs = {
            "pool_size": getattr(cfg, "pool_size", 5),
            "max_overflow": getattr(cfg, "max_overflow", 10),
            "pool_timeout": getattr(cfg, "pool_timeout", 30),
            "pool_recycle": getattr(cfg, "pool_recycle", 3600),
            "pool_pre_ping": getattr(cfg, "pool_pre_ping", True),
            "echo": getattr(cfg, "echo", False),
        }

        # Remove None values
        return {k: v for k, v in kwargs.items() if v is not None}
