# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Database session management for PostgreSQL.

Handles session creation, automatic retry logic, and integration with
reconnection strategy.
"""

from typing import Any

import sqlalchemy


class SessionManager:
    """
    Manages database session lifecycle with automatic reconnection.

    Handles session creation, health checks, and retry logic when sessions
    fail due to connection issues.
    """

    def __init__(
        self,
        session_cls: Any,
        logger: Any,
        auto_reconnect: bool = True,
    ):
        """
        Initialize session manager.

        Args:
            session_cls: SQLAlchemy sessionmaker instance
            logger: Logger for session events
            auto_reconnect: Whether to automatically reconnect on failures
        """
        self._SessionCls = session_cls
        self._lg = logger
        self._auto_reconnect = auto_reconnect
        self._lg_extra: dict[str, Any] = {}
        self._connection_healthy = True
        self._reconnect_strategy: Any = None

    def set_logging_context(self, lg_extra: dict[str, Any]) -> None:
        """Set logging context for session operations."""
        self._lg_extra = lg_extra

    def set_reconnect_strategy(self, strategy: Any) -> None:
        """Set reconnection strategy for automatic recovery."""
        self._reconnect_strategy = strategy

    def set_connection_health(self, healthy: bool) -> None:
        """Update connection health status."""
        self._connection_healthy = healthy

    def ensure_connection_healthy(self) -> None:
        """
        Ensure connection is healthy before creating session.

        Proactively reconnects if auto_reconnect enabled and connection unhealthy.
        """
        if self._auto_reconnect and not self._connection_healthy:
            if self._reconnect_strategy:
                if not self._reconnect_strategy.check_connection():
                    self._lg.info("connection unhealthy, attempting reconnect")
                    self._reconnect_strategy.reconnect()
                    self._connection_healthy = self._reconnect_strategy.is_healthy()

    def create_session_with_retry(self) -> Any:
        """
        Create session with automatic retry on failure.

        Returns:
            Database session instance

        Raises:
            sqlalchemy.exc.SQLAlchemyError: If session creation fails
        """
        try:
            session = self._SessionCls()
            self._lg.trace("created database session", extra=self._lg_extra)
            return session
        except Exception as e:
            self._connection_healthy = False
            if self._auto_reconnect:
                return self._retry_session_after_reconnect(e)
            else:
                return self._raise_session_error(e)

    def _retry_session_after_reconnect(self, original_error: Exception) -> Any:
        """
        Retry session creation after reconnecting.

        Args:
            original_error: The original exception that triggered retry

        Returns:
            Database session instance

        Raises:
            sqlalchemy.exc.SQLAlchemyError: If retry fails
        """
        self._lg.info("session creation failed, attempting reconnect")
        try:
            if self._reconnect_strategy:
                self._reconnect_strategy.reconnect()
                self._connection_healthy = self._reconnect_strategy.is_healthy()

            session = self._SessionCls()
            self._lg.trace(
                "created database session after reconnect", extra=self._lg_extra
            )
            return session
        except Exception as reconnect_error:
            self._lg.error(
                "failed to create session even after reconnect",
                extra=self._lg_extra | {"error": str(reconnect_error)},
            )
            raise sqlalchemy.exc.SQLAlchemyError(
                f"Session creation failed after reconnect: {reconnect_error}"
            ) from reconnect_error

    def _raise_session_error(self, error: Exception) -> None:
        """
        Raise session creation error.

        Args:
            error: The original exception

        Raises:
            sqlalchemy.exc.SQLAlchemyError: Always raises
        """
        self._lg.error(
            "failed to create database session",
            extra=self._lg_extra | {"error": str(error)},
        )
        raise sqlalchemy.exc.SQLAlchemyError(
            f"Session creation failed: {error}"
        ) from error

    def session(self) -> Any:
        """
        Create a new database session with automatic reconnection if enabled.

        If auto_reconnect is enabled and the connection is unhealthy,
        this method will attempt to reconnect before creating the session.

        Returns:
            Database session instance

        Raises:
            sqlalchemy.exc.SQLAlchemyError: If session creation fails
        """
        self.ensure_connection_healthy()
        return self.create_session_with_retry()
