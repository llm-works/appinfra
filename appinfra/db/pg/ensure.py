"""
First-touch DDL helpers for PostgreSQL.

Concurrent workers that lazily create the same database object (embedding
tables, per-tenant partitions, materialized views, cache tables, application-
managed indexes) hit a first-touch race:

1. Two workers observe the target as missing (via SELECT or reflection).
2. Both fire ``CREATE ...``.
3. The loser raises ``duplicate_table`` / ``duplicate_object`` /
   ``unique_violation`` on ``pg_type_typname_nsp_index``, and the outer
   transaction ends up in ``InFailedSqlTransaction`` — not recoverable via
   naive ``try/except``.

Naive fixes fail in specific ways:

- ``CREATE ... IF NOT EXISTS`` — doesn't close the race in Postgres; two
  concurrent ``CREATE``\\ s still collide on catalog inserts.
- ``Table.create(checkfirst=True)`` — reflection is racy, and SAVEPOINT
  rollback does not reliably clear the aborted state under every session
  config.
- ``try/except IntegrityError/ProgrammingError`` — must savepoint-scope AND
  pgcode-filter (``23505``, ``42P07``, ``42710``) to avoid swallowing real
  errors (permission denied, missing extension, invalid DDL).

The right primitive is a Postgres transaction-scoped advisory lock keyed on
the object name (see :func:`with_object_lock`). It serializes concurrent
first-touches across every worker connected to the same cluster, auto-
releases at commit/rollback, and needs no exception juggling.

Existence checks in this module explicitly filter by ``pg_namespace.nspname``
rather than relying on ``pg_table_is_visible(oid)``, which resolves against
``search_path`` at query time and has produced false negatives for callers
that manage ``search_path`` per statement rather than per session.

Example — idempotent, race-safe on-demand CREATE::

    from appinfra.db.pg import ensure_object, table_exists

    with pg.session() as session:
        conn = session.connection()
        ensure_object(
            session,
            key=f"ensure:{schema}.{table_name}",
            exists_fn=lambda: table_exists(conn, table_name, schema=schema),
            create_fn=lambda: MyTable.__table__.create(conn),
        )
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session


@contextmanager
def with_object_lock(session: Session, key: str) -> Iterator[None]:
    """Serialize concurrent first-touch DDL on ``key`` across all workers.

    Acquires a Postgres transaction-scoped advisory lock derived from ``key``
    on the session's current connection. The lock is auto-released when the
    surrounding transaction commits or rolls back, so no explicit release is
    needed. The lock is cluster-scoped, so it serializes across every worker
    and node sharing one PG cluster — not just within a single process.

    Contention is limited to the first-touch path; once the target object
    exists, callers typically short-circuit before entering this block, so
    steady-state cost is zero.

    The session must be inside a transaction. In AUTOCOMMIT sessions each
    statement is its own transaction and the lock releases immediately,
    providing no serialization — do not use with AUTOCOMMIT sessions.

    Different keys map to independent locks, so distinct objects do not
    contend with each other. The key is hashed to int4 by ``hashtext``, so
    unrelated keys may hash-collide and needlessly serialize — this is a
    performance wart, never a correctness issue.

    Args:
        session: Transactional SQLAlchemy session (not AUTOCOMMIT).
        key: Stable string identifying the object being ensured. Choose a
            key that names the specific object, e.g.
            ``f"ensure:{schema}.{table_name}"``.

    Example:
        with with_object_lock(session, f"ensure:{table_name}"):
            if not table_exists(session.connection(), table_name):
                MyTable.__table__.create(session.connection())

    Raises:
        ValueError: If the session is configured with AUTOCOMMIT isolation.
    """
    conn = session.connection()
    iso = conn.get_execution_options().get("isolation_level")
    if iso == "AUTOCOMMIT":
        raise ValueError(
            "with_object_lock requires a transactional session; "
            "AUTOCOMMIT releases the lock immediately and provides no serialization"
        )
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": key},
    )
    yield


def ensure_object(
    session: Session,
    key: str,
    exists_fn: Callable[[], bool],
    create_fn: Callable[[], None],
) -> None:
    """Idempotent, race-safe check-and-create under a first-touch lock.

    Acquires :func:`with_object_lock` on ``key``, then calls ``exists_fn()``
    inside the lock and invokes ``create_fn()`` only if the object still
    does not exist. Re-checking inside the lock is what makes the pattern
    race-free: the loser of the pre-lock check finds the object present
    once it holds the lock and does nothing.

    The session must be transactional. See :func:`with_object_lock` for the
    reason.

    Args:
        session: Transactional SQLAlchemy session (not AUTOCOMMIT).
        key: Stable string identifying the object; see
            :func:`with_object_lock`.
        exists_fn: Zero-argument callable returning ``True`` when the target
            object exists. Called once, inside the lock.
        create_fn: Zero-argument callable that performs the ``CREATE``.
            Called only when ``exists_fn()`` returns ``False``.

    Example:
        ensure_object(
            session,
            key=f"ensure:{schema}.{table_name}",
            exists_fn=lambda: table_exists(
                session.connection(), table_name, schema=schema
            ),
            create_fn=lambda: MyTable.__table__.create(session.connection()),
        )
    """
    with with_object_lock(session, key):
        if not exists_fn():
            create_fn()


def table_exists(conn: Connection, name: str, schema: str | None = None) -> bool:
    """Return ``True`` if a table named ``name`` exists.

    When ``schema`` is provided, the check filters
    ``pg_catalog.pg_namespace.nspname`` explicitly. When ``schema`` is
    ``None``, the check falls back to ``n.nspname = ANY(current_schemas(true))``
    (respects the session's ``search_path`` by name, without going through
    ``pg_table_is_visible(oid)``).

    ``pg_table_is_visible(oid)`` has produced false negatives for callers
    that manage ``search_path`` per statement rather than per session;
    filtering by ``nspname`` avoids that path.

    Args:
        conn: SQLAlchemy connection (or ``session.connection()``).
        name: Unqualified table name.
        schema: Namespace to scope the check to, or ``None`` to use the
            session's ``search_path``.

    Returns:
        ``True`` if the table exists in the given (or visible) schema.
    """
    if schema is not None:
        sql = text(
            "SELECT 1 FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = :name AND n.nspname = :schema "
            "AND c.relkind IN ('r', 'p')"
        )
        params: dict[str, Any] = {"name": name, "schema": schema}
    else:
        sql = text(
            "SELECT 1 FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = :name "
            "AND n.nspname = ANY(current_schemas(true)) "
            "AND c.relkind IN ('r', 'p')"
        )
        params = {"name": name}
    return conn.execute(sql, params).scalar() is not None


def index_exists(conn: Connection, name: str, schema: str | None = None) -> bool:
    """Return ``True`` if an index named ``name`` exists.

    When ``schema`` is provided, the check filters ``pg_indexes.schemaname``
    explicitly. When ``schema`` is ``None``, the check falls back to
    ``schemaname = ANY(current_schemas(true))`` (respects the session's
    ``search_path``, matching ``table_exists`` behavior).

    Args:
        conn: SQLAlchemy connection (or ``session.connection()``).
        name: Index name.
        schema: Namespace to scope the check to, or ``None`` to use the
            session's ``search_path``.

    Returns:
        ``True`` if the index exists in the given (or visible) schema.
    """
    if schema is not None:
        sql = text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :name AND schemaname = :schema"
        )
        params: dict[str, Any] = {"name": name, "schema": schema}
    else:
        sql = text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :name "
            "AND schemaname = ANY(current_schemas(true))"
        )
        params = {"name": name}
    return conn.execute(sql, params).scalar() is not None
