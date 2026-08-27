# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Integration tests for first-touch DDL helpers against a real PostgreSQL.

Covers:

- ``table_exists`` / ``index_exists`` return correct results in real
  catalogs, in the default schema and in an explicit schema.
- ``ensure_object`` is idempotent — calling it twice creates one table.
- Concurrent workers racing on ``ensure_object`` produce exactly one
  successful CREATE with no ``duplicate_table`` propagating.

Run with:
    ~/.venv/bin/python -m pytest tests/integration/test_pg_ensure.py -v -s
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy import text

from appinfra.db.pg import ensure_object, index_exists, table_exists
from appinfra.db.pg.pg import PG

pytestmark = pytest.mark.require_pg


def _random_suffix() -> str:
    """Return a unique suffix for a per-test object name."""
    return uuid.uuid4().hex[:12]


@pytest.fixture
def ephemeral_table_name() -> str:
    """A unique table name; cleanup is left to the test module."""
    return f"appinfra_ensure_probe_{_random_suffix()}"


@pytest.fixture
def cleanup_public_object(pg_connection):
    """
    Return a callable that drops a public.<name> table + its indexes at
    teardown. Registered names are dropped even on test failure.
    """
    to_drop: list[str] = []

    def register(name: str) -> None:
        to_drop.append(name)

    yield register

    with pg_connection.session() as session:
        for name in to_drop:
            session.execute(text(f'DROP TABLE IF EXISTS public."{name}" CASCADE'))


@pytest.mark.integration
class TestExistenceChecks:
    """table_exists / index_exists against a real catalog."""

    def test_table_exists_false_before_create(
        self, pg_connection, ephemeral_table_name, cleanup_public_object
    ):
        cleanup_public_object(ephemeral_table_name)
        with pg_connection.session() as session:
            assert (
                table_exists(
                    session.connection(), ephemeral_table_name, schema="public"
                )
                is False
            )

    def test_table_exists_true_after_create(
        self, pg_connection, ephemeral_table_name, cleanup_public_object
    ):
        cleanup_public_object(ephemeral_table_name)
        with pg_connection.session() as session:
            session.execute(
                text(f'CREATE TABLE public."{ephemeral_table_name}" (id int)')
            )
            session.commit()
        with pg_connection.session() as session:
            assert (
                table_exists(
                    session.connection(), ephemeral_table_name, schema="public"
                )
                is True
            )

    def test_table_exists_scoped_to_schema(
        self, pg_connection, ephemeral_table_name, cleanup_public_object
    ):
        """A table in 'public' is not visible when scoped to a different schema."""
        cleanup_public_object(ephemeral_table_name)
        with pg_connection.session() as session:
            session.execute(
                text(f'CREATE TABLE public."{ephemeral_table_name}" (id int)')
            )
            session.commit()
        with pg_connection.session() as session:
            # Wrong-schema lookup must return False even though the name exists
            # in public.
            assert (
                table_exists(
                    session.connection(),
                    ephemeral_table_name,
                    schema="pg_catalog",
                )
                is False
            )

    def test_index_exists_roundtrip(
        self, pg_connection, ephemeral_table_name, cleanup_public_object
    ):
        cleanup_public_object(ephemeral_table_name)
        idx_name = f"idx_{ephemeral_table_name}_id"
        with pg_connection.session() as session:
            session.execute(
                text(f'CREATE TABLE public."{ephemeral_table_name}" (id int)')
            )
            session.execute(
                text(
                    f'CREATE INDEX "{idx_name}" ON public."{ephemeral_table_name}" (id)'
                )
            )
            session.commit()
        with pg_connection.session() as session:
            conn = session.connection()
            assert index_exists(conn, idx_name, schema="public") is True
            assert index_exists(conn, f"{idx_name}_missing", schema="public") is False

    def test_table_exists_schema_none_uses_search_path(
        self, pg_connection, ephemeral_table_name, cleanup_public_object
    ):
        """schema=None falls back to current_schemas(true)."""
        cleanup_public_object(ephemeral_table_name)
        with pg_connection.session() as session:
            session.execute(
                text(f'CREATE TABLE public."{ephemeral_table_name}" (id int)')
            )
            session.commit()
        with pg_connection.session() as session:
            conn = session.connection()
            # Default search_path includes public, so schema=None should find it.
            assert table_exists(conn, ephemeral_table_name) is True
            assert table_exists(conn, f"{ephemeral_table_name}_missing") is False

    def test_index_exists_schema_none_uses_search_path(
        self, pg_connection, ephemeral_table_name, cleanup_public_object
    ):
        """schema=None falls back to current_schemas(true)."""
        cleanup_public_object(ephemeral_table_name)
        idx_name = f"idx_{ephemeral_table_name}_id"
        with pg_connection.session() as session:
            session.execute(
                text(f'CREATE TABLE public."{ephemeral_table_name}" (id int)')
            )
            session.execute(
                text(
                    f'CREATE INDEX "{idx_name}" ON public."{ephemeral_table_name}" (id)'
                )
            )
            session.commit()
        with pg_connection.session() as session:
            conn = session.connection()
            # Default search_path includes public, so schema=None should find it.
            assert index_exists(conn, idx_name) is True
            assert index_exists(conn, f"{idx_name}_missing") is False


@pytest.mark.integration
class TestEnsureObjectIdempotent:
    """ensure_object twice on the same key creates one object."""

    def test_second_call_is_noop(
        self, pg_connection, ephemeral_table_name, cleanup_public_object
    ):
        cleanup_public_object(ephemeral_table_name)
        key = f"ensure:public.{ephemeral_table_name}"
        create_calls = 0

        def create_fn():
            nonlocal create_calls
            create_calls += 1
            session.execute(
                text(f'CREATE TABLE public."{ephemeral_table_name}" (id int)')
            )

        with pg_connection.session() as session:
            conn = session.connection()
            ensure_object(
                session,
                key=key,
                exists_fn=lambda: table_exists(
                    conn, ephemeral_table_name, schema="public"
                ),
                create_fn=create_fn,
            )
            # Second call in the same session must see the table and skip.
            ensure_object(
                session,
                key=key,
                exists_fn=lambda: table_exists(
                    conn, ephemeral_table_name, schema="public"
                ),
                create_fn=create_fn,
            )
            session.commit()

        assert create_calls == 1


@pytest.mark.integration
class TestEnsureObjectConcurrent:
    """Concurrent workers on the same key produce one CREATE."""

    def test_race_produces_one_create(
        self, pg_config, pg_logger, ephemeral_table_name, cleanup_public_object
    ):
        cleanup_public_object(ephemeral_table_name)
        key = f"ensure:public.{ephemeral_table_name}"
        n_workers = 8
        start_barrier = threading.Barrier(n_workers)
        # Second barrier inside create_fn forces workers to overlap while the
        # object is absent. Without it, one fast worker could finish before
        # others even acquire the lock, causing a false pass.
        create_barrier = threading.Barrier(n_workers, timeout=5)
        create_calls = 0
        create_lock = threading.Lock()

        def worker() -> None:
            # Each worker gets its own PG + connection pool → distinct sessions,
            # which is the actual production shape.
            pg = PG(pg_logger, pg_config)
            start_barrier.wait()  # release all workers at once
            with pg.session() as session:
                conn = session.connection()

                def create_fn():
                    nonlocal create_calls
                    # Wait for all workers to reach create_fn before any
                    # proceeds — ensures contention on the advisory lock.
                    try:
                        create_barrier.wait()
                    except threading.BrokenBarrierError:
                        pass  # Other workers already proceeded; fine.
                    with create_lock:
                        create_calls += 1
                    session.execute(
                        text(f'CREATE TABLE public."{ephemeral_table_name}" (id int)')
                    )

                ensure_object(
                    session,
                    key=key,
                    exists_fn=lambda: table_exists(
                        conn, ephemeral_table_name, schema="public"
                    ),
                    create_fn=create_fn,
                )

        errors: list[BaseException] = []
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = [pool.submit(worker) for _ in range(n_workers)]
            for f in as_completed(futures):
                try:
                    f.result()
                except BaseException as e:  # noqa: BLE001 — surface everything
                    errors.append(e)

        # No worker may see duplicate_table / InFailedSqlTransaction bubble up.
        assert errors == [], f"workers raised: {errors!r}"
        # Exactly one create_fn invocation, database-wide.
        assert create_calls == 1
        # Verify the table actually exists (DDL committed).
        pg = PG(pg_logger, pg_config)
        with pg.session() as session:
            assert table_exists(
                session.connection(), ephemeral_table_name, schema="public"
            )
