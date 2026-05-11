"""
SQLite database interface implementation.

Provides a SQLite database interface with SQLAlchemy integration.
Simpler than PostgreSQL - no connection pooling, reconnection, or
advanced features needed for file-based databases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy
import sqlalchemy.orm

from ...log import Logger, LoggerFactory
from ..pg.interface import Interface

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session


def _validate_sqlite_config(cfg: Any) -> None:
    """Validate SQLite configuration."""
    if cfg is None:
        raise ValueError("Configuration cannot be None")

    if not hasattr(cfg, "url") or not cfg.url:
        raise ValueError("Configuration missing required 'url' field")

    url = cfg.url
    if not url.startswith("sqlite"):
        raise ValueError(f"Invalid SQLite URL: {url}")


def _get_engine_kwargs(cfg: Any) -> dict[str, Any]:
    """Get engine creation kwargs from config."""
    kwargs: dict[str, Any] = {}

    # SQLite-specific: check_same_thread for multi-threaded access
    if hasattr(cfg, "check_same_thread"):
        kwargs["connect_args"] = {"check_same_thread": cfg.check_same_thread}
    else:
        # Default: allow multi-threaded access (common for web apps)
        kwargs["connect_args"] = {"check_same_thread": False}

    # Echo SQL statements if configured
    if hasattr(cfg, "echo") and cfg.echo:
        kwargs["echo"] = True

    return kwargs


class SQLite(Interface):
    """
    SQLite database interface implementation.

    Provides a SQLite database interface with SQLAlchemy integration.
    Designed for:
    - Fast unit tests (in-memory or file-based)
    - Simple applications that don't need PostgreSQL
    - Local development

    Example:
        >>> from appinfra.db.sqlite import SQLite
        >>>
        >>> # In-memory database for tests
        >>> db_config = {"url": "sqlite:///:memory:"}
        >>> sqlite = SQLite(logger, db_config)
        >>>
        >>> # File-based database
        >>> db_config = {"url": "sqlite:///./data.db"}
        >>> sqlite = SQLite(logger, db_config)
    """

    def __init__(self, lg: Logger, cfg: Any) -> None:
        """
        Initialize the SQLite database interface.

        Args:
            lg: Logger instance for database operations
            cfg: Database configuration object with 'url' field
        """
        if lg is None:
            raise ValueError("Logger cannot be None")

        _validate_sqlite_config(cfg)

        self._cfg = cfg
        self._lg = LoggerFactory.derive(lg, "sqlite")

        # Create engine and session factory
        engine_kwargs = _get_engine_kwargs(cfg)
        self._engine: Engine = sqlalchemy.create_engine(cfg.url, **engine_kwargs)
        self._SessionCls = sqlalchemy.orm.sessionmaker(bind=self._engine)

        self._lg.debug("initialized", extra={"url": self._safe_url})

    @property
    def _safe_url(self) -> str:
        """Get URL safe for logging (no credentials)."""
        return str(self._engine.url)

    @property
    def cfg(self) -> Any:
        """Get the database configuration."""
        return self._cfg

    @property
    def url(self) -> str:
        """Get the database URL."""
        return str(self._engine.url)

    @property
    def engine(self) -> Engine:
        """Get the SQLAlchemy engine."""
        return self._engine

    def connect(self) -> Any:
        """
        Establish a connection to the SQLite database.

        Returns:
            Database connection object
        """
        return self._engine.connect()

    def migrate(self, base: Any) -> None:  # type: ignore[override]
        """
        Run database migrations using SQLAlchemy metadata.

        Creates all tables defined in the metadata if they don't exist.

        Args:
            base: SQLAlchemy declarative base with metadata
        """
        base.metadata.create_all(self._engine)
        self._lg.debug("migrated schema")

    def session(self, autocommit: bool = False) -> Session:  # noqa: ARG002
        """
        Create a new database session.

        Args:
            autocommit: Ignored for SQLite (included for interface compatibility).

        Returns:
            Database session instance
        """
        return self._SessionCls()

    def dispose(self) -> None:
        """Dispose of the engine and close all connections."""
        self._engine.dispose()
        self._lg.debug("disposed engine")
