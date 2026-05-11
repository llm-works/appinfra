"""
E2E test for PostgreSQL session context managers.

Tests the session() context manager workflow with transactional and autocommit modes.
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from appinfra.config import Config
from appinfra.db.pg.pg import PG
from appinfra.log import LoggingBuilder

# Resolve config path relative to test file (works from any CWD)
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "etc" / "infra.yaml"


@pytest.mark.e2e
class TestPGSessionWorkflow:
    """E2E tests for PG session context managers."""

    def setup_method(self):
        """Set up E2E test environment."""
        self.logger = LoggingBuilder("e2e_session").with_level("info").build()
        self.cfg = Config(str(_CONFIG_PATH))
        self.pg = PG(self.logger, self.cfg.dbs.unittest)

    def teardown_method(self):
        """Clean up test resources."""
        if hasattr(self, "pg") and hasattr(self.pg, "_engine"):
            import sqlalchemy

            if hasattr(self.pg, "_after_execute_listener"):
                sqlalchemy.event.remove(
                    self.pg._engine,
                    "after_execute",
                    self.pg._after_execute_listener,
                )
            if hasattr(self.pg, "_before_cursor_listener"):
                sqlalchemy.event.remove(
                    self.pg._engine,
                    "before_cursor_execute",
                    self.pg._before_cursor_listener,
                )
            self.pg._engine.dispose()

    def test_session_commits_on_success(self):
        """Test session() commits changes on successful exit."""
        table_name = f"e2e_session_commit_{uuid.uuid4().hex[:8]}"

        # Create table and insert data in one session
        with self.pg.session() as session:
            session.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            session.execute(
                text(f"CREATE TABLE {table_name} (id INT PRIMARY KEY, value TEXT)")
            )
            session.execute(
                text(f"INSERT INTO {table_name} (id, value) VALUES (1, 'committed')")
            )

        # Verify data persists in new session
        with self.pg.session() as session:
            result = session.execute(
                text(f"SELECT value FROM {table_name} WHERE id = 1")
            )
            assert result.scalar() == "committed"

        # Cleanup
        with self.pg.session() as session:
            session.execute(text(f"DROP TABLE {table_name}"))

    def test_session_rollback_on_exception(self):
        """Test session() rolls back on exception."""
        table_name = f"e2e_session_rollback_{uuid.uuid4().hex[:8]}"

        # Create table first
        with self.pg.session() as session:
            session.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            session.execute(
                text(f"CREATE TABLE {table_name} (id INT PRIMARY KEY, value TEXT)")
            )
            session.execute(
                text(f"INSERT INTO {table_name} (id, value) VALUES (1, 'original')")
            )

        # Try to update but raise exception - should rollback
        with pytest.raises(RuntimeError):
            with self.pg.session() as session:
                session.execute(
                    text(f"UPDATE {table_name} SET value = 'modified' WHERE id = 1")
                )
                raise RuntimeError("Simulated error")

        # Verify original value remains
        with self.pg.session() as session:
            result = session.execute(
                text(f"SELECT value FROM {table_name} WHERE id = 1")
            )
            assert result.scalar() == "original"

        # Cleanup
        with self.pg.session() as session:
            session.execute(text(f"DROP TABLE {table_name}"))

    def test_autocommit_session_executes_queries(self):
        """Test session(autocommit=True) can execute queries."""
        table_name = f"e2e_autocommit_{uuid.uuid4().hex[:8]}"

        # Setup: create table with data
        with self.pg.session() as session:
            session.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            session.execute(
                text(f"CREATE TABLE {table_name} (id INT PRIMARY KEY, value TEXT)")
            )
            session.execute(
                text(f"INSERT INTO {table_name} (id, value) VALUES (1, 'readable')")
            )

        # Read using autocommit session
        with self.pg.session(autocommit=True) as session:
            result = session.execute(
                text(f"SELECT value FROM {table_name} WHERE id = 1")
            )
            assert result.scalar() == "readable"

        # Cleanup
        with self.pg.session() as session:
            session.execute(text(f"DROP TABLE {table_name}"))

    def test_create_session_returns_raw_session(self):
        """Test _create_session() returns a usable raw session."""
        session = self.pg._create_session()
        try:
            result = session.execute(text("SELECT 1 as value"))
            assert result.scalar() == 1
        finally:
            session.close()
