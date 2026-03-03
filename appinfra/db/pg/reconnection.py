"""
Database reconnection strategy with exponential backoff.

Handles automatic reconnection to PostgreSQL with configurable retry logic
and exponential backoff delays.
"""

import time
from typing import Any

import sqlalchemy

from ...errors import DatabaseError


class ReconnectionStrategy:
    """
    Manages database reconnection with exponential backoff.

    Encapsulates the logic for checking connection health, attempting reconnects,
    and managing retry delays.
    """

    def __init__(
        self,
        engine: sqlalchemy.engine.Engine,
        logger: Any,
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ):
        """
        Initialize reconnection strategy.

        Args:
            engine: SQLAlchemy engine instance
            logger: Logger for reconnection events
            max_retries: Maximum retry attempts
            retry_delay: Initial delay between retries (seconds)
        """
        self._engine = engine
        self._lg = logger
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._connection_healthy = True
        self._lg_extra: dict[str, Any] = {}

    def set_logging_context(self, lg_extra: dict[str, Any]) -> None:
        """Set logging context for reconnection operations."""
        self._lg_extra = lg_extra

    def is_healthy(self) -> bool:
        """Return current connection health status."""
        return self._connection_healthy

    def check_connection(self, timeout: float = 5.0) -> bool:
        """
        Check if database connection is healthy.

        Args:
            timeout: Query timeout in seconds

        Returns:
            True if connection is healthy, False otherwise
        """
        try:
            # Quick health check with timeout
            with self._engine.connect() as conn:
                conn.execute(
                    sqlalchemy.text("SELECT 1").execution_options(timeout=timeout)
                )
            self._connection_healthy = True
            return True
        except Exception as e:
            self._lg.warning(
                "connection health check failed",
                extra=self._lg_extra | {"error": str(e)},
            )
            self._connection_healthy = False
            return False

    def attempt_reconnect(self, attempt_num: int) -> bool:
        """
        Attempt a single reconnection.

        Args:
            attempt_num: Current attempt number (for logging)

        Returns:
            True if reconnection successful
        """
        try:
            self._engine.dispose()
            if self.check_connection():
                self._lg.info(
                    "reconnected to database",
                    extra=self._lg_extra | {"attempt": attempt_num},
                )
                return True
        except Exception as e:
            self._lg.warning(
                f"reconnection attempt {attempt_num} failed",
                extra=self._lg_extra | {"error": str(e)},
            )
        return False

    def reconnect_with_backoff(self, max_retries: int, delay: float) -> bool:
        """
        Execute reconnection attempts with exponential backoff.

        Args:
            max_retries: Maximum retry attempts
            delay: Initial delay between retries

        Returns:
            True if any attempt succeeded

        Raises:
            DatabaseError: If all retries exhausted
        """
        for attempt in range(max_retries):
            if self.attempt_reconnect(attempt + 1):
                return True

            # Exponential backoff before next retry
            if attempt < max_retries - 1:
                wait_time = delay * (2**attempt)
                self._lg.debug(
                    f"waiting {wait_time:.2f}s before retry",
                    extra=self._lg_extra,
                )
                time.sleep(wait_time)

        # All retries exhausted
        self._connection_healthy = False
        error_msg = f"Failed to reconnect after {max_retries} attempts"
        self._lg.error(error_msg, extra=self._lg_extra)
        raise DatabaseError(error_msg, url=str(self._engine.url), retries=max_retries)

    def reconnect(
        self, max_retries: int | None = None, initial_delay: float | None = None
    ) -> bool:
        """
        Reconnect to the database with exponential backoff.

        Args:
            max_retries: Maximum retry attempts (uses default if None)
            initial_delay: Initial retry delay (uses default if None)

        Returns:
            True if reconnection successful

        Raises:
            DatabaseError: If reconnection fails after all retries
        """
        max_retries = max_retries if max_retries is not None else self._max_retries
        delay = initial_delay if initial_delay is not None else self._retry_delay
        self._lg.info("attempting to reconnect to database", extra=self._lg_extra)
        return self.reconnect_with_backoff(max_retries, delay)
