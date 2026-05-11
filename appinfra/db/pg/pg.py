"""
PostgreSQL database interface implementation.

Provides a complete PostgreSQL database interface with SQLAlchemy integration,
using composition pattern for clean separation of concerns.
"""

import re
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

import sqlalchemy
import sqlalchemy_utils
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...dot_dict import DotDict
from ...log import Logger, LoggerFactory
from .connection import ConnectionManager
from .core import (
    ConfigValidator,
    QueryLogger,
    configure_readonly_mode,
    initialize_connection_health,
    initialize_logging_context,
    initialize_performance_optimizations,
    validate_init_params,
)
from .interface import Interface
from .reconnection import ReconnectionStrategy
from .session import SessionManager


class PG(Interface):
    """
    PostgreSQL database interface implementation.

    Provides a complete PostgreSQL database interface with SQLAlchemy integration,
    including connection management, query logging, migration support, and
    read-only connection capabilities.

    Uses composition pattern with specialized manager classes for clean
    separation of concerns.

    Example:
        >>> from appinfra.db.pg import PG
        >>> from appinfra.log import LoggerFactory, LogConfig
        >>>
        >>> # Create logger and config
        >>> log_config = LogConfig.from_params(level="info")
        >>> logger = LoggerFactory.create_root(log_config)
        >>> db_config = {"url": "postgresql://user:pass@localhost/mydb"}
        >>>
        >>> # Initialize and use
        >>> pg = PG(logger, db_config)
        >>> with pg.session() as session:
        ...     result = session.execute("SELECT 1")

        >>> # With schema isolation (for parallel testing or multi-tenant)
        >>> pg = PG(logger, db_config, schema="test_gw0")
        >>> pg.create_schema()  # Create schema if needed
        >>> pg.migrate(Base)    # Tables created in test_gw0 schema
    """

    # Type annotations for instance attributes
    _dialect: Any
    _cached_regex: Any
    _whitespace_regex: Any
    _lg_extra: dict[str, Any]
    _query_lg_level: int | bool | None
    _auto_reconnect: bool
    _max_retries: int
    _retry_delay: float
    # Event listener attributes (set conditionally)
    _readonly_listener: Any
    _after_execute_listener: Any
    _before_cursor_listener: Any
    # Lifecycle hooks
    _before_migrate_hooks: list[Callable[[Any], None]]
    _after_migrate_hooks: list[Callable[[Any], None]]
    # Schema isolation (optional)
    _schema_mgr: Any  # SchemaManager | None
    # Scoped PG cache (schema_name -> ScopedPG)
    _scoped_cache: dict[str, "ScopedPG"]

    # Extension name validation pattern (defense-in-depth)
    _EXTENSION_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")

    def __init__(
        self,
        lg: Logger,
        cfg: Any,
        query_lg_level: Any | None = None,
        schema: str | None = None,
    ) -> None:
        """
        Initialize the PostgreSQL database interface.

        Args:
            lg: Logger instance for database operations
            cfg: Database configuration object
            query_lg_level: Log level for query logging (optional)
            schema: PostgreSQL schema for isolation (optional). When set, all
                queries are routed to this schema via search_path. Useful for
                parallel test execution or multi-tenant applications.
        """
        validate_init_params(lg, cfg)

        # Normalize plain dict config to DotDict for attribute access
        if type(cfg) is dict:
            cfg = DotDict(**cfg)

        self._cfg = cfg
        self._lg = LoggerFactory.derive(lg, "pg")

        # Initialize lifecycle hooks
        self._before_migrate_hooks = []
        self._after_migrate_hooks = []

        # Initialize scoped PG cache
        self._scoped_cache = {}

        # Validate and create engine
        ConfigValidator.validate_config(cfg)
        self._create_engine_and_session(cfg)

        # Initialize subsystems
        self._initialize_subsystems(query_lg_level)

        # Create and connect managers
        self._create_managers()
        self._setup_query_logging(query_lg_level)

        # Schema isolation (after engine creation)
        self._initialize_schema_isolation(schema, cfg)

    def _create_engine_and_session(self, cfg: Any) -> None:
        """Create SQLAlchemy engine and session maker."""
        engine_kwargs = ConfigValidator.get_engine_kwargs(cfg)
        self._engine = sqlalchemy.create_engine(self._cfg.url, **engine_kwargs)
        self._SessionCls = sqlalchemy.orm.sessionmaker(bind=self._engine)

    def _initialize_subsystems(self, query_lg_level: Any) -> None:
        """Initialize configuration and tracking subsystems."""
        configure_readonly_mode(self)
        initialize_logging_context(self, query_lg_level)
        initialize_performance_optimizations(self)
        initialize_connection_health(self)

    def _create_managers(self) -> None:
        """Create manager instances and connect them."""
        self._connection_mgr = ConnectionManager(
            self._engine, self._lg, self._cfg, self.readonly
        )
        self._session_mgr = SessionManager(
            self._SessionCls, self._lg, self._auto_reconnect
        )
        self._reconnect_strategy = ReconnectionStrategy(
            self._engine, self._lg, self._max_retries, self._retry_delay
        )
        self._query_logger = QueryLogger(self._engine, self._lg, self._query_lg_level)

        # Connect managers
        self._session_mgr.set_reconnect_strategy(self._reconnect_strategy)
        self._update_logging_context()

    def _setup_query_logging(self, query_lg_level: Any) -> None:
        """Setup query logging callbacks if enabled."""
        if query_lg_level is not None:
            self._query_logger.setup_callbacks(self._lg_extra)

    def _initialize_schema_isolation(self, schema: str | None, cfg: Any) -> None:
        """Initialize schema isolation if configured."""
        self._schema_mgr = None
        # Check parameter first, then config (supports both 'schema' and 'isolation_schema')
        # Use None checks (not truthiness) so empty strings propagate to SchemaManager for validation
        effective_schema = schema
        if effective_schema is None:
            effective_schema = getattr(cfg, "isolation_schema", None)
        if effective_schema is None:
            effective_schema = getattr(cfg, "schema", None)
        # Only use schema if it's a string (handles Mock objects in tests)
        if isinstance(effective_schema, str):
            from .schema import SchemaManager

            self._schema_mgr = SchemaManager(self._engine, effective_schema, self._lg)
            self._schema_mgr.setup_listeners()

    def _update_logging_context(self) -> None:
        """Update logging context on all managers."""
        self._connection_mgr.set_logging_context(self._lg_extra)
        self._session_mgr.set_logging_context(self._lg_extra)
        self._reconnect_strategy.set_logging_context(self._lg_extra)

    @property
    def cfg(self) -> Any:
        """Get the database configuration."""
        return self._cfg

    @property
    def url(self) -> str:
        """Get the database URL."""
        return str(self._engine.url)

    @property
    def readonly(self) -> bool:
        """Check if connection is read-only."""
        return getattr(self._cfg, "readonly", False) is True

    @property
    def engine(self) -> sqlalchemy.engine.Engine:
        """Get the SQLAlchemy engine."""
        return self._engine

    @property
    def schema(self) -> str | None:
        """Get the configured schema name, if any."""
        return self._schema_mgr.schema if self._schema_mgr else None

    def create_schema(self) -> None:
        """
        Create the configured schema if it doesn't exist.

        Only has effect if a schema was configured during initialization.

        Example:
            >>> pg = PG(logger, config, schema="test_gw0")
            >>> pg.create_schema()  # Creates schema if not exists
        """
        if self._schema_mgr:
            self._schema_mgr.create_schema()

    def scoped(self, schema_name: str) -> "ScopedPG":
        """
        Get a scoped PG for a specific schema with its own connection pool.

        Each schema gets a dedicated connection pool with search_path enforced
        at the connection level. ScopedPG instances are cached by schema name
        to avoid creating multiple pools for the same schema.

        Args:
            schema_name: PostgreSQL schema name for the scope

        Returns:
            ScopedPG instance with dedicated pool for the specified schema

        Raises:
            ValueError: If schema name is invalid

        Example:
            >>> pg = PG(logger, config)  # Schema-agnostic
            >>> scoped = pg.scoped("my_schema")
            >>> with scoped.session() as session:
            ...     session.query(MyModel).all()  # Uses my_schema.* tables

            >>> # Multiple scopes from same PG (each gets its own pool)
            >>> scope_a = pg.scoped("schema_a")
            >>> scope_b = pg.scoped("schema_b")
        """
        if schema_name not in self._scoped_cache:
            self._scoped_cache[schema_name] = ScopedPG(self._lg, self, schema_name)
        return self._scoped_cache[schema_name]

    def connect(self) -> Any:
        """
        Establish a connection to the PostgreSQL database.

        Returns:
            Database connection object

        Raises:
            sqlalchemy.exc.SQLAlchemyError: If connection fails

        Example:
            >>> pg = PG(logger, config)
            >>> conn = pg.connect()
            >>> result = conn.execute(sqlalchemy.text("SELECT version()"))
            >>> print(result.fetchone()[0])
            PostgreSQL 15.4 ...
            >>> conn.close()
        """
        return self._connection_mgr.connect()

    def migrate(self, base: Any) -> None:  # type: ignore[override]
        """
        Run database migrations using SQLAlchemy metadata.

        Creates database (if create_db=True), extensions, runs lifecycle hooks,
        and creates all tables defined in the metadata.

        Args:
            base: SQLAlchemy declarative base with metadata

        Example:
            >>> from sqlalchemy.orm import declarative_base
            >>> from sqlalchemy import Column, Integer, String
            >>>
            >>> Base = declarative_base()
            >>>
            >>> class User(Base):
            ...     __tablename__ = "users"
            ...     id = Column(Integer, primary_key=True)
            ...     name = Column(String(100))
            >>>
            >>> pg = PG(logger, config)
            >>> pg.migrate(Base)  # Creates 'users' table if not exists
        """
        # Ensure database exists if create_db is enabled
        create_db = getattr(self._cfg, "create_db", False)
        if create_db is True and not sqlalchemy_utils.database_exists(self._engine.url):
            try:
                sqlalchemy_utils.create_database(self._engine.url)
                self._lg.info("created db", extra=self._lg_extra)
            except Exception:  # pragma: no cover
                # Race condition: another process created it. Verify it exists now.
                if not sqlalchemy_utils.database_exists(self._engine.url):
                    raise

        # Create configured extensions
        self._create_extensions()

        # Run before-migrate hooks
        self._run_hooks(self._before_migrate_hooks, "before_migrate")

        # Create tables (schema-aware if configured)
        if self._schema_mgr:
            from .schema import create_all_in_schema

            # Auto-create schema if it doesn't exist (idempotent, prevents common footgun)
            self._schema_mgr.create_schema()
            create_all_in_schema(base, self._engine, self._schema_mgr.schema)
        else:
            base.metadata.create_all(self._engine)

        # Run after-migrate hooks
        self._run_hooks(self._after_migrate_hooks, "after_migrate")

    def _create_session(self) -> Session:
        """
        Create a raw database session with automatic reconnection if enabled.

        This is an internal method - prefer session() for managed sessions.

        Returns:
            Raw SQLAlchemy session instance
        """
        self._session_mgr.set_connection_health(self._reconnect_strategy.is_healthy())
        session: Session = self._session_mgr.session()
        return session

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        Get a managed database session with automatic commit/rollback.

        Commits on successful exit, rolls back on exception, always closes.

        Yields:
            SQLAlchemy session instance

        Raises:
            sqlalchemy.exc.SQLAlchemyError: If session creation fails

        Example:
            >>> pg = PG(logger, config)
            >>> with pg.session() as session:
            ...     result = session.execute(sqlalchemy.text("SELECT * FROM users"))
            ...     users = result.fetchall()
            ...     # Commits automatically on success
        """
        sa_session = self._create_session()
        try:
            yield sa_session
            sa_session.commit()
        except Exception:
            sa_session.rollback()
            raise
        finally:
            sa_session.close()

    @contextmanager
    def read_session(self) -> Generator[Session, None, None]:
        """
        Get a read-only session with AUTOCOMMIT isolation (no transaction overhead).

        Use for read-only queries where you don't need transaction semantics.
        Avoids BEGIN/COMMIT round-trips for better performance.

        Yields:
            SQLAlchemy session instance

        Example:
            >>> pg = PG(logger, config)
            >>> with pg.read_session() as session:
            ...     result = session.execute(sqlalchemy.text("SELECT * FROM users"))
            ...     users = result.fetchall()
        """
        with self._engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as conn:
            if self._schema_mgr:
                conn.execute(
                    text(f'SET search_path TO "{self._schema_mgr.schema}", public')
                )
            sa_session = Session(bind=conn, expire_on_commit=False)
            try:
                yield sa_session
            finally:
                sa_session.close()

    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the database connection.

        Returns:
            Dictionary with health check results
        """
        return self._connection_mgr.health_check()

    def get_pool_status(self) -> dict[str, Any]:
        """
        Get connection pool status information.

        Returns:
            Dictionary with pool status
        """
        return self._connection_mgr.get_pool_status()

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
        result = self._reconnect_strategy.reconnect(max_retries, initial_delay)
        # Update session manager's health status
        self._session_mgr.set_connection_health(self._reconnect_strategy.is_healthy())
        return result

    # -------------------------------------------------------------------------
    # Lifecycle Hooks
    # -------------------------------------------------------------------------

    def on_before_migrate(
        self, callback: Callable[[Any], None]
    ) -> Callable[[Any], None]:
        """
        Register a callback to run before migration.

        The callback receives a SQLAlchemy connection object and can execute
        custom SQL or setup operations.

        Args:
            callback: Function that accepts a connection object

        Returns:
            The callback (allows use as decorator)

        Example:
            >>> pg = PG(logger, config)
            >>>
            >>> @pg.on_before_migrate
            ... def setup_schema(conn):
            ...     conn.execute(text("CREATE SCHEMA IF NOT EXISTS ml"))
            >>>
            >>> pg.migrate(Base)  # Runs setup_schema before creating tables
        """
        self._before_migrate_hooks.append(callback)
        return callback

    def on_after_migrate(
        self, callback: Callable[[Any], None]
    ) -> Callable[[Any], None]:
        """
        Register a callback to run after migration.

        The callback receives a SQLAlchemy connection object and can execute
        custom SQL or post-migration operations.

        Args:
            callback: Function that accepts a connection object

        Returns:
            The callback (allows use as decorator)

        Example:
            >>> pg = PG(logger, config)
            >>>
            >>> @pg.on_after_migrate
            ... def seed_data(conn):
            ...     conn.execute(text("INSERT INTO settings ..."))
            >>>
            >>> pg.migrate(Base)  # Runs seed_data after creating tables
        """
        self._after_migrate_hooks.append(callback)
        return callback

    # -------------------------------------------------------------------------
    # Extension Management
    # -------------------------------------------------------------------------

    def _create_extensions(self) -> None:
        """Create PostgreSQL extensions configured in the database config."""
        extensions = getattr(self._cfg, "extensions", [])
        if not extensions:
            return

        for ext in extensions:
            # Defense-in-depth validation (also validated by Pydantic schema)
            if not self._is_valid_extension_name(ext):
                self._lg.warning(
                    "skipping invalid extension name",
                    extra={**self._lg_extra, "extension": ext},
                )
                continue

            # Each extension in its own transaction to avoid rollback affecting others
            try:
                with self._engine.connect() as conn:
                    conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))
                    conn.commit()
                self._lg.debug(
                    "created extension",
                    extra={**self._lg_extra, "extension": ext},
                )
            except Exception as e:  # pragma: no cover
                # Race condition: another process created it concurrently.
                # PostgreSQL error code 42710 = duplicate_object (extension exists).
                pgcode = getattr(getattr(e, "orig", None), "pgcode", None)
                if pgcode != "42710":
                    raise

    def _is_valid_extension_name(self, name: str) -> bool:
        """
        Validate extension name is a safe SQL identifier.

        Defense-in-depth check - names should already be validated by Pydantic.
        """
        return bool(self._EXTENSION_NAME_PATTERN.match(name))

    def _run_hooks(self, hooks: list[Callable[[Any], None]], hook_type: str) -> None:
        """Execute lifecycle hooks with a connection."""
        if not hooks:
            return

        with self._engine.connect() as conn:
            for hook in hooks:
                try:
                    hook(conn)
                except Exception:
                    self._lg.exception(
                        "hook failed",
                        extra={**self._lg_extra, "hook_type": hook_type},
                    )
                    raise
            conn.commit()


class ScopedPG:
    """
    PG wrapper scoped to a specific PostgreSQL schema.

    Uses a dedicated connection pool with schema enforced at connection level
    via a connect event listener. All operations (session, read_session)
    consistently use the configured schema.

    Example:
        >>> pg = PG(logger, config)  # Schema-agnostic
        >>> scoped = pg.scoped("my_schema")
        >>> with scoped.session() as session:
        ...     session.query(MyModel).all()  # Uses my_schema.* tables

        >>> # Multiple scopes from same PG (each gets its own pool)
        >>> scope_a = pg.scoped("schema_a")
        >>> scope_b = pg.scoped("schema_b")
    """

    def __init__(self, lg: Logger, parent_pg: PG, schema_name: str) -> None:
        """
        Initialize a scoped PG with dedicated connection pool.

        Args:
            lg: Logger instance
            parent_pg: Parent PG instance (used for config and schema creation)
            schema_name: PostgreSQL schema name for this scope

        Raises:
            ValueError: If schema name is invalid
        """
        from .schema import validate_schema_name

        self._lg = lg
        self._parent_pg = parent_pg

        # Validate schema name
        if not validate_schema_name(schema_name):
            raise ValueError(
                f"Invalid schema name '{schema_name}'. Must start with lowercase letter "
                "and contain only lowercase letters, numbers, and underscores."
            )
        self._schema_name = schema_name

        # Create dedicated PG with own pool, schema enforced at connection level
        self._pg = PG(lg, parent_pg.cfg, schema=schema_name)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        Get a managed session for this schema.

        Commits on success, rolls back on exception, always closes.
        Schema is enforced at connection level via the pool's connect listener.

        Yields:
            SQLAlchemy session configured for this schema

        Example:
            >>> with scoped.session() as session:
            ...     result = session.execute(text("SELECT * FROM my_table"))
            ...     # Commits automatically on success
        """
        with self._pg.session() as session:
            yield session

    @contextmanager
    def read_session(self) -> Generator[Session, None, None]:
        """
        Get a read-only session with AUTOCOMMIT isolation (no transaction overhead).

        Use for read-only queries where you don't need transaction semantics.
        Avoids BEGIN/COMMIT round-trips for better performance.
        Schema is enforced at connection level via the pool's connect listener.

        Yields:
            SQLAlchemy session configured for this schema

        Example:
            >>> with scoped.read_session() as session:
            ...     result = session.execute(text("SELECT * FROM my_table"))
        """
        with self._pg.read_session() as session:
            yield session

    def ensure_schema(self) -> None:
        """
        Create the PostgreSQL schema if it doesn't exist.

        Uses the parent PG's connection to create the schema (avoids
        chicken-and-egg with schema-scoped connections).

        This is idempotent - safe to call multiple times.

        Raises:
            DatabaseError: If parent PG is in readonly mode

        Example:
            >>> scoped = pg.scoped("my_schema")
            >>> scoped.ensure_schema()  # CREATE SCHEMA IF NOT EXISTS
        """
        from ...errors import DatabaseError

        if self._parent_pg.readonly:
            raise DatabaseError(
                f"Cannot create schema '{self._schema_name}': PG is readonly",
                schema=self._schema_name,
            )
        with self._parent_pg.engine.connect() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{self._schema_name}"'))
            conn.commit()
        self._lg.trace("ensured schema exists", extra={"schema": self._schema_name})

    @property
    def schema(self) -> str:
        """Get the schema name for this scope."""
        return self._schema_name

    @property
    def engine(self) -> sqlalchemy.engine.Engine:
        """Get the underlying SQLAlchemy engine (dedicated to this schema)."""
        return self._pg.engine

    @property
    def cfg(self) -> Any:
        """Get the database configuration."""
        return self._pg.cfg
