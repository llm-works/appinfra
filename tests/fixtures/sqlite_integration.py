"""
Pytest fixtures for SQLite integration testing.

This module provides fixtures for testing with SQLite in-memory databases.
Useful for tests that need real SQL execution but don't require
PostgreSQL-specific features (JSONB, pgvector, connection pooling, etc.).

SQLite fixtures are faster than PostgreSQL fixtures because:
- No external database server needed
- In-memory database (no disk I/O)
- No connection pool overhead

Usage:
    import pytest

    @pytest.mark.unit
    def test_basic_crud(sqlite_session, sqlite_table):
        from sqlalchemy import text

        # Create table
        sqlite_session.execute(text(f'''
            CREATE TABLE {sqlite_table} (
                id INTEGER PRIMARY KEY,
                name TEXT
            )
        '''))

        # Insert data
        sqlite_session.execute(text(f'''
            INSERT INTO {sqlite_table} (id, name) VALUES (1, 'test')
        '''))
        sqlite_session.commit()

        # Verify
        result = sqlite_session.execute(text(f'SELECT COUNT(*) FROM {sqlite_table}'))
        assert result.fetchone()[0] == 1
"""

import uuid

import pytest

from appinfra.db.sqlite import SQLite
from appinfra.log.config import LogConfig
from appinfra.log.factory import LoggerFactory

# =============================================================================
# Configuration and Connection Fixtures
# =============================================================================


class _SQLiteConfig:
    """Simple config object for SQLite."""

    def __init__(self, url: str = "sqlite:///:memory:"):
        self.url = url


@pytest.fixture(scope="session")
def sqlite_logger():
    """
    Create a logger for SQLite integration tests.

    Returns:
        Logger instance configured for testing
    """
    log_config = LogConfig.from_params(
        level="debug",
        location=0,
        micros=False,
        colors=False,
    )
    return LoggerFactory.create_root(log_config)


@pytest.fixture(scope="session")
def sqlite_connection(sqlite_logger):
    """
    Create a SQLite in-memory connection for the test session.

    This fixture provides a SQLite instance that's shared across all tests
    in the session. Uses in-memory database for speed.

    Note: In-memory SQLite with check_same_thread=False allows sharing
    across pytest workers while maintaining isolation.

    Args:
        sqlite_logger: Logger fixture

    Yields:
        SQLite instance with in-memory database
    """
    config = _SQLiteConfig("sqlite:///:memory:")
    sqlite = SQLite(sqlite_logger, config)
    yield sqlite
    sqlite.dispose()


# =============================================================================
# Session and Table Fixtures
# =============================================================================


@pytest.fixture
def sqlite_session(sqlite_connection):
    """
    Create a database session for a single test.

    This fixture provides a fresh session for each test. The session
    is automatically committed on success, rolled back on exception,
    and closed after the test completes.

    Args:
        sqlite_connection: SQLite connection fixture

    Yields:
        SQLAlchemy session
    """
    with sqlite_connection.session() as session:
        yield session


@pytest.fixture
def sqlite_table(sqlite_session):
    """
    Generate a unique table name for testing.

    This fixture provides a unique table name and automatically
    drops the table after the test completes.

    Unlike PostgreSQL debug tables, SQLite tables are always cleaned up
    since the in-memory database doesn't persist for debugging anyway.

    Args:
        sqlite_session: Database session fixture

    Yields:
        str: Unique table name (e.g., "test_a1b2c3d4")
    """
    from sqlalchemy import text

    table_name = f"test_{uuid.uuid4().hex[:8]}"

    yield table_name

    # Always cleanup - in-memory DB doesn't persist anyway
    try:
        sqlite_session.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        sqlite_session.commit()
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture
def sqlite_table_with_schema(sqlite_session):
    """
    Create a table with a custom schema.

    This fixture provides a table name and a function to create
    the table with a custom schema.

    Args:
        sqlite_session: Database session fixture

    Yields:
        tuple: (table_name, create_table_function)

    Example:
        def test_custom_schema(sqlite_table_with_schema, sqlite_session):
            table_name, create_table = sqlite_table_with_schema
            create_table("id INTEGER PRIMARY KEY, data TEXT, score REAL")

            # Use the table...
    """
    from sqlalchemy import text

    table_name = f"test_{uuid.uuid4().hex[:8]}"

    def create_table(schema: str):
        """Create table with custom schema."""
        sqlite_session.execute(text(f"CREATE TABLE {table_name} ({schema})"))
        sqlite_session.commit()

    yield table_name, create_table

    # Always cleanup
    try:
        sqlite_session.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        sqlite_session.commit()
    except Exception:
        pass
