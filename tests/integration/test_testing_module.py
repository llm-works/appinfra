# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Integration tests for the appinfra.db.pg.testing module.

Verifies that the pytest fixtures work correctly for schema isolation.
"""

import pytest
from sqlalchemy import Column, Integer, String, text
from sqlalchemy.orm import declarative_base

from appinfra.db.pg.testing import make_migrate_fixture

MigrateBase = declarative_base()


class MigrateFixtureModel(MigrateBase):
    __tablename__ = "migrate_fixture_test"
    id = Column(Integer, primary_key=True)
    name = Column(String(50))


pg_migrated = make_migrate_fixture(MigrateBase)


def _schema_exists(pg, schema: str) -> bool:
    with pg.engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.schemata "
                "WHERE schema_name = :schema"
            ),
            {"schema": schema},
        )
        return result.scalar() == 1


# Override the default fixtures to use our test config
@pytest.fixture(scope="session")
def pg_test_config(pg_config):
    """Use the existing pg_config from pg_integration fixtures."""
    return pg_config


@pytest.fixture(scope="session")
def pg_test_logger(pg_logger):
    """Use the existing pg_logger from pg_integration fixtures."""
    return pg_logger


# The appinfra.db.pg.testing fixtures come from tests/conftest.py

# All classes here exercise PG-backed fixtures from appinfra.db.pg.testing;
# skip the whole module with the sentinel reason if PG is unreachable.
pytestmark = pytest.mark.require_pg


class TestPgIsolatedFixture:
    """Test the pg_isolated fixture."""

    def test_pg_isolated_has_schema(self, pg_isolated):
        """Test that pg_isolated has a schema configured."""
        import re

        assert pg_isolated.schema is not None
        # Schema format: {suite}_{worker} where suite is test/unit/integ/e2e/etc.
        # and worker is master or gwN (suite must start with lowercase letter)
        assert re.match(r"^[a-z][a-z0-9_]*_(master|gw\d+)$", pg_isolated.schema)

    def test_pg_isolated_can_execute_queries(self, pg_isolated):
        """Test that pg_isolated can execute queries."""
        with pg_isolated.session() as session:
            result = session.execute(text("SELECT 1 as value"))
            row = result.fetchone()
            assert row[0] == 1


class TestPgSessionIsolatedFixture:
    """Test the pg_session_isolated fixture."""

    def test_session_executes_in_schema(self, pg_isolated, pg_session_isolated):
        """Test session executes queries in the correct schema."""
        # Create a test table
        pg_session_isolated.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS test_session_fixture (
                    id INT PRIMARY KEY,
                    value TEXT
                )
                """
            )
        )
        pg_session_isolated.commit()

        # Verify table is in the correct schema
        result = pg_session_isolated.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = :schema
                AND table_name = 'test_session_fixture'
                """
            ),
            {"schema": pg_isolated.schema},
        )
        assert result.scalar() == 1


class TestSchemaIsolationRobustness:
    """Regression tests for schema isolation under pool-state stress.

    The SchemaManager listener is hooked on the ``checkout`` event so
    every session that grabs a pooled connection re-establishes
    ``search_path``. Under the earlier ``connect``-only wiring, a
    connection whose ``search_path`` had been reset between uses
    would leak into the next session — the failure mode that surfaces
    intermittently when parallel test workers share a database.
    """

    def test_search_path_recovers_after_pool_reset(self, pg_isolated):
        """After a raw connection deliberately overwrites search_path and
        returns to the pool, the next session must still see the isolated
        schema. Under the pre-fix listener this would leak `public` into
        the next session."""
        # Overwrite search_path on a pooled connection.
        with pg_isolated._engine.connect() as conn:
            conn.execute(text('SET search_path TO "public"'))
            conn.commit()

        # A fresh session must still route to the isolated schema.
        with pg_isolated.session() as sess:
            row = sess.execute(text("SHOW search_path")).scalar()
            assert pg_isolated.schema in row, (
                f"search_path leaked past pool reset: got {row!r}, "
                f"expected schema {pg_isolated.schema!r}"
            )

    def test_search_path_stable_across_many_checkouts(self, pg_isolated):
        """Every session in a long sequence sees the isolated schema.
        Exercises pool reuse without creating new physical connections."""
        for i in range(50):
            with pg_isolated.session() as sess:
                row = sess.execute(text("SHOW search_path")).scalar()
                assert pg_isolated.schema in row, (
                    f"iteration {i}: search_path {row!r} lost schema "
                    f"{pg_isolated.schema!r}"
                )


class TestMakeMigrateFixture:
    """Test the make_migrate_fixture factory."""

    def test_creates_tables_from_base(self, pg_migrated):
        """Test that make_migrate_fixture creates tables in its schema."""
        with pg_migrated.engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = :schema
                    AND table_name = 'migrate_fixture_test'
                    """
                ),
                {"schema": pg_migrated.schema},
            )
            assert result.scalar() == 1

    def test_uses_a_schema_of_its_own(self, pg_isolated, pg_migrated):
        """The fixture's schema is not the worker schema pg_isolated uses."""
        assert pg_migrated.schema != pg_isolated.schema
        assert _schema_exists(pg_isolated, pg_isolated.schema)


class TestPgMigrateFactory:
    """Test the pg_migrate_factory fixture."""

    def test_factory_creates_tables_in_schema(self, pg_migrate_factory):
        """Test that pg_migrate_factory creates tables in the schema."""
        Base = declarative_base()

        class FactoryTestModel(Base):
            __tablename__ = "factory_test_table"
            id = Column(Integer, primary_key=True)
            name = Column(String(50))

        # Verify table exists in correct schema
        with pg_migrate_factory(Base) as pg, pg.engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = :schema
                    AND table_name = 'factory_test_table'
                    """
                ),
                {"schema": pg.schema},
            )
            assert result.scalar() == 1

    def test_factory_cleans_up_on_exit(self, pg_migrate_factory, pg_test_schema):
        """Test that pg_migrate_factory cleans up schema on context exit."""
        Base = declarative_base()

        class CleanupTestModel(Base):
            __tablename__ = "cleanup_test_table"
            id = Column(Integer, primary_key=True)

        # Use the factory and exit the context
        with pg_migrate_factory(Base) as pg:
            engine = pg.engine
            schema = pg.schema

        # After context exit, schema should be dropped. The factory disposed the
        # engine's pool; this query opens a new one, closed again below.
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.schemata
                        WHERE schema_name = :schema
                        """
                    ),
                    {"schema": schema},
                )
                assert result.scalar() == 0
        finally:
            engine.dispose()

    def test_factory_leaves_the_worker_schema(self, pg_isolated, pg_migrate_factory):
        """Entering and leaving the factory keeps pg_isolated's schema."""
        Base = declarative_base()

        class WorkerSchemaTestModel(Base):
            __tablename__ = "worker_schema_test_table"
            id = Column(Integer, primary_key=True)

        with pg_migrate_factory(Base) as pg:
            assert pg.schema != pg_isolated.schema

        assert _schema_exists(pg_isolated, pg_isolated.schema)

    def test_factory_accepts_extensions(self, pg_migrate_factory):
        """Test that pg_migrate_factory accepts extensions parameter."""
        Base = declarative_base()

        class ExtensionsTestModel(Base):
            __tablename__ = "extensions_test_table"
            id = Column(Integer, primary_key=True)

        # Just verify it doesn't error with extensions parameter
        # (actual extension creation depends on DB having the extension available)
        with pg_migrate_factory(Base, extensions=[]) as pg:
            assert pg.schema is not None


class TestPgCleanSchemaFixture:
    """Test the pg_clean_schema fixture."""

    def test_clean_schema_starts_fresh(self, pg_clean_schema, pg_isolated):
        """Test that pg_clean_schema provides a fresh schema."""
        # The schema should be empty (reset just happened)
        with pg_isolated.engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = :schema
                    """
                ),
                {"schema": pg_isolated.schema},
            )
            # Should have no tables in a freshly reset schema
            assert result.scalar() == 0
