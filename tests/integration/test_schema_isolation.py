"""
Integration tests for PostgreSQL schema isolation.

These tests verify schema isolation works correctly with a real PostgreSQL database,
including table creation, query routing, and parallel execution safety.

Run with:
    pytest tests/integration/test_schema_isolation.py -v -s

Run with parallel workers to test isolation:
    pytest tests/integration/test_schema_isolation.py -v -n 4
"""

import os
import threading
import time

import pytest
from sqlalchemy import Column, Integer, String, text
from sqlalchemy.orm import declarative_base

from appinfra.db.pg import PG


@pytest.mark.integration
class TestSchemaCreation:
    """Test schema creation and management."""

    def test_create_schema_creates_new_schema(self, pg_connection, pg_logger):
        """Test create_schema creates a new PostgreSQL schema."""
        schema_name = f"test_create_{int(time.time())}_{os.getpid()}"

        try:
            # Create PG with schema
            pg = PG(pg_logger, pg_connection.cfg, schema=schema_name)
            pg.create_schema()

            # Verify schema exists
            with pg.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.schemata
                        WHERE schema_name = :schema
                        """
                    ),
                    {"schema": schema_name},
                )
                count = result.scalar()
                assert count == 1, f"Schema '{schema_name}' was not created"

        finally:
            # Cleanup
            with pg_connection.engine.connect() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
                conn.commit()

    def test_schema_property_returns_schema_name(self, pg_connection, pg_logger):
        """Test schema property returns the configured schema name."""
        schema_name = f"test_prop_{int(time.time())}_{os.getpid()}"

        pg = PG(pg_logger, pg_connection.cfg, schema=schema_name)

        assert pg.schema == schema_name

    def test_schema_property_returns_none_without_schema(self, pg_connection):
        """Test schema property returns None when no schema configured."""
        assert pg_connection.schema is None


@pytest.mark.integration
class TestSchemaIsolation:
    """Test that queries are isolated to the configured schema."""

    def test_tables_created_in_correct_schema(self, pg_connection, pg_logger):
        """Test that migrate creates tables in the configured schema."""
        schema_name = f"test_tables_{int(time.time())}_{os.getpid()}"

        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = "schema_test_table"
            id = Column(Integer, primary_key=True)
            name = Column(String(50))

        try:
            pg = PG(pg_logger, pg_connection.cfg, schema=schema_name)
            pg.create_schema()
            pg.migrate(Base)

            # Verify table exists in the correct schema
            with pg.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = :schema
                        AND table_name = 'schema_test_table'
                        """
                    ),
                    {"schema": schema_name},
                )
                count = result.scalar()
                assert count == 1, "Table not created in correct schema"

            # Verify table does NOT exist in public schema
            with pg.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'schema_test_table'
                        """
                    )
                )
                count = result.scalar()
                assert count == 0, "Table incorrectly created in public schema"

        finally:
            with pg_connection.engine.connect() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
                conn.commit()

    def test_queries_use_correct_schema(self, pg_connection, pg_logger):
        """Test that queries are routed to the correct schema via search_path."""
        schema_name = f"test_queries_{int(time.time())}_{os.getpid()}"

        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = "query_test_table"
            id = Column(Integer, primary_key=True)
            value = Column(String(50))

        try:
            pg = PG(pg_logger, pg_connection.cfg, schema=schema_name)
            pg.create_schema()
            pg.migrate(Base)

            # Insert data using session (should use search_path)
            with pg.session() as session:
                session.execute(
                    text("INSERT INTO query_test_table (id, value) VALUES (1, 'test')")
                )
                session.commit()

            # Query data (should find it via search_path)
            with pg.session() as session:
                result = session.execute(
                    text("SELECT value FROM query_test_table WHERE id = 1")
                )
                value = result.scalar()
                assert value == "test"

            # Verify data is actually in the schema-qualified table
            with pg.engine.connect() as conn:
                result = conn.execute(
                    text(
                        f'SELECT value FROM "{schema_name}".query_test_table WHERE id = 1'
                    )
                )
                value = result.scalar()
                assert value == "test"

            # Test read_session also uses schema search_path
            with pg.read_session() as session:
                result = session.execute(
                    text("SELECT value FROM query_test_table WHERE id = 1")
                )
                value = result.scalar()
                assert value == "test"

        finally:
            with pg_connection.engine.connect() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
                conn.commit()


@pytest.mark.integration
class TestParallelSchemaIsolation:
    """Test schema isolation with multiple concurrent connections."""

    def test_different_schemas_are_isolated(self, pg_connection, pg_logger):
        """Test that different schemas don't interfere with each other."""
        ts = int(time.time())
        pid = os.getpid()
        schema1 = f"test_iso1_{ts}_{pid}"
        schema2 = f"test_iso2_{ts}_{pid}"

        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = "isolation_test"
            id = Column(Integer, primary_key=True)
            source = Column(String(50))

        try:
            # Create two PG instances with different schemas
            pg1 = PG(pg_logger, pg_connection.cfg, schema=schema1)
            pg2 = PG(pg_logger, pg_connection.cfg, schema=schema2)

            pg1.create_schema()
            pg2.create_schema()

            pg1.migrate(Base)
            pg2.migrate(Base)

            # Insert different data in each schema
            with pg1.session() as s1:
                s1.execute(
                    text(
                        "INSERT INTO isolation_test (id, source) VALUES (1, 'schema1')"
                    )
                )
                s1.commit()

            with pg2.session() as s2:
                s2.execute(
                    text(
                        "INSERT INTO isolation_test (id, source) VALUES (1, 'schema2')"
                    )
                )
                s2.commit()

            # Each should see only its own data
            with pg1.session() as s1:
                result = s1.execute(
                    text("SELECT source FROM isolation_test WHERE id = 1")
                )
                assert result.scalar() == "schema1"

            with pg2.session() as s2:
                result = s2.execute(
                    text("SELECT source FROM isolation_test WHERE id = 1")
                )
                assert result.scalar() == "schema2"

        finally:
            with pg_connection.engine.connect() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema1}" CASCADE'))
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema2}" CASCADE'))
                conn.commit()

    def test_concurrent_inserts_to_different_schemas(self, pg_connection, pg_logger):
        """Test concurrent inserts to different schemas don't conflict."""
        ts = int(time.time())
        pid = os.getpid()
        schema1 = f"test_conc1_{ts}_{pid}"
        schema2 = f"test_conc2_{ts}_{pid}"

        Base = declarative_base()

        class Counter(Base):
            __tablename__ = "counter"
            id = Column(Integer, primary_key=True)
            count = Column(Integer, default=0)

        errors = []
        results = {}

        def insert_many(pg, schema_name, num_inserts):
            """Insert many rows in a schema."""
            try:
                for i in range(num_inserts):
                    with pg.session() as session:
                        session.execute(
                            text(f"INSERT INTO counter (id, count) VALUES ({i}, {i})")
                        )
                        session.commit()

                # Count total rows
                with pg.session() as session:
                    result = session.execute(text("SELECT COUNT(*) FROM counter"))
                    results[schema_name] = result.scalar()

            except Exception as e:
                errors.append((schema_name, e))

        try:
            pg1 = PG(pg_logger, pg_connection.cfg, schema=schema1)
            pg2 = PG(pg_logger, pg_connection.cfg, schema=schema2)

            pg1.create_schema()
            pg2.create_schema()
            pg1.migrate(Base)
            pg2.migrate(Base)

            # Run concurrent inserts
            t1 = threading.Thread(target=insert_many, args=(pg1, schema1, 50))
            t2 = threading.Thread(target=insert_many, args=(pg2, schema2, 50))

            t1.start()
            t2.start()

            t1.join(timeout=30)
            t2.join(timeout=30)

            # Check for errors
            assert not errors, f"Errors during concurrent inserts: {errors}"

            # Each schema should have exactly 50 rows
            assert results.get(schema1) == 50, (
                f"Schema1 has {results.get(schema1)} rows"
            )
            assert results.get(schema2) == 50, (
                f"Schema2 has {results.get(schema2)} rows"
            )

        finally:
            with pg_connection.engine.connect() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema1}" CASCADE'))
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema2}" CASCADE'))
                conn.commit()


@pytest.mark.integration
class TestSchemaFromConfig:
    """Test schema configuration via config object."""

    def test_schema_from_config_dict(self, pg_connection, pg_logger):
        """Test schema can be set via config dict."""
        schema_name = f"test_cfg_{int(time.time())}_{os.getpid()}"

        # Create config dict with schema
        config = dict(pg_connection.cfg)
        config["schema"] = schema_name

        try:
            pg = PG(pg_logger, config)

            assert pg.schema == schema_name

        finally:
            with pg_connection.engine.connect() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
                conn.commit()

    def test_schema_param_overrides_config(self, pg_connection, pg_logger):
        """Test schema parameter takes precedence over config."""
        config_schema = f"test_cfg_schema_{int(time.time())}_{os.getpid()}"
        param_schema = f"test_param_schema_{int(time.time())}_{os.getpid()}"

        config = dict(pg_connection.cfg)
        config["schema"] = config_schema

        try:
            pg = PG(pg_logger, config, schema=param_schema)

            # Parameter should win
            assert pg.schema == param_schema

        finally:
            with pg_connection.engine.connect() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{config_schema}" CASCADE'))
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{param_schema}" CASCADE'))
                conn.commit()


@pytest.mark.integration
class TestSchemaReset:
    """Test schema reset functionality."""

    def test_reset_schema_clears_all_tables(self, pg_connection, pg_logger):
        """Test reset_schema drops all tables in the schema."""
        schema_name = f"test_reset_{int(time.time())}_{os.getpid()}"

        Base = declarative_base()

        class TestModel(Base):
            __tablename__ = "reset_test"
            id = Column(Integer, primary_key=True)

        try:
            pg = PG(pg_logger, pg_connection.cfg, schema=schema_name)
            pg.create_schema()
            pg.migrate(Base)

            # Insert some data
            with pg.session() as session:
                session.execute(text("INSERT INTO reset_test (id) VALUES (1)"))
                session.commit()

            # Verify data exists
            with pg.session() as session:
                result = session.execute(text("SELECT COUNT(*) FROM reset_test"))
                assert result.scalar() == 1

            # Reset schema
            pg._schema_mgr.reset_schema()

            # Table should be gone
            with pg.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = :schema
                        """
                    ),
                    {"schema": schema_name},
                )
                count = result.scalar()
                assert count == 0, "Tables still exist after reset"

        finally:
            with pg_connection.engine.connect() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
                conn.commit()
