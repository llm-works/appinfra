"""
Scoped PostgreSQL access for per-operation schema selection.

Provides session-level schema isolation without engine-level binding,
allowing a single PG instance to serve multiple schemas.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ...errors import DatabaseError
from .schema import validate_schema_name

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from ...log import Logger
    from .pg import PG


class ScopedPG:
    """
    PG wrapper scoped to a specific PostgreSQL schema.

    Provides session-level schema isolation without engine-level binding.
    Sessions have search_path set at creation, not via event listeners.

    Unlike PG.session() which returns a raw session, ScopedPG.session()
    is a context manager that handles commit/rollback/close automatically.

    Example:
        >>> pg = PG(logger, config)  # Schema-agnostic
        >>> scoped = pg.scoped("my_schema")
        >>> with scoped.session() as session:
        ...     session.query(MyModel).all()  # Uses my_schema.* tables

        >>> # Multiple scopes from same PG
        >>> scope_a = pg.scoped("schema_a")
        >>> scope_b = pg.scoped("schema_b")
    """

    def __init__(self, lg: Logger, pg: PG, schema_name: str) -> None:
        """
        Initialize a scoped PG wrapper.

        Args:
            lg: Logger instance
            pg: Parent PG instance
            schema_name: PostgreSQL schema name for this scope

        Raises:
            ValueError: If schema name is invalid
        """
        self._lg = lg
        self._pg = pg
        self._schema_name = self._validate_schema_name(schema_name)

    @staticmethod
    def _validate_schema_name(name: str) -> str:
        """
        Validate schema name to prevent SQL injection.

        Args:
            name: Schema name to validate

        Returns:
            The validated schema name

        Raises:
            ValueError: If schema name is invalid
        """
        if not validate_schema_name(name):
            raise ValueError(
                f"Invalid schema name '{name}'. Must start with lowercase letter "
                "and contain only lowercase letters, numbers, and underscores."
            )
        return name

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        Get a session with search_path set to this schema.

        This is a context manager that automatically handles commit on success,
        rollback on exception, and close on exit.

        Yields:
            SQLAlchemy session configured for this schema

        Raises:
            Exception: Re-raises any exception after rollback

        Example:
            >>> with scoped.session() as session:
            ...     result = session.execute(text("SELECT * FROM my_table"))
            ...     # Commits automatically on success
        """
        session: Session = self._pg.session()
        try:
            session.execute(
                text(f'SET LOCAL search_path TO "{self._schema_name}", public')
            )
            yield session
            session.commit()
        except Exception as e:
            self._lg.warning("session rollback", extra={"exception": e})
            session.rollback()
            raise
        finally:
            session.close()

    def ensure_schema(self) -> None:
        """
        Create the PostgreSQL schema if it doesn't exist.

        This is idempotent - safe to call multiple times.

        Raises:
            DatabaseError: If parent PG is in readonly mode

        Example:
            >>> scoped = pg.scoped("my_schema")
            >>> scoped.ensure_schema()  # CREATE SCHEMA IF NOT EXISTS
        """
        if self._pg.readonly:
            raise DatabaseError(
                f"Cannot create schema '{self._schema_name}': PG is readonly",
                schema=self._schema_name,
            )
        with self._pg.engine.connect() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{self._schema_name}"'))
            conn.commit()
        self._lg.trace("ensured schema exists", extra={"schema": self._schema_name})

    @property
    def schema(self) -> str:
        """Get the schema name for this scope."""
        return self._schema_name

    @property
    def engine(self) -> Engine:
        """Get the underlying SQLAlchemy engine."""
        return self._pg.engine
