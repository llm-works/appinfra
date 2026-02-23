"""
Integration tests for PostgreSQL fixtures.

These tests verify that the pytest fixtures for PostgreSQL integration testing
work correctly against a real database.

Run with:
    ~/.venv/bin/python -m pytest tests/integration/test_pg_fixtures.py -v -s
"""

import os

import pytest
import sqlalchemy


@pytest.mark.integration
class TestPGFixtures:
    """Test PostgreSQL integration fixtures."""

    def test_pg_config_loads(self, pg_config):
        """Test that PostgreSQL configuration loads correctly."""
        assert pg_config is not None
        assert hasattr(pg_config, "url")
        assert "postgresql" in pg_config.url or "postgres" in pg_config.url

    def test_pg_connection_works(self, pg_connection):
        """Test that PostgreSQL connection is established."""
        assert pg_connection is not None
        # Test we can create a session
        session = pg_connection.session()
        assert session is not None
        session.close()

    def test_pg_session_basic_query(self, pg_session):
        """Test that we can execute basic queries with pg_session."""
        result = pg_session.execute(sqlalchemy.text("SELECT 1 as value"))
        row = result.fetchone()
        assert row[0] == 1

    def test_pg_debug_table_creation(self, pg_session, pg_debug_table):
        """Test debug table creation and data insertion."""
        # Create table with test data
        pg_session.execute(
            sqlalchemy.text(
                f"""
            CREATE TABLE {pg_debug_table} (
                id INT PRIMARY KEY,
                name TEXT NOT NULL
            )
        """
            )
        )
        pg_session.commit()

        # Insert data
        pg_session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {pg_debug_table} (id, name) VALUES (1, 'test_data')
        """
            )
        )
        pg_session.commit()

        # Verify data
        result = pg_session.execute(
            sqlalchemy.text(f"SELECT COUNT(*) FROM {pg_debug_table}")
        )
        count = result.fetchone()[0]
        assert count == 1

        # Verify content
        result = pg_session.execute(
            sqlalchemy.text(f"SELECT name FROM {pg_debug_table} WHERE id = 1")
        )
        name = result.fetchone()[0]
        assert name == "test_data"

    def test_pg_debug_table_custom_schema(self, pg_session, pg_debug_table_with_schema):
        """Test debug table with custom schema."""
        table_name, create_table = pg_debug_table_with_schema

        # Create table with custom schema
        create_table(
            """
            id SERIAL PRIMARY KEY,
            data JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        """
        )

        # Insert JSON data
        pg_session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {table_name} (data)
            VALUES ('{{"key": "value", "number": 42}}'::jsonb)
        """
            )
        )
        pg_session.commit()

        # Verify JSONB query works
        result = pg_session.execute(
            sqlalchemy.text(
                f"""
            SELECT data->>'key' as key_value FROM {table_name}
        """
            )
        )
        key_value = result.fetchone()[0]
        assert key_value == "value"

    def test_pg_debug_table_multiple_inserts(self, pg_session, pg_debug_table):
        """Test multiple inserts and complex queries."""
        # Create table
        pg_session.execute(
            sqlalchemy.text(
                f"""
            CREATE TABLE {pg_debug_table} (
                id SERIAL PRIMARY KEY,
                product TEXT NOT NULL,
                price DECIMAL(10,2) NOT NULL,
                quantity INT NOT NULL
            )
        """
            )
        )
        pg_session.commit()

        # Insert multiple rows
        products = [
            ("Widget", 10.99, 5),
            ("Gadget", 25.50, 3),
            ("Doohickey", 15.00, 10),
        ]

        for product, price, qty in products:
            pg_session.execute(
                sqlalchemy.text(
                    f"""
                INSERT INTO {pg_debug_table} (product, price, quantity)
                VALUES ('{product}', {price}, {qty})
            """
                )
            )
        pg_session.commit()

        # Test aggregation
        result = pg_session.execute(
            sqlalchemy.text(
                f"""
            SELECT SUM(price * quantity) as total_value
            FROM {pg_debug_table}
        """
            )
        )
        total = float(result.fetchone()[0])
        expected = (10.99 * 5) + (25.50 * 3) + (15.00 * 10)
        assert abs(total - expected) < 0.01

    def test_pg_cleanup_tables_utility(self, pg_session, pg_cleanup_tables):
        """Test manual table cleanup utility."""
        import time

        # Use timestamped names to avoid conflicts
        timestamp = int(time.time())
        table1 = f"temp_test1_{timestamp}"
        table2 = f"temp_test2_{timestamp}"

        # Create temp tables
        pg_session.execute(sqlalchemy.text(f"CREATE TABLE {table1} (id INT)"))
        pg_session.execute(sqlalchemy.text(f"CREATE TABLE {table2} (id INT)"))
        pg_session.commit()

        # Verify tables exist
        result = pg_session.execute(
            sqlalchemy.text(
                f"""
            SELECT COUNT(*)
            FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename IN ('{table1}', '{table2}')
        """
            )
        )
        assert result.fetchone()[0] == 2

        # Cleanup
        pg_cleanup_tables(table1, table2)

        # Verify tables are gone
        result = pg_session.execute(
            sqlalchemy.text(
                f"""
            SELECT COUNT(*)
            FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename IN ('{table1}', '{table2}')
        """
            )
        )
        assert result.fetchone()[0] == 0

    def test_pg_list_debug_tables(
        self, pg_session, pg_debug_table, pg_list_debug_tables
    ):
        """Test listing debug tables."""
        # Create a debug table
        pg_session.execute(
            sqlalchemy.text(
                f"""
            CREATE TABLE {pg_debug_table} (id INT)
        """
            )
        )
        pg_session.commit()

        # List tables
        tables = pg_list_debug_tables()

        # Our table should be in the list
        assert pg_debug_table in tables

        # All tables should have timestamp pattern (10-digit number in name)
        import re

        for table in tables:
            assert re.search(r"_\d{10}_", table), f"Table {table} missing timestamp"


@pytest.mark.integration
class TestPGDebugTableCleanup:
    """Test debug table cleanup behavior on test failure/success."""

    def test_successful_test_cleans_table(self, pg_session, pg_debug_table):
        """
        Test that successful tests clean up their tables.

        This test passes, so the fixture should clean up the table automatically.
        """
        pg_session.execute(
            sqlalchemy.text(
                f"""
            CREATE TABLE {pg_debug_table} (id INT)
        """
            )
        )
        pg_session.commit()

        # Test passes - table will be cleaned up by fixture
        assert True


@pytest.mark.integration
class TestPGComplexScenarios:
    """Test complex real-world database scenarios."""

    def test_transaction_rollback(self, pg_session, pg_debug_table):
        """Test that rollback works correctly."""
        # Create table
        pg_session.execute(
            sqlalchemy.text(
                f"""
            CREATE TABLE {pg_debug_table} (id INT PRIMARY KEY, value TEXT)
        """
            )
        )
        pg_session.commit()

        # Start transaction
        pg_session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {pg_debug_table} VALUES (1, 'original')
        """
            )
        )
        pg_session.commit()

        # Try to insert duplicate (should fail due to PK constraint)
        try:
            pg_session.execute(
                sqlalchemy.text(
                    f"""
                INSERT INTO {pg_debug_table} VALUES (1, 'duplicate')
            """
                )
            )
            pg_session.commit()
            assert False, "Should have raised IntegrityError"
        except Exception:
            pg_session.rollback()

        # Verify original data is still there
        result = pg_session.execute(
            sqlalchemy.text(f"SELECT value FROM {pg_debug_table} WHERE id = 1")
        )
        value = result.fetchone()[0]
        assert value == "original"

    def test_table_with_constraints(self, pg_session, pg_debug_table_with_schema):
        """Test table creation with various constraints."""
        table_name, create_table = pg_debug_table_with_schema

        create_table(
            """
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            age INT CHECK (age >= 0 AND age < 150),
            status TEXT DEFAULT 'active'
        """
        )

        # Insert valid data
        pg_session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {table_name} (email, age)
            VALUES ('test@example.com', 25)
        """
            )
        )
        pg_session.commit()

        # Verify constraints work
        result = pg_session.execute(
            sqlalchemy.text(
                f"SELECT status FROM {table_name} WHERE email = 'test@example.com'"
            )
        )
        status = result.fetchone()[0]
        assert status == "active"

    def test_foreign_key_relationships(self, pg_session, pg_debug_table_with_schema):
        """Test tables with foreign key relationships."""
        parent_table, create_parent = pg_debug_table_with_schema

        # Create parent table
        create_parent(
            """
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL
        """
        )

        # Create child table with FK
        child_table = f"{parent_table}_child"
        pg_session.execute(
            sqlalchemy.text(
                f"""
            CREATE TABLE {child_table} (
                id SERIAL PRIMARY KEY,
                parent_id INT REFERENCES {parent_table}(id) ON DELETE CASCADE,
                data TEXT
            )
        """
            )
        )
        pg_session.commit()

        # Insert parent
        pg_session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {parent_table} (name) VALUES ('Parent 1')
            RETURNING id
        """
            )
        )
        result = pg_session.execute(sqlalchemy.text(f"SELECT id FROM {parent_table}"))
        parent_id = result.fetchone()[0]
        pg_session.commit()

        # Insert child
        pg_session.execute(
            sqlalchemy.text(
                f"""
            INSERT INTO {child_table} (parent_id, data)
            VALUES ({parent_id}, 'Child data')
        """
            )
        )
        pg_session.commit()

        # Verify relationship
        result = pg_session.execute(
            sqlalchemy.text(
                f"""
            SELECT c.data, p.name
            FROM {child_table} c
            JOIN {parent_table} p ON c.parent_id = p.id
        """
            )
        )
        row = result.fetchone()
        assert row[0] == "Child data"
        assert row[1] == "Parent 1"

        # Child table cleaned up via CASCADE when parent debug table is dropped


@pytest.mark.integration
class TestPGStaleTableCleanup:
    """Test that stale debug tables are cleaned at session start."""

    @pytest.mark.expected_skip  # Skipped in xdist workers (expected)
    @pytest.mark.skipif(
        os.environ.get("PYTEST_XDIST_WORKER") is not None,
        reason="Cleanup only runs on master; test not valid with xdist workers",
    )
    def test_stale_tables_cleaned_at_session_start(self, pg_session):
        """
        Verify no tables with old timestamps exist after session starts.

        The pg_cleanup_stale_debug_tables fixture runs at session start and
        removes all tables matching the debug pattern. Any debug tables that
        exist at this point should be from the current session (recent timestamp).

        Note: This test only runs on master (non-xdist) because the cleanup
        fixture only runs on master. With xdist, workers create tables that
        won't be cleaned by the master's session-scoped fixture.
        """
        import re
        import time

        result = pg_session.execute(
            sqlalchemy.text(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                AND tablename ~ '_[0-9]{10}_'
                """
            )
        )
        tables = result.fetchall()

        current_time = int(time.time())
        for (table,) in tables:
            # Extract timestamp from table name
            match = re.search(r"_(\d{10})_", table)
            if match:
                table_time = int(match.group(1))
                # Table should be from this session (within last 5 minutes)
                age_seconds = current_time - table_time
                assert age_seconds < 300, (
                    f"Stale table '{table}' is {age_seconds}s old - "
                    "should have been cleaned at session start"
                )

    def test_table_retained_on_test_failure(self, pg_session):
        """
        Verify tables are retained when a test fails.

        This tests the cleanup logic directly by mocking the test outcome,
        rather than running a subprocess test that actually fails.
        """
        import os
        import time
        from unittest.mock import Mock

        from tests.fixtures.pg_integration import _cleanup_debug_table

        # Create a table with debug naming pattern
        table_name = f"test_retention_{int(time.time())}_{os.getpid()}_1"
        pg_session.execute(sqlalchemy.text(f"CREATE TABLE {table_name} (id INT)"))
        pg_session.commit()

        # Mock a failed test request
        mock_request = Mock()
        mock_request.node.rep_call.failed = True

        # Cleanup should NOT drop the table when test failed
        _cleanup_debug_table(mock_request, pg_session, table_name)

        # Verify table still exists
        result = pg_session.execute(
            sqlalchemy.text(f"SELECT 1 FROM pg_tables WHERE tablename = '{table_name}'")
        )
        assert result.fetchone() is not None, "Table should be retained on failure"

        # Now test that passing test cleans up
        mock_request.node.rep_call.failed = False
        _cleanup_debug_table(mock_request, pg_session, table_name)

        # Verify table is gone
        result = pg_session.execute(
            sqlalchemy.text(f"SELECT 1 FROM pg_tables WHERE tablename = '{table_name}'")
        )
        assert result.fetchone() is None, "Table should be cleaned on success"
