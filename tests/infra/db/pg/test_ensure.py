# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for first-touch DDL helpers in appinfra.db.pg.ensure.

Covers the SQL emitted by each helper and the branching behavior of
ensure_object using mock sessions/connections. Real PG behavior (advisory
lock serialization, catalog visibility) is covered by the integration
tests in tests/integration/test_pg_ensure.py.
"""

from unittest.mock import MagicMock

import pytest

from appinfra.db.pg import (
    ensure_object,
    index_exists,
    table_exists,
    with_object_lock,
)


def _executed_sql(mock: MagicMock, call_index: int = 0) -> str:
    """Return the compiled SQL text passed to ``execute`` on the mock."""
    return str(mock.execute.call_args_list[call_index].args[0])


def _executed_params(mock: MagicMock, call_index: int = 0) -> dict:
    """Return the bind params dict passed to ``execute`` on the mock."""
    return mock.execute.call_args_list[call_index].args[1]


@pytest.mark.unit
class TestWithObjectLock:
    """with_object_lock issues the advisory lock and yields."""

    def test_emits_pg_advisory_xact_lock(self):
        session = MagicMock()
        conn = session.connection.return_value

        with with_object_lock(session, "ensure:foo"):
            pass

        assert conn.execute.call_count == 1
        sql = _executed_sql(conn)
        assert "pg_advisory_xact_lock" in sql
        assert "hashtext(:k)" in sql

    def test_key_is_bound_as_parameter(self):
        """The key must be a bound parameter, never string-interpolated."""
        session = MagicMock()
        conn = session.connection.return_value

        with with_object_lock(session, "ensure:some.table"):
            pass

        assert _executed_params(conn) == {"k": "ensure:some.table"}
        # And it must not leak into the SQL text itself.
        assert "ensure:some.table" not in _executed_sql(conn)

    def test_yields_control_to_body(self):
        session = MagicMock()
        entered = False
        with with_object_lock(session, "k"):
            entered = True
        assert entered is True

    def test_lock_acquired_before_body_runs(self):
        """The advisory lock must be held before the caller's body executes."""
        session = MagicMock()
        conn = session.connection.return_value
        conn.get_execution_options.return_value = {}

        with with_object_lock(session, "k"):
            # By the time the body runs, exactly one execute must have fired
            # — the advisory lock itself.
            assert conn.execute.call_count == 1

    def test_rejects_autocommit_session(self):
        """AUTOCOMMIT sessions are rejected with a clear error."""
        session = MagicMock()
        conn = session.connection.return_value
        conn.get_execution_options.return_value = {"isolation_level": "AUTOCOMMIT"}

        with pytest.raises(ValueError, match="AUTOCOMMIT"):
            with with_object_lock(session, "k"):
                pass


@pytest.mark.unit
class TestEnsureObject:
    """ensure_object skips create_fn when exists_fn is True, else calls it."""

    def test_skips_create_when_object_exists(self):
        session = MagicMock()
        create_fn = MagicMock()

        ensure_object(
            session,
            key="ensure:t",
            exists_fn=lambda: True,
            create_fn=create_fn,
        )

        create_fn.assert_not_called()
        # The advisory lock still gets acquired.
        assert session.connection.return_value.execute.call_count == 1

    def test_calls_create_when_object_missing(self):
        session = MagicMock()
        create_fn = MagicMock()

        ensure_object(
            session,
            key="ensure:t",
            exists_fn=lambda: False,
            create_fn=create_fn,
        )

        create_fn.assert_called_once_with()

    def test_exists_check_runs_after_lock(self):
        """The recheck must happen *inside* the lock, not before it."""
        session = MagicMock()
        conn = session.connection.return_value
        calls: list[str] = []

        def exists_fn() -> bool:
            calls.append("exists")
            return False

        def create_fn() -> None:
            calls.append("create")

        # Record when the lock-SELECT fires.
        original_execute = conn.execute

        def tracked_execute(*args, **kwargs):
            calls.append("lock")
            return original_execute(*args, **kwargs)

        conn.execute = tracked_execute

        ensure_object(session, key="k", exists_fn=exists_fn, create_fn=create_fn)

        assert calls == ["lock", "exists", "create"]


@pytest.mark.unit
class TestTableExists:
    """table_exists emits an nspname-filtered catalog query."""

    def test_scoped_query_when_schema_given(self):
        conn = MagicMock()
        conn.execute.return_value.scalar.return_value = 1

        assert table_exists(conn, "my_table", schema="my_schema") is True

        sql = _executed_sql(conn)
        assert "pg_catalog.pg_class" in sql
        assert "pg_catalog.pg_namespace" in sql
        assert "n.nspname = :schema" in sql
        assert _executed_params(conn) == {"name": "my_table", "schema": "my_schema"}

    def test_filters_by_relkind_to_exclude_views_and_sequences(self):
        """Exclude views, sequences, indexes, etc. — only match real tables."""
        conn = MagicMock()
        conn.execute.return_value.scalar.return_value = 1

        table_exists(conn, "my_table", schema="public")

        sql = _executed_sql(conn)
        assert "relkind IN ('r', 'p')" in sql

    def test_fallback_uses_current_schemas_when_no_schema(self):
        conn = MagicMock()
        conn.execute.return_value.scalar.return_value = None

        assert table_exists(conn, "my_table") is False

        sql = _executed_sql(conn)
        # No pg_table_is_visible — that's the whole point.
        assert "pg_table_is_visible" not in sql
        assert "current_schemas(true)" in sql
        assert _executed_params(conn) == {"name": "my_table"}

    def test_returns_false_when_scalar_is_none(self):
        conn = MagicMock()
        conn.execute.return_value.scalar.return_value = None
        assert table_exists(conn, "t", schema="s") is False

    def test_returns_true_when_scalar_is_present(self):
        conn = MagicMock()
        conn.execute.return_value.scalar.return_value = 1
        assert table_exists(conn, "t", schema="s") is True


@pytest.mark.unit
class TestIndexExists:
    """index_exists uses pg_indexes with optional schemaname filter."""

    def test_scoped_query_when_schema_given(self):
        conn = MagicMock()
        conn.execute.return_value.scalar.return_value = 1

        assert index_exists(conn, "idx_foo", schema="my_schema") is True

        sql = _executed_sql(conn)
        assert "pg_indexes" in sql
        assert "indexname = :name" in sql
        assert "schemaname = :schema" in sql
        assert _executed_params(conn) == {"name": "idx_foo", "schema": "my_schema"}

    def test_fallback_uses_current_schemas_when_no_schema(self):
        """schema=None scopes to search_path, matching table_exists behavior."""
        conn = MagicMock()
        conn.execute.return_value.scalar.return_value = None

        assert index_exists(conn, "idx_foo") is False

        sql = _executed_sql(conn)
        assert "pg_indexes" in sql
        assert "current_schemas(true)" in sql
        assert _executed_params(conn) == {"name": "idx_foo"}
