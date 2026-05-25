"""
Pytest fixtures for PostgreSQL integration testing.

This module provides fixtures for testing against a real PostgreSQL database.
It includes automatic debug table management:
- Tables are created with timestamps for isolation
- Tables are kept on test failure for debugging
- Tables are cleaned up on test success

Usage:
    import pytest

    @pytest.mark.integration
    def test_my_database_operation(pg_session, pg_debug_table):
        # Insert data
        pg_session.execute(
            f"INSERT INTO {pg_debug_table} (id, name) VALUES (1, 'test')"
        )
        pg_session.commit()

        # Test assertions
        result = pg_session.execute(f"SELECT COUNT(*) FROM {pg_debug_table}")
        assert result.fetchone()[0] == 1
"""

import logging
import os
import sys
import threading
import time
from pathlib import Path

import pytest

# Thread-safe counter for unique table names in parallel execution
_table_counter = 0
_table_counter_lock = threading.Lock()

# Import required infra modules
from appinfra.config import Config
from appinfra.db.pg.pg import PG
from appinfra.log.config import LogConfig
from appinfra.log.factory import LoggerFactory
from tests.helpers.pg.probe import PG_SKIP_REASON, PG_STATUS_KEY

# =============================================================================
# Configuration and Connection Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def pg_config():
    """
    Load PostgreSQL configuration from appinfra.yaml.

    Returns:
        Database configuration from dbs.unittest section

    Raises:
        pytest.skip: If configuration or database section not found
    """
    try:
        # Find project root by looking for etc/infra.yaml
        current_path = Path(__file__)
        for parent in current_path.parents:
            config_path = parent / "etc" / "infra.yaml"
            if config_path.exists():
                break
        else:
            pytest.skip("Could not find etc/infra.yaml in parent directories")

        # Load configuration
        config = Config(str(config_path))
        test_config = config.get("dbs.unittest")

        if not test_config:
            pytest.skip("Database configuration 'unittest' not found in dbs section")

        return test_config

    except Exception as e:
        pytest.skip(f"Failed to load database configuration: {e}")


@pytest.fixture(scope="session")
def pg_logger():
    """
    Create a logger for PostgreSQL integration tests.

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
def pg_available(request) -> bool:
    """
    Return the session-level PG reachability flag stashed by conftest's
    pytest_configure hook. (One probe per session, shared by all consumers.)
    """
    status = request.config.stash.get(PG_STATUS_KEY, None)
    return bool(status and status["available"])


@pytest.fixture(scope="session")
def pg_connection(pg_config, pg_logger, pg_available):
    """
    Create a PostgreSQL connection for the test session.

    This fixture provides a PG instance that's shared across all tests
    in the session. The connection is automatically closed after all tests complete.

    Args:
        pg_config: Database configuration fixture
        pg_logger: Logger fixture
        pg_available: Session-level PG reachability probe

    Yields:
        PG instance with active connection

    Raises:
        pytest.skip: With the uniform sentinel reason if PG is unreachable,
            so terminal_summary can collapse all DB-skipped tests into one banner.
    """
    if not pg_available:
        pytest.skip(PG_SKIP_REASON)

    # Narrow try/except to connection setup only: an exception here means the
    # DB isn't usable → skip. Letting `yield` run inside this except block
    # would silently convert genuine test failures into skips.
    try:
        pg = PG(pg_logger, pg_config)
        conn = pg.connect()
        conn.close()
    except Exception as e:
        # Probe said port was open but real connect failed (auth/role/DB-name).
        # Surface the cause so the developer doesn't see a bare "pg-unavailable".
        print(
            f"warning: PG probe passed but pg_connection setup failed ({e!r})",
            file=sys.stderr,
        )
        pytest.skip(PG_SKIP_REASON)

    yield pg


def _do_cleanup_stale_tables(pg_connection):
    """Execute the actual cleanup of stale debug tables."""
    import sqlalchemy

    try:
        with pg_connection.session() as session:
            result = session.execute(
                sqlalchemy.text(
                    """
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public'
                    AND tablename ~ '_[0-9]{10}_'
                    """
                )
            )
            tables = [row[0] for row in result.fetchall()]

            for table in tables:
                session.execute(
                    sqlalchemy.text(f'DROP TABLE IF EXISTS "{table}" CASCADE')
                )

            if tables:
                logging.info(
                    f"Cleaned up {len(tables)} stale debug tables from previous runs"
                )
    except Exception as e:
        logging.warning(f"Failed to clean up stale debug tables: {e}")


@pytest.fixture(scope="session", autouse=True)
def pg_cleanup_stale_debug_tables(pg_available, worker_id, request):
    """
    Clean up all debug tables from previous test runs at session start.

    When running with pytest-xdist, cleanup only runs on the master process
    (worker_id="master") to avoid race conditions where one worker might
    drop tables that another worker just created.

    If PG is unreachable, no-op silently so non-PG tests can still run — only
    tests that directly request pg_connection/pg_session etc. will be skipped.

    Note: pg_connection is *not* a declared parameter on purpose. Requesting it
    declaratively would cause its pytest.skip(PG_SKIP_REASON) to propagate from
    this autouse session fixture to every test in the run. Instead, we fetch it
    lazily via request.getfixturevalue() and catch the skip exception locally.

    Args:
        pg_available: Session-level PG reachability probe
        worker_id: pytest-xdist worker ID ("master" when not using xdist)
        request: pytest request object (used to lazily fetch pg_connection)
    """
    if not pg_available:
        return
    # Only run cleanup on master to avoid race conditions with xdist workers
    # Each xdist worker gets its own "session", but they share the same database
    if worker_id != "master":
        return

    # Probe said PG was reachable, but the actual connect inside pg_connection
    # may still fail (auth/role/DB-name mismatch). Catch its pytest.skip here so
    # the autouse session fixture does not cascade-skip every test in the run.
    try:
        pg_connection = request.getfixturevalue("pg_connection")
    except pytest.skip.Exception:
        return
    _do_cleanup_stale_tables(pg_connection)


@pytest.fixture
def pg_config_ro():
    """
    Load PostgreSQL read-only configuration from appinfra.yaml.

    Returns:
        Database configuration from dbs.unittest_ro section

    Raises:
        pytest.skip: If configuration or database section not found
    """
    try:
        # Find project root by looking for etc/infra.yaml
        current_path = Path(__file__)
        for parent in current_path.parents:
            config_path = parent / "etc" / "infra.yaml"
            if config_path.exists():
                break
        else:
            pytest.skip("Could not find etc/infra.yaml in parent directories")

        # Load configuration
        config = Config(str(config_path))
        test_config = config.get("dbs.unittest_ro")

        if not test_config:
            pytest.skip("Database configuration 'unittest_ro' not found in dbs section")

        return test_config

    except Exception as e:
        pytest.skip(f"Failed to load readonly database configuration: {e}")


@pytest.fixture
def pg_connection_ro(pg_config_ro, pg_logger, pg_available):
    """
    Create a read-only PostgreSQL connection for the test session.

    This fixture provides a PG instance in readonly mode that's shared
    across all tests in the session.

    Args:
        pg_config_ro: Read-only database configuration fixture
        pg_logger: Logger fixture
        pg_available: Session-level PG reachability probe

    Yields:
        PG instance with readonly connection

    Raises:
        pytest.skip: With the uniform sentinel reason if PG is unreachable.
    """
    if not pg_available:
        pytest.skip(PG_SKIP_REASON)

    # Narrow try/except to connection setup only: an exception here means the
    # readonly DB isn't usable → skip. Letting `yield` run inside this except
    # block would silently convert genuine test failures into skips.
    try:
        pg = PG(pg_logger, pg_config_ro)
        conn = pg.connect()
        conn.close()
    except Exception as e:
        print(
            f"warning: PG probe passed but pg_connection_ro setup failed ({e!r})",
            file=sys.stderr,
        )
        pytest.skip(PG_SKIP_REASON)

    try:
        yield pg
    finally:
        dispose_ro_engine(pg)


def dispose_ro_engine(pg):
    """Remove RO-mode event listeners and dispose the engine to prevent hanging."""
    if not (hasattr(pg, "_engine") and pg._engine is not None):
        return
    import sqlalchemy

    if hasattr(pg, "_readonly_listener"):
        sqlalchemy.event.remove(pg._engine, "begin", pg._readonly_listener)
    if hasattr(pg, "_after_execute_listener"):
        sqlalchemy.event.remove(pg._engine, "after_execute", pg._after_execute_listener)
    if hasattr(pg, "_before_cursor_listener"):
        sqlalchemy.event.remove(
            pg._engine, "before_cursor_execute", pg._before_cursor_listener
        )
    pg._engine.dispose()


@pytest.fixture
def pg_session_ro(pg_connection_ro, request):
    """
    Create a read-only database session for a single test.

    This fixture provides a fresh readonly session for each test.
    The session is rolled back on test failure, committed on success,
    and always closed after the test completes.

    Args:
        pg_connection_ro: Read-only PG connection fixture
        request: pytest request fixture for test outcome detection

    Yields:
        SQLAlchemy session (readonly mode)
    """
    session = pg_connection_ro._create_session()
    try:
        yield session
    finally:
        failed = getattr(request.node, "rep_call", None)
        if failed is not None and failed.failed:
            session.rollback()
        else:
            session.commit()
        session.close()


# =============================================================================
# Session and Debug Table Fixtures
# =============================================================================


@pytest.fixture
def pg_session(pg_connection, request):
    """
    Create a database session for a single test.

    This fixture provides a fresh session for each test. The session
    is rolled back on test failure, committed on success, and always
    closed after the test completes.

    Args:
        pg_connection: PG connection fixture
        request: pytest request fixture for test outcome detection

    Yields:
        SQLAlchemy session
    """
    session = pg_connection._create_session()
    try:
        yield session
    finally:
        failed = getattr(request.node, "rep_call", None)
        if failed is not None and failed.failed:
            session.rollback()
        else:
            session.commit()
        session.close()


def _cleanup_debug_table(request, pg_session, table_name):
    """Cleanup debug table based on test outcome."""
    test_failed = (
        request.node.rep_call.failed if hasattr(request.node, "rep_call") else False
    )

    if test_failed:
        logging.info(
            f"🐛 Keeping table '{table_name}' for debugging (test failed). "
            f"Inspect with: SELECT * FROM {table_name};"
        )
    else:
        try:
            import sqlalchemy

            pg_session.execute(
                sqlalchemy.text(f"DROP TABLE IF EXISTS {table_name} CASCADE")
            )
            pg_session.commit()
            logging.info(f"✅ Cleaned up table '{table_name}' after successful test")
        except Exception as e:
            logging.warning(f"⚠️  Failed to clean up table '{table_name}': {e}")


@pytest.fixture
def pg_debug_table(request, pg_session):
    """
    Create a debug table for testing with automatic cleanup.

    This fixture:
    - Creates a unique table name safe for parallel execution
    - Persists the table if the test fails (for debugging)
    - Cleans up the table if the test passes

    The table is created automatically, and cleanup is handled based on
    test outcome.

    Args:
        request: Pytest request object (for test outcome detection)
        pg_session: Database session fixture

    Yields:
        str: Table name (e.g., "test_my_feature_1234567890_gw0_1")
    """
    table_name = _generate_debug_table_name(request)

    yield table_name

    _cleanup_debug_table(request, pg_session, table_name)


def _generate_debug_table_name(request):
    """Generate unique debug table name safe for parallel execution.

    Uses timestamp + pid + counter to ensure uniqueness across:
    - Multiple test runs (timestamp)
    - Parallel workers (each xdist worker is a separate process with unique PID)
    - Same process, same second (atomic counter)
    """
    global _table_counter

    test_name = request.node.name
    clean_name = "".join(c if c.isalnum() or c == "_" else "_" for c in test_name)
    clean_name = clean_name[:40]  # Shorter to fit additional suffixes

    timestamp = int(time.time())
    pid = os.getpid()

    # Atomic counter increment
    with _table_counter_lock:
        _table_counter += 1
        counter = _table_counter

    return f"{clean_name}_{timestamp}_{pid}_{counter}"


def _cleanup_debug_table_with_schema(request, pg_session, table_name):
    """Cleanup debug table based on test outcome."""
    test_failed = (
        request.node.rep_call.failed if hasattr(request.node, "rep_call") else False
    )

    if test_failed:
        logging.info(f"🐛 Keeping table '{table_name}' for debugging")
    else:
        try:
            import sqlalchemy

            pg_session.execute(
                sqlalchemy.text(f"DROP TABLE IF EXISTS {table_name} CASCADE")
            )
            pg_session.commit()
            logging.info(f"✅ Cleaned up table '{table_name}'")
        except Exception as e:
            logging.warning(f"⚠️  Failed to clean up table '{table_name}': {e}")


@pytest.fixture
def pg_debug_table_with_schema(request, pg_session):
    """
    Create a debug table with a custom schema.

    This fixture creates a table with the provided schema and handles
    cleanup based on test outcome (just like pg_debug_table).

    Args:
        request: Pytest request object
        pg_session: Database session fixture

    Yields:
        tuple: (table_name, create_table_function)
            table_name: Name of the debug table
            create_table_function: Function to create table with custom schema
    """
    table_name = _generate_debug_table_name(request)

    def create_table(schema: str):
        """Create table with custom schema."""
        import sqlalchemy

        pg_session.execute(sqlalchemy.text(f"CREATE TABLE {table_name} ({schema})"))
        pg_session.commit()

    yield table_name, create_table

    _cleanup_debug_table_with_schema(request, pg_session, table_name)


# =============================================================================
# Pytest Hooks for Test Outcome Detection
# =============================================================================


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Hook to capture test outcomes for cleanup decisions.

    This hook stores the test outcome on the test item so that fixtures
    can access it during teardown to decide whether to keep or clean up
    debug tables.
    """
    outcome = yield
    rep = outcome.get_result()

    # Store test reports for each phase
    setattr(item, f"rep_{rep.when}", rep)


# =============================================================================
# Utility Fixtures
# =============================================================================


@pytest.fixture
def pg_cleanup_tables(pg_session):
    """
    Manually cleanup specified tables.

    This fixture provides a cleanup function that can be used to
    manually drop tables during or after tests.

    Args:
        pg_session: Database session fixture

    Yields:
        function: Cleanup function that accepts table names

    Example:
        def test_with_cleanup(pg_session, pg_cleanup_tables):
            # Create tables
            pg_session.execute("CREATE TABLE temp1 (id INT)")
            pg_session.execute("CREATE TABLE temp2 (id INT)")

            # Do test stuff...

            # Manually cleanup
            pg_cleanup_tables("temp1", "temp2")
    """

    def cleanup(*table_names):
        """Drop specified tables."""
        import sqlalchemy

        for table_name in table_names:
            try:
                pg_session.execute(
                    sqlalchemy.text(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                )
                pg_session.commit()
                logging.info(f"✅ Cleaned up table '{table_name}'")
            except Exception as e:
                logging.warning(f"⚠️  Failed to clean up table '{table_name}': {e}")

    yield cleanup


@pytest.fixture
def pg_list_debug_tables(pg_session):
    """
    List all debug tables in the database.

    This fixture provides a function to list all tables that look like
    debug tables (have timestamps in their names).

    Args:
        pg_session: Database session fixture

    Yields:
        function: Function that returns list of debug table names

    Example:
        def test_check_tables(pg_list_debug_tables):
            tables = pg_list_debug_tables()
            print(f"Found {len(tables)} debug tables")
    """

    def list_tables():
        """List all tables in public schema that look like debug tables."""
        import sqlalchemy

        result = pg_session.execute(
            sqlalchemy.text(
                """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename ~ '_[0-9]{10}_'
            ORDER BY tablename
        """
            )
        )
        return [row[0] for row in result.fetchall()]

    yield list_tables
