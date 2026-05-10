"""
PostgreSQL schema isolation support.

Provides schema-level isolation for parallel test execution and multi-tenant applications.
Each PG instance can be configured to use a specific schema, with all queries automatically
routed to that schema via search_path.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import event, text
from sqlalchemy.engine import Engine

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import DeclarativeBase

    from ...log import Logger


# Schema name validation pattern - must be a valid SQL identifier
_SCHEMA_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_schema_name(name: str) -> bool:
    """
    Validate that a schema name is a safe SQL identifier.

    Args:
        name: Schema name to validate

    Returns:
        True if valid, False otherwise
    """
    return bool(_SCHEMA_NAME_PATTERN.match(name))


class SchemaManager:
    """
    Manages PostgreSQL schema isolation.

    Installs SQLAlchemy event listeners to set search_path on all connections,
    ensuring queries are routed to the correct schema.

    Example:
        >>> from appinfra.db.pg import PG
        >>> pg = PG(logger, config, schema="test_gw0")
        >>> # All queries now use schema test_gw0
    """

    def __init__(self, engine: Engine, schema: str, logger: Logger) -> None:
        """
        Initialize the schema manager.

        Args:
            engine: SQLAlchemy engine instance
            schema: PostgreSQL schema name
            logger: Logger instance

        Raises:
            ValueError: If schema name is invalid
        """
        if not validate_schema_name(schema):
            raise ValueError(
                f"Invalid schema name '{schema}'. Must start with lowercase letter "
                "and contain only lowercase letters, numbers, and underscores."
            )

        self._engine = engine
        self._schema = schema
        self._lg = logger
        # Include public in search_path for extension visibility (e.g., pgvector)
        self._search_path = f"{schema}, public"
        self._listeners_installed = False

    @property
    def schema(self) -> str:
        """Get the configured schema name."""
        return self._schema

    @property
    def search_path(self) -> str:
        """Get the configured search_path."""
        return self._search_path

    def setup_listeners(self) -> None:
        """Install event listeners to set search_path on all connections."""
        if self._listeners_installed:
            return

        # Quote schema for reserved word safety (consistent with CREATE SCHEMA)
        set_path_sql = f'SET search_path TO "{self._schema}", public'

        @event.listens_for(self._engine, "connect")
        def _on_connect(dbapi_conn: Any, connection_record: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute(set_path_sql)
            cursor.close()

        self._connect_listener = _on_connect
        self._listeners_installed = True
        self._lg.debug(
            "installed schema listeners",
            extra={"schema": self._schema, "search_path": self._search_path},
        )

    def remove_listeners(self) -> None:
        """Remove event listeners (for cleanup)."""
        if not self._listeners_installed:
            return

        if hasattr(self, "_connect_listener"):
            event.remove(self._engine, "connect", self._connect_listener)

        self._listeners_installed = False
        self._lg.debug("removed schema listeners", extra={"schema": self._schema})

    def create_schema(self) -> None:
        """Create the schema if it doesn't exist."""
        with self._engine.connect() as conn:
            # Use identifier quoting for safety (name already validated)
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{self._schema}"'))
            conn.commit()

        self._lg.debug("created schema", extra={"schema": self._schema})

    def drop_schema(self, cascade: bool = True) -> None:
        """
        Drop the schema if it exists.

        Args:
            cascade: If True, drop all objects in the schema (default: True)
        """
        cascade_sql = "CASCADE" if cascade else ""
        with self._engine.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{self._schema}" {cascade_sql}'))
            conn.commit()

        self._lg.debug(
            "dropped schema", extra={"schema": self._schema, "cascade": cascade}
        )

    def reset_schema(self) -> None:
        """Drop and recreate the schema for fresh state."""
        self.drop_schema(cascade=True)
        self.create_schema()
        self._lg.debug("reset schema", extra={"schema": self._schema})


def create_all_in_schema(base: DeclarativeBase, engine: Engine, schema: str) -> None:
    """
    Create tables in a specific schema.

    SQLAlchemy's create_all() doesn't respect search_path for DDL operations.
    It checks if tables exist before creating, and with 'public' in search_path,
    it may find existing tables and skip creation.

    This function works around that by temporarily setting the schema attribute
    on all tables before create_all(), then restoring them so queries use
    search_path.

    Args:
        base: SQLAlchemy declarative base with table definitions
        engine: SQLAlchemy engine instance
        schema: Target schema name

    Raises:
        ValueError: If schema name is invalid
    """
    if not validate_schema_name(schema):
        raise ValueError(
            f"Invalid schema name '{schema}'. Must start with lowercase letter "
            "and contain only lowercase letters, numbers, and underscores."
        )

    # Store original schemas and temporarily set target schema
    original_schemas: dict[Any, str | None] = {}

    for table in base.metadata.tables.values():
        original_schemas[table] = table.schema
        table.schema = schema

    try:
        base.metadata.create_all(engine)
    finally:
        # Restore original schemas so queries use search_path
        for table, original_schema in original_schemas.items():
            table.schema = original_schema
