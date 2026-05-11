"""
Database interface module.

This module defines the abstract base class for database interfaces,
ensuring consistent behavior across different database implementations.
"""

import abc
from typing import Any


class Interface(abc.ABC):
    """
    Abstract base class for database interfaces.

    Defines the interface that all database implementations must follow,
    ensuring consistent behavior across different database types.
    """

    @property
    @abc.abstractmethod
    def cfg(self) -> Any:
        """
        Get the database configuration.

        Returns:
            Configuration object for the database
        """
        pass  # pragma: no cover

    @property
    @abc.abstractmethod
    def url(self) -> str:
        """
        Get the database connection URL.

        Returns:
            str: Database connection URL
        """
        pass  # pragma: no cover

    @property
    @abc.abstractmethod
    def engine(self) -> Any:
        """
        Get the SQLAlchemy engine.

        Returns:
            sqlalchemy.Engine: Database engine instance
        """
        pass  # pragma: no cover

    @abc.abstractmethod
    def connect(self) -> Any:
        """
        Establish a database connection.

        Returns:
            Database connection object
        """
        pass  # pragma: no cover

    @abc.abstractmethod
    def migrate(self) -> None:
        """
        Run database migrations.
        """
        pass  # pragma: no cover

    @abc.abstractmethod
    def session(self, autocommit: bool = False) -> Any:
        """
        Get a managed database session (context manager).

        Args:
            autocommit: If True, use AUTOCOMMIT isolation (no transaction).
                        If False (default), wrap in transaction with auto-commit/rollback.

        Yields:
            Database session instance
        """
        pass  # pragma: no cover
