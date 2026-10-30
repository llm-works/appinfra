# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
E2E test for PostgreSQL readonly mode workflow.

This test validates readonly database connections by testing a complete workflow
from configuration loading through query execution and proper cleanup.
"""

import pytest
from sqlalchemy import text

from appinfra.config import Config
from appinfra.db.pg.pg import PG
from appinfra.log import LoggingBuilder


@pytest.mark.e2e
@pytest.mark.require_pg
class TestPGReadOnlyWorkflow:
    """E2E tests for PostgreSQL readonly mode complete workflow."""

    def setup_method(self):
        """Set up E2E test environment."""
        # Create logger
        self.logger = LoggingBuilder("e2e_readonly").with_level("info").build()

        # Load config
        self.cfg = Config("etc/infra.yaml")

        # Create read-write connection for setup
        self.pg_rw = PG(self.logger, self.cfg.dbs.unittest)

        # Create readonly connection
        self.pg_ro = PG(self.logger, self.cfg.dbs.unittest_ro)

        # Track cleanup tasks
        self.cleanup_tasks = []

    def teardown_method(self):
        """Clean up test resources."""
        # Clean up readonly connection
        self._cleanup_pg(self.pg_ro)

        # Clean up read-write connection
        self._cleanup_pg(self.pg_rw)

    def _cleanup_pg(self, pg_instance):
        """Clean up PG instance and remove event listeners."""
        if hasattr(pg_instance, "_engine") and pg_instance._engine is not None:
            import sqlalchemy

            # Remove all event listeners to prevent hanging
            if hasattr(pg_instance, "_readonly_listener"):
                sqlalchemy.event.remove(
                    pg_instance._engine, "begin", pg_instance._readonly_listener
                )
            if hasattr(pg_instance, "_after_execute_listener"):
                sqlalchemy.event.remove(
                    pg_instance._engine,
                    "after_execute",
                    pg_instance._after_execute_listener,
                )
            if hasattr(pg_instance, "_before_cursor_listener"):
                sqlalchemy.event.remove(
                    pg_instance._engine,
                    "before_cursor_execute",
                    pg_instance._before_cursor_listener,
                )

            pg_instance._engine.dispose()

    def _create_test_table(self, table_name, initial_value="test"):
        """Create test table with initial data."""
        with self.pg_rw.session() as session:
            session.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            session.execute(
                text(
                    f"""
                CREATE TABLE {table_name} (
                    id INT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """
                )
            )
            session.execute(
                text(
                    f"INSERT INTO {table_name} (id, value) VALUES (1, '{initial_value}')"
                )
            )
            session.commit()

    def _drop_test_table(self, table_name):
        """Drop test table."""
        with self.pg_rw.session() as session:
            session.execute(text(f"DROP TABLE {table_name}"))
            session.commit()

    def _verify_readonly_blocks_write(self, sql_statement):
        """Verify that readonly connection blocks write operation."""
        with self.pg_ro.session() as session:
            with pytest.raises(Exception) as exc_info:
                session.execute(text(sql_statement))
                session.commit()

            error_msg = str(exc_info.value).lower()
            assert "read" in error_msg, "Error should indicate readonly constraint"

    def test_readonly_connection_workflow(self):
        """Test complete readonly connection workflow: setup, query, cleanup."""
        table_name = "e2e_readonly_test"

        # Create test table with data
        self._create_test_table(table_name, "readonly_test")

        # Read data using readonly connection
        with self.pg_ro.session() as session:
            result = session.execute(
                text(f"SELECT value FROM {table_name} WHERE id = 1")
            )
            value = result.fetchone()[0]
            assert value == "readonly_test", (
                "Should read value from readonly connection"
            )

        # Verify readonly connection blocks writes
        self._verify_readonly_blocks_write(
            f"INSERT INTO {table_name} (id, value) VALUES (2, 'should_fail')"
        )

        # Cleanup
        self._drop_test_table(table_name)

    def test_readonly_connection_blocks_updates(self):
        """Test that readonly connection blocks UPDATE operations."""
        table_name = "e2e_readonly_update_test"

        # Create test table with data
        self._create_test_table(table_name, "original")

        # Verify readonly connection blocks UPDATE
        self._verify_readonly_blocks_write(
            f"UPDATE {table_name} SET value = 'modified' WHERE id = 1"
        )

        # Verify data unchanged
        with self.pg_rw.session() as session:
            result = session.execute(
                text(f"SELECT value FROM {table_name} WHERE id = 1")
            )
            value = result.fetchone()[0]
            assert value == "original", "Value should remain unchanged"

        # Cleanup
        self._drop_test_table(table_name)

    def test_readonly_connection_blocks_deletes(self):
        """Test that readonly connection blocks DELETE operations."""
        table_name = "e2e_readonly_delete_test"

        # Create test table with data
        self._create_test_table(table_name, "test")

        # Verify readonly connection blocks DELETE
        self._verify_readonly_blocks_write(f"DELETE FROM {table_name} WHERE id = 1")

        # Verify data still exists
        with self.pg_rw.session() as session:
            result = session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            count = result.fetchone()[0]
            assert count == 1, "Row should still exist"

        # Cleanup
        self._drop_test_table(table_name)
