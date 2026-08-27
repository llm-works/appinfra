# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Database connection management for PostgreSQL.

Handles connection establishment, health checks, and connection pool monitoring.
"""

from typing import Any

import sqlalchemy
import sqlalchemy_utils

from ... import time as infratime


def validate_readonly_config(readonly: bool, create_db: bool) -> None:
    """Validate readonly and create_db settings don't conflict."""
    if readonly and create_db:
        raise ValueError("Cannot create database in readonly mode")


def handle_database_creation(
    engine: sqlalchemy.engine.Engine,
    lg: Any,
    lg_extra: dict[str, Any],
    start_time: float,
) -> None:
    """Create database if it doesn't exist."""
    if not sqlalchemy_utils.database_exists(engine.url):
        sqlalchemy_utils.create_database(engine.url)
        lg.info("created db", extra=lg_extra | {"after": infratime.since(start_time)})


def handle_sqlalchemy_error(
    lg: Any, lg_extra: dict[str, Any], error: Exception, start_time: float
) -> None:
    """Handle SQLAlchemy connection errors."""
    lg.error(
        "failed to connect to db",
        extra=lg_extra | {"after": infratime.since(start_time), "error": str(error)},
    )
    raise


def handle_general_error(
    lg: Any, lg_extra: dict[str, Any], error: Exception, start_time: float
) -> None:
    """Handle general connection errors by wrapping in SQLAlchemyError."""
    lg.error(
        "unexpected error connecting to db",
        extra=lg_extra | {"after": infratime.since(start_time), "error": str(error)},
    )
    raise sqlalchemy.exc.SQLAlchemyError(
        f"Database connection failed: {error}"
    ) from error


class ConnectionManager:
    """
    Manages database connections and health checks.

    Encapsulates connection establishment, health monitoring, and pool status tracking.
    """

    def __init__(
        self, engine: sqlalchemy.engine.Engine, logger: Any, cfg: Any, readonly: bool
    ):
        """
        Initialize connection manager.

        Args:
            engine: SQLAlchemy engine instance
            logger: Logger for connection events
            cfg: Database configuration
            readonly: Whether connection is read-only
        """
        self._engine = engine
        self._lg = logger
        self._cfg = cfg
        self._readonly = readonly
        self._lg_extra: dict[str, Any] = {}

    def set_logging_context(self, lg_extra: dict[str, Any]) -> None:
        """Set logging context for connection operations."""
        self._lg_extra = lg_extra

    def connect(self) -> Any:
        """
        Establish a connection to the PostgreSQL database.

        Handles database creation if specified and ensures proper connection
        setup with logging.

        Returns:
            Database connection object

        Raises:
            sqlalchemy.exc.SQLAlchemyError: If connection fails
            ValueError: If configuration is invalid
        """
        start = infratime.start()
        self._lg.trace("connecting to db...", extra=self._lg_extra)

        create_db = getattr(self._cfg, "create_db", False)
        validate_readonly_config(self._readonly, create_db)

        if self._readonly:
            self._lg.trace("db conn set to readonly", extra=self._lg_extra)

        try:
            if create_db:
                handle_database_creation(self._engine, self._lg, self._lg_extra, start)

            conn = self._engine.connect()
            self._lg.debug(
                "connected to db",
                extra=self._lg_extra | {"after": infratime.since(start)},
            )
            return conn

        except sqlalchemy.exc.SQLAlchemyError as e:
            handle_sqlalchemy_error(self._lg, self._lg_extra, e, start)
        except Exception as e:
            handle_general_error(self._lg, self._lg_extra, e, start)

    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the database connection.

        Returns:
            Dictionary with health check results
        """
        start = infratime.start()
        try:
            # Simple health check - execute a basic query
            conn = self.connect()
            conn.execute(sqlalchemy.text("SELECT 1"))
            conn.close()

            elapsed = infratime.since(start)
            self._lg.debug(
                "health check passed", extra=self._lg_extra | {"after": elapsed}
            )

            return {
                "status": "healthy",
                "response_time_ms": elapsed * 1000,
                "error": None,
            }

        except Exception as e:
            elapsed = infratime.since(start)
            self._lg.error(
                "health check failed",
                extra=self._lg_extra | {"error": str(e), "after": elapsed},
            )

            return {
                "status": "unhealthy",
                "response_time_ms": elapsed * 1000,
                "error": str(e),
            }

    def get_pool_status(self) -> dict[str, Any]:
        """
        Get connection pool status information.

        Returns:
            Dictionary with pool status
        """
        pool = self._engine.pool
        status = {
            "pool_size": pool.size(),  # type: ignore[attr-defined]
            "checked_out": pool.checkedout(),  # type: ignore[attr-defined]
            "overflow": pool.overflow(),  # type: ignore[attr-defined]
            "checked_in": pool.checkedin(),  # type: ignore[attr-defined]
            "total_connections": pool.size() + pool.overflow(),  # type: ignore[attr-defined]
        }

        # Add invalid count if the method exists
        if hasattr(pool, "invalid"):
            status["invalid"] = pool.invalid()
        else:
            status["invalid"] = 0

        return status
