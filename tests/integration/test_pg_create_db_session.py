"""
Integration test for create_db=True on the session() path.

Verifies that PG.__init__() eagerly creates the database when create_db=True,
so that session() (which lazily connects via sessionmaker) succeeds on a fresh
volume without requiring a prior connect() or migrate() call.

Regression test for the fix in b32b956.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy_utils
from sqlalchemy import text

from appinfra.db.pg.pg import PG

pytestmark = pytest.mark.require_pg


@pytest.mark.integration
class TestCreateDbOnSession:
    """Verify create_db=True works on the session() path without migrate()."""

    def test_session_creates_database_when_create_db_true(
        self, pg_config, pg_logger, pg_available
    ):
        """
        Calling session() on a PG instance with create_db=True should
        automatically create the database, even without a prior migrate() call.
        """
        if not pg_available:
            pytest.skip("PostgreSQL not available")

        # Generate a unique database name that definitely doesn't exist
        unique_db = f"appinfra_create_db_test_{uuid.uuid4().hex[:12]}"

        # Build a config pointing to the non-existent database with create_db=True
        # Start from the existing test config and override the URL
        base_url = pg_config.url
        # Replace the database name in the URL
        # URL format: postgresql://user:pass@host:port/dbname
        url_parts = base_url.rsplit("/", 1)
        test_url = f"{url_parts[0]}/{unique_db}"

        test_cfg = {
            "url": test_url,
            "create_db": True,
            "readonly": False,
            "pool_size": 2,
            "max_overflow": 2,
        }

        pg = None
        try:
            # Create PG instance - this should eagerly create the database
            pg = PG(pg_logger, test_cfg)

            # Verify database was created during __init__
            assert sqlalchemy_utils.database_exists(pg._engine.url), (
                "Database should exist after PG.__init__() with create_db=True"
            )

            # Now call session() - this should work without migrate()
            with pg.session() as session:
                # Execute a simple query to verify the session works
                result = session.execute(text("SELECT 1"))
                assert result.scalar() == 1

        finally:
            # Cleanup: drop the test database
            if pg is not None:
                pg._engine.dispose()
                if sqlalchemy_utils.database_exists(test_url):
                    sqlalchemy_utils.drop_database(test_url)
