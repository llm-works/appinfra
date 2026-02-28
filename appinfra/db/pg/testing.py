"""
Pytest fixtures for PostgreSQL testing with schema isolation.

This module provides turnkey fixtures for parallel test execution with pytest-xdist.
Each worker gets an isolated PostgreSQL schema (e.g., test_gw0, test_gw1), preventing
race conditions when tests share the same database.

Usage (minimal - one line in conftest.py):
    pytest_plugins = ["appinfra.db.pg.testing"]

Usage (with migrations - recommended):
    # conftest.py - no import needed, avoids PytestAssertRewriteWarning
    pytest_plugins = ["appinfra.db.pg.testing"]

    @pytest.fixture(scope="session")
    def pg_with_tables(pg_migrate_factory):
        with pg_migrate_factory(Base, extensions=["vector"]) as pg:
            yield pg

Usage (with migrations - legacy, causes warning):
    from myapp.models import Base
    from appinfra.db.pg.testing import make_migrate_fixture

    pytest_plugins = ["appinfra.db.pg.testing"]

    pg_with_tables = make_migrate_fixture(Base)

The fixtures expect the following environment or configuration:
- pg_test_config fixture (user-provided): Returns database configuration dict
- pg_test_logger fixture (user-provided): Returns Logger instance

If these fixtures are not provided, default implementations will be used that
read from environment variables (APPINFRA_TEST_PG_URL) or skip the tests.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from sqlalchemy.orm import DeclarativeBase

    from ...log import Logger
    from .pg import PG


# =============================================================================
# Helpers
# =============================================================================

# Extension name validation pattern (same as PG class)
_EXT_PATTERN = __import__("re").compile(r"^[a-z][a-z0-9_-]*$")


def _create_extensions_in_db(url: str, extensions: list[str]) -> None:
    """Create PostgreSQL extensions in the target database."""
    import sqlalchemy
    from sqlalchemy import text

    if not extensions:
        return

    engine = sqlalchemy.create_engine(url)
    try:
        with engine.connect() as conn:
            for ext in extensions:
                if _EXT_PATTERN.match(ext):
                    conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))
            conn.commit()
    finally:
        engine.dispose()


def _setup_database_with_lock(config: dict[str, Any]) -> None:
    """
    Set up database and extensions with advisory lock coordination.

    Connects to the 'postgres' database to acquire an advisory lock,
    then creates the target database and extensions if needed.
    This prevents race conditions with pytest-xdist workers.
    """
    import hashlib
    from urllib.parse import urlparse

    import sqlalchemy
    import sqlalchemy_utils
    from sqlalchemy import text

    if not config.get("create_db"):
        return

    url = config["url"]
    parsed = urlparse(url)
    db_name = parsed.path.lstrip("/")
    postgres_url = url.replace(f"/{db_name}", "/postgres")
    lock_id = int(hashlib.md5(db_name.encode()).hexdigest()[:15], 16)

    engine = sqlalchemy.create_engine(postgres_url)
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SELECT pg_advisory_lock({lock_id})"))
            try:
                if not sqlalchemy_utils.database_exists(url):
                    sqlalchemy_utils.create_database(url)
                _create_extensions_in_db(url, config.get("extensions", []))
            finally:
                conn.execute(text(f"SELECT pg_advisory_unlock({lock_id})"))
                conn.commit()
    finally:
        engine.dispose()


# =============================================================================
# Core Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def pg_test_schema(worker_id: str) -> str:
    """
    Generate a unique schema name for the current test worker.

    When running with pytest-xdist, each worker gets a unique schema
    (test_gw0, test_gw1, etc.). When running without xdist, uses 'test_master'.

    Args:
        worker_id: pytest-xdist worker ID ("master" when not using xdist,
            "gw0", "gw1", etc. when using xdist)

    Returns:
        Schema name (e.g., "test_gw0" or "test_master")
    """
    if worker_id == "master":
        return "test_master"
    return f"test_{worker_id}"


@pytest.fixture(scope="session")
def pg_test_config() -> dict[str, Any]:
    """
    Provide database configuration for testing.

    Override this fixture in your conftest.py to provide custom configuration.
    Default implementation reads from APPINFRA_TEST_PG_URL environment variable.

    Returns:
        Database configuration dict with at least 'url' key

    Raises:
        pytest.skip: If no configuration is available
    """
    import os

    url = os.environ.get("APPINFRA_TEST_PG_URL")
    if not url:
        pytest.skip(
            "APPINFRA_TEST_PG_URL not set. Set this environment variable or "
            "override the pg_test_config fixture in your conftest.py"
        )

    return {"url": url}


@pytest.fixture(scope="session")
def pg_test_logger() -> Logger:
    """
    Provide a logger for testing.

    Override this fixture in your conftest.py to provide custom logger.
    Default implementation creates a debug-level logger.

    Returns:
        Logger instance
    """
    from ...log import LogConfig, LoggerFactory

    log_config = LogConfig.from_params(
        level="debug",
        location=0,
        micros=False,
        colors=False,
    )
    return LoggerFactory.create_root(log_config)


@pytest.fixture(scope="session")
def pg_isolated(
    pg_test_config: dict[str, Any],
    pg_test_logger: Logger,
    pg_test_schema: str,
) -> Generator[PG, None, None]:
    """
    Create a PG instance with schema isolation for the test session.

    This is the main fixture for schema-isolated database access. The schema
    is created at session start and dropped at session end.

    Args:
        pg_test_config: Database configuration
        pg_test_logger: Logger instance
        pg_test_schema: Schema name for isolation

    Yields:
        PG instance configured with schema isolation
    """
    from .pg import PG

    # Set up database and extensions under advisory lock (handles xdist race conditions)
    _setup_database_with_lock(pg_test_config)

    pg = PG(pg_test_logger, pg_test_config, schema=pg_test_schema)

    if pg._schema_mgr:
        pg._schema_mgr.reset_schema()

    yield pg

    # Clean up schema at session end
    if pg._schema_mgr:
        pg._schema_mgr.drop_schema(cascade=True)
        pg._schema_mgr.remove_listeners()


@pytest.fixture
def pg_session_isolated(pg_isolated: PG) -> Generator[Any, None, None]:
    """
    Create a database session with automatic commit/rollback.

    Provides a fresh session for each test. The session is committed on
    success and rolled back on failure.

    Args:
        pg_isolated: Schema-isolated PG instance

    Yields:
        SQLAlchemy session
    """
    session = pg_isolated.session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture
def pg_clean_schema(pg_isolated: PG) -> Generator[PG, None, None]:
    """
    Ensure a completely fresh schema for each test.

    Use this fixture when you need complete isolation between tests
    (drops and recreates the schema before each test).

    Args:
        pg_isolated: Schema-isolated PG instance

    Yields:
        PG instance with freshly reset schema
    """
    if pg_isolated._schema_mgr:
        pg_isolated._schema_mgr.reset_schema()
    yield pg_isolated


# =============================================================================
# Migration Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def pg_migrate_factory(
    pg_test_config: dict[str, Any],
    pg_test_logger: Logger,
    pg_test_schema: str,
) -> Callable[..., Any]:
    """
    Factory for creating schema-isolated PG instances with migrations.

    Returns a context manager factory that handles setup (schema creation,
    migrations) and cleanup (schema drop). This avoids the need to import
    from this module, preventing PytestAssertRewriteWarning.

    Args:
        pg_test_config: Database configuration
        pg_test_logger: Logger instance
        pg_test_schema: Schema name for isolation

    Returns:
        A factory function that creates context managers

    Example:
        # In conftest.py - no import needed
        pytest_plugins = ["appinfra.db.pg.testing"]

        @pytest.fixture(scope="session")
        def pg_with_tables(pg_migrate_factory):
            with pg_migrate_factory(Base, extensions=["vector"]) as pg:
                yield pg

        # In tests
        def test_something(pg_with_tables):
            session = pg_with_tables.session()
            # Tables from Base are available
    """

    @contextmanager
    def _factory(
        base: DeclarativeBase, extensions: list[str] | None = None
    ) -> Generator[PG, None, None]:
        from .pg import PG

        # Merge extensions into config if provided
        config = dict(pg_test_config)
        if extensions is not None:
            config["extensions"] = extensions

        # Set up database and extensions under advisory lock (handles xdist race conditions)
        _setup_database_with_lock(config)

        pg = PG(pg_test_logger, config, schema=pg_test_schema)

        if pg._schema_mgr:
            pg._schema_mgr.reset_schema()

        pg.migrate(base)

        try:
            yield pg
        finally:
            if pg._schema_mgr:
                pg._schema_mgr.drop_schema(cascade=True)
                pg._schema_mgr.remove_listeners()

    return _factory


def make_migrate_fixture(
    base: DeclarativeBase,
    extensions: list[str] | None = None,
) -> Callable[..., Generator[PG, None, None]]:
    """
    Create a fixture that runs migrations before tests.

    Note: This is the legacy approach. Prefer using the `pg_migrate_factory`
    fixture instead to avoid PytestAssertRewriteWarning (importing from this
    module while also using it as a pytest plugin causes the warning).

    This factory function creates a session-scoped fixture that:
    1. Creates a fresh schema
    2. Creates configured extensions
    3. Runs migrations to create all tables

    Args:
        base: SQLAlchemy declarative base with table definitions
        extensions: Optional list of PostgreSQL extensions to create

    Returns:
        A pytest fixture function

    Example (legacy - causes PytestAssertRewriteWarning):
        # In conftest.py
        from myapp.models import Base
        from appinfra.db.pg.testing import make_migrate_fixture

        pg_with_tables = make_migrate_fixture(Base, extensions=["vector"])

    Example (recommended - use pg_migrate_factory instead):
        # In conftest.py - no import needed
        pytest_plugins = ["appinfra.db.pg.testing"]

        @pytest.fixture(scope="session")
        def pg_with_tables(pg_migrate_factory):
            with pg_migrate_factory(Base, extensions=["vector"]) as pg:
                yield pg
    """

    @pytest.fixture(scope="session")
    def _migrate_fixture(
        pg_test_config: dict[str, Any],
        pg_test_logger: Logger,
        pg_test_schema: str,
    ) -> Generator[PG, None, None]:
        from .pg import PG

        config = dict(pg_test_config)  # Copy to avoid mutating fixture
        if extensions is not None:
            config["extensions"] = extensions

        # Set up database and extensions under advisory lock (handles xdist race conditions)
        _setup_database_with_lock(config)

        pg = PG(pg_test_logger, config, schema=pg_test_schema)

        if pg._schema_mgr:
            pg._schema_mgr.reset_schema()
        pg.migrate(base)

        yield pg

        if pg._schema_mgr:
            pg._schema_mgr.drop_schema(cascade=True)
            pg._schema_mgr.remove_listeners()

    return _migrate_fixture


# =============================================================================
# Utility Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def pg_schema_info(pg_isolated: PG) -> dict[str, Any]:
    """
    Get information about the current schema configuration.

    Useful for debugging and verification in tests.

    Args:
        pg_isolated: Schema-isolated PG instance

    Returns:
        Dict with schema information
    """
    return {
        "schema": pg_isolated.schema,
        "search_path": (
            pg_isolated._schema_mgr.search_path if pg_isolated._schema_mgr else None
        ),
        "url": pg_isolated.url,
    }


@pytest.fixture
def assert_table_in_schema(pg_isolated: PG) -> Callable[[str], None]:
    """
    Provide an assertion helper to verify tables are in the correct schema.

    Args:
        pg_isolated: Schema-isolated PG instance

    Returns:
        Assertion function

    Example:
        def test_migration(pg_isolated, assert_table_in_schema):
            pg_isolated.migrate(Base)
            assert_table_in_schema("users")  # Verifies 'users' is in the schema
    """
    from sqlalchemy import text

    def _assert(table_name: str) -> None:
        schema = pg_isolated.schema
        if not schema:
            pytest.fail("No schema configured on pg_isolated fixture")

        with pg_isolated.engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = :schema
                    AND table_name = :table
                    """
                ),
                {"schema": schema, "table": table_name},
            )
            count = result.scalar()
            if count == 0:
                pytest.fail(
                    f"Table '{table_name}' not found in schema '{schema}'. "
                    f"Check that migrations ran correctly."
                )

    return _assert
