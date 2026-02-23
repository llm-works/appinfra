"""
Integration tests for the PG class.

These tests verify PG class methods against a real PostgreSQL database,
including connection management, query execution, health checks, and error handling.

Run with:
    ~/.venv/bin/python -m pytest tests/integration/test_pg_class.py -v -s
"""

import pytest
import sqlalchemy
from sqlalchemy import text
from sqlalchemy.orm import declarative_base

from appinfra.db.pg.pg import PG


@pytest.mark.integration
class TestPGConnection:
    """Test PG connection and session management."""

    def test_pg_connect_returns_connection(self, pg_connection):
        """Test that connect() returns a working database connection."""
        conn = pg_connection.connect()
        assert conn is not None

        # Verify we can execute a query
        result = conn.execute(text("SELECT 1 as value"))
        row = result.fetchone()
        assert row[0] == 1

        conn.close()

    def test_pg_session_creation(self, pg_connection):
        """Test that session() creates a working SQLAlchemy session."""
        session = pg_connection.session()
        assert session is not None

        # Execute a simple query
        result = session.execute(text("SELECT 'test' as msg"))
        row = result.fetchone()
        assert row[0] == "test"

        session.close()

    def test_pg_session_context_manager(self, pg_connection):
        """Test session as context manager for automatic cleanup."""
        with pg_connection.session() as session:
            result = session.execute(text("SELECT 42 as answer"))
            row = result.fetchone()
            assert row[0] == 42

    def test_pg_multiple_sessions(self, pg_connection):
        """Test that multiple sessions can be created from same PG instance."""
        session1 = pg_connection.session()
        session2 = pg_connection.session()

        try:
            # Both should work independently
            result1 = session1.execute(text("SELECT 1"))
            result2 = session2.execute(text("SELECT 2"))

            assert result1.fetchone()[0] == 1
            assert result2.fetchone()[0] == 2
        finally:
            session1.close()
            session2.close()


@pytest.mark.integration
class TestPGHealthCheck:
    """Test PG health check functionality."""

    def test_health_check_returns_healthy_status(self, pg_connection):
        """Test that health_check returns healthy status for working database."""
        result = pg_connection.health_check()

        assert result["status"] == "healthy"
        assert result["error"] is None
        assert "response_time_ms" in result
        assert result["response_time_ms"] >= 0

    def test_health_check_measures_response_time(self, pg_connection):
        """Test that health check measures response time."""
        result = pg_connection.health_check()

        # Response time should be a reasonable number (< 1 second for local DB)
        assert result["response_time_ms"] < 1000
        assert result["response_time_ms"] > 0


@pytest.mark.integration
class TestPGPoolStatus:
    """Test connection pool status monitoring."""

    def test_get_pool_status_returns_stats(self, pg_connection):
        """Test that get_pool_status returns pool statistics."""
        # Note: pg_connection uses NullPool, so this tests NullPool behavior
        status = pg_connection.get_pool_status()

        assert "pool_size" in status
        assert "checked_out" in status
        assert "overflow" in status
        assert "checked_in" in status
        assert "total_connections" in status


@pytest.mark.integration
class TestPGQueryExecution:
    """Test query execution and transaction handling."""

    def test_execute_select_query(self, pg_session, pg_debug_table):
        """Test executing SELECT queries."""
        # Create test table
        pg_session.execute(
            text(
                f"""
            CREATE TABLE {pg_debug_table} (
                id INT PRIMARY KEY,
                name TEXT NOT NULL
            )
        """
            )
        )
        pg_session.commit()

        # Insert test data
        pg_session.execute(
            text(f"INSERT INTO {pg_debug_table} (id, name) VALUES (1, 'Alice')")
        )
        pg_session.commit()

        # Query the data
        result = pg_session.execute(
            text(f"SELECT name FROM {pg_debug_table} WHERE id = 1")
        )
        name = result.fetchone()[0]
        assert name == "Alice"

    def test_execute_insert_and_update(self, pg_session, pg_debug_table):
        """Test INSERT and UPDATE operations."""
        # Create test table
        pg_session.execute(
            text(
                f"""
            CREATE TABLE {pg_debug_table} (
                id SERIAL PRIMARY KEY,
                value INT NOT NULL
            )
        """
            )
        )
        pg_session.commit()

        # Insert
        result = pg_session.execute(
            text(f"INSERT INTO {pg_debug_table} (value) VALUES (100) RETURNING id")
        )
        row_id = result.fetchone()[0]
        pg_session.commit()

        # Update
        pg_session.execute(
            text(f"UPDATE {pg_debug_table} SET value = 200 WHERE id = {row_id}")
        )
        pg_session.commit()

        # Verify update
        result = pg_session.execute(
            text(f"SELECT value FROM {pg_debug_table} WHERE id = {row_id}")
        )
        value = result.fetchone()[0]
        assert value == 200

    def test_transaction_commit(self, pg_session, pg_debug_table):
        """Test transaction commit behavior."""
        # Create table
        pg_session.execute(text(f"CREATE TABLE {pg_debug_table} (id INT PRIMARY KEY)"))
        pg_session.commit()

        # Start transaction
        pg_session.execute(text(f"INSERT INTO {pg_debug_table} VALUES (1)"))
        pg_session.commit()

        # Verify data persisted
        result = pg_session.execute(text(f"SELECT COUNT(*) FROM {pg_debug_table}"))
        count = result.fetchone()[0]
        assert count == 1

    def test_transaction_rollback(self, pg_session, pg_debug_table):
        """Test transaction rollback behavior."""
        # Create table
        pg_session.execute(text(f"CREATE TABLE {pg_debug_table} (id INT PRIMARY KEY)"))
        pg_session.commit()

        # Insert initial data
        pg_session.execute(text(f"INSERT INTO {pg_debug_table} VALUES (1)"))
        pg_session.commit()

        # Try to insert duplicate (will fail)
        try:
            pg_session.execute(text(f"INSERT INTO {pg_debug_table} VALUES (1)"))
            pg_session.commit()
            assert False, "Should have raised IntegrityError"
        except Exception:
            pg_session.rollback()

        # Verify only original row exists
        result = pg_session.execute(text(f"SELECT COUNT(*) FROM {pg_debug_table}"))
        count = result.fetchone()[0]
        assert count == 1


@pytest.mark.integration
class TestPGMigration:
    """Test database migration functionality."""

    def test_migrate_creates_tables(self, pg_connection, pg_session, pg_debug_table):
        """Test that migrate() creates tables from SQLAlchemy models."""
        # Create a test model
        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = pg_debug_table
            id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
            name = sqlalchemy.Column(sqlalchemy.String(50), nullable=False)

        # Run migration
        pg_connection.migrate(Base)

        # Verify table was created
        result = pg_session.execute(
            text(
                f"""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = '{pg_debug_table}'
        """
            )
        )
        count = result.fetchone()[0]
        assert count == 1

        # Verify we can insert data
        pg_session.execute(
            text(f"INSERT INTO {pg_debug_table} (id, name) VALUES (1, 'test')")
        )
        pg_session.commit()

        # Verify data
        result = pg_session.execute(text(f"SELECT name FROM {pg_debug_table}"))
        name = result.fetchone()[0]
        assert name == "test"

    def test_migrate_runs_before_hooks(self, pg_connection, pg_session, pg_debug_table):
        """Test that migrate() runs before_migrate hooks."""
        hook_calls = []

        @pg_connection.on_before_migrate
        def before_hook(conn):
            hook_calls.append("before")
            # Create a schema that the table will use
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS test_schema"))

        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = pg_debug_table
            id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)

        pg_connection.migrate(Base)

        # Verify hook was called
        assert "before" in hook_calls

        # Verify schema was created (hook ran before table creation)
        result = pg_session.execute(
            text(
                """
            SELECT COUNT(*)
            FROM information_schema.schemata
            WHERE schema_name = 'test_schema'
        """
            )
        )
        count = result.fetchone()[0]
        assert count == 1

        # Cleanup
        pg_session.execute(text("DROP SCHEMA IF EXISTS test_schema CASCADE"))
        pg_session.commit()

    def test_migrate_runs_after_hooks(self, pg_connection, pg_session, pg_debug_table):
        """Test that migrate() runs after_migrate hooks."""
        hook_calls = []

        @pg_connection.on_after_migrate
        def after_hook(conn):
            hook_calls.append("after")
            # Insert seed data after tables are created
            conn.execute(
                text(f"INSERT INTO {pg_debug_table} (id, name) VALUES (999, 'seeded')")
            )

        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = pg_debug_table
            id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
            name = sqlalchemy.Column(sqlalchemy.String(50), nullable=True)

        pg_connection.migrate(Base)

        # Verify hook was called
        assert "after" in hook_calls

        # Verify seed data was inserted (hook ran after table creation)
        result = pg_session.execute(
            text(f"SELECT name FROM {pg_debug_table} WHERE id = 999")
        )
        name = result.fetchone()[0]
        assert name == "seeded"

    def test_migrate_runs_hooks_in_order(self, pg_config, pg_logger, pg_debug_table):
        """Test that migrate() runs hooks in correct order: before -> tables -> after."""
        # Use fresh PG instance to avoid hook pollution from other tests
        pg = PG(pg_logger, pg_config)
        execution_order = []

        @pg.on_before_migrate
        def before_hook(conn):
            execution_order.append("before")

        @pg.on_after_migrate
        def after_hook(conn):
            execution_order.append("after")

        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = pg_debug_table
            id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)

        pg.migrate(Base)

        # Verify order
        assert execution_order == ["before", "after"]


@pytest.mark.integration
class TestPGConfigValidation:
    """Test configuration validation."""

    def test_pg_initialization_with_valid_config(self, pg_config, pg_logger):
        """Test PG initialization with valid configuration."""
        pg = PG(pg_logger, pg_config)
        assert pg is not None

        # Verify we can create a session
        session = pg.session()
        assert session is not None
        session.close()

    def test_pg_url_property_returns_database_url(self, pg_connection):
        """Test that url property returns the database URL."""
        url = pg_connection.url
        assert url is not None
        # url is a SQLAlchemy URL object, convert to string to check
        url_str = str(url)
        assert "postgresql" in url_str or "postgres" in url_str

    def test_pg_engine_property_returns_engine(self, pg_connection):
        """Test that engine property returns SQLAlchemy engine."""
        engine = pg_connection.engine
        assert engine is not None
        assert isinstance(engine, sqlalchemy.engine.Engine)


@pytest.mark.integration
class TestPGComplexQueries:
    """Test complex query scenarios."""

    def test_parameterized_queries(self, pg_session, pg_debug_table):
        """Test parameterized queries for SQL injection safety."""
        # Create table
        pg_session.execute(
            text(
                f"""
            CREATE TABLE {pg_debug_table} (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL,
                email TEXT NOT NULL
            )
        """
            )
        )
        pg_session.commit()

        # Insert with parameters
        pg_session.execute(
            text(
                f"""
            INSERT INTO {pg_debug_table} (username, email)
            VALUES (:username, :email)
        """
            ),
            {"username": "alice", "email": "alice@example.com"},
        )
        pg_session.commit()

        # Query with parameters
        result = pg_session.execute(
            text(f"SELECT email FROM {pg_debug_table} WHERE username = :username"),
            {"username": "alice"},
        )
        email = result.fetchone()[0]
        assert email == "alice@example.com"

    def test_aggregate_functions(self, pg_session, pg_debug_table):
        """Test aggregate functions (COUNT, SUM, AVG, etc.)."""
        # Create table
        pg_session.execute(
            text(
                f"""
            CREATE TABLE {pg_debug_table} (
                id SERIAL PRIMARY KEY,
                amount DECIMAL(10,2) NOT NULL
            )
        """
            )
        )
        pg_session.commit()

        # Insert test data
        amounts = [10.50, 20.75, 30.00, 15.25]
        for amount in amounts:
            pg_session.execute(
                text(f"INSERT INTO {pg_debug_table} (amount) VALUES ({amount})")
            )
        pg_session.commit()

        # Test COUNT
        result = pg_session.execute(text(f"SELECT COUNT(*) FROM {pg_debug_table}"))
        count = result.fetchone()[0]
        assert count == 4

        # Test SUM
        result = pg_session.execute(text(f"SELECT SUM(amount) FROM {pg_debug_table}"))
        total = float(result.fetchone()[0])
        assert abs(total - sum(amounts)) < 0.01

        # Test AVG
        result = pg_session.execute(text(f"SELECT AVG(amount) FROM {pg_debug_table}"))
        avg = float(result.fetchone()[0])
        expected_avg = sum(amounts) / len(amounts)
        assert abs(avg - expected_avg) < 0.01

    def test_join_operations(self, pg_session, pg_debug_table):
        """Test JOIN operations between tables."""
        users_table = pg_debug_table
        orders_table = f"{pg_debug_table}_orders"

        # Create users table
        pg_session.execute(
            text(
                f"""
            CREATE TABLE {users_table} (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL
            )
        """
            )
        )

        # Create orders table
        pg_session.execute(
            text(
                f"""
            CREATE TABLE {orders_table} (
                id SERIAL PRIMARY KEY,
                user_id INT REFERENCES {users_table}(id),
                product TEXT NOT NULL
            )
        """
            )
        )
        pg_session.commit()

        # Insert test data
        pg_session.execute(
            text(f"INSERT INTO {users_table} (name) VALUES ('Alice') RETURNING id")
        )
        result = pg_session.execute(text(f"SELECT id FROM {users_table}"))
        user_id = result.fetchone()[0]
        pg_session.commit()

        pg_session.execute(
            text(
                f"INSERT INTO {orders_table} (user_id, product) VALUES ({user_id}, 'Widget')"
            )
        )
        pg_session.commit()

        # Test JOIN
        result = pg_session.execute(
            text(
                f"""
            SELECT u.name, o.product
            FROM {users_table} u
            JOIN {orders_table} o ON u.id = o.user_id
        """
            )
        )
        row = result.fetchone()
        assert row[0] == "Alice"
        assert row[1] == "Widget"

        # Cleanup orders table
        pg_session.execute(text(f"DROP TABLE {orders_table} CASCADE"))
        pg_session.commit()
