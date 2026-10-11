# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Integration tests for ORM objects returned out of PG.session().

session() commits and closes on exit, so returned objects are detached. By
default the exit commit does not expire them; expire_on_commit=True does.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm.exc import DetachedInstanceError

from appinfra.db.pg.pg import PG

pytestmark = pytest.mark.require_pg


class _Base(DeclarativeBase):
    """Declarative base for the test model."""


class _Item(_Base):
    """Single-table model used to round-trip one row."""

    __tablename__ = "returned_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32))


def _make_pg(pg_config: Any, pg_logger: Any, **overrides: Any) -> PG:
    """Create a PG on a fresh schema holding one _Item row."""
    cfg = {"url": pg_config.url, "pool_size": 2, "max_overflow": 2, **overrides}
    pg = PG(pg_logger, cfg, schema=f"returned_{uuid.uuid4().hex[:12]}")
    pg.create_schema()
    pg.migrate(_Base)
    with pg.session() as session:
        session.add(_Item(id=1, name="first"))
    return pg


@pytest.fixture
def make_pg(pg_config, pg_logger, pg_available) -> Generator[Any, None, None]:
    """Factory for schema-isolated PG instances, dropped after the test."""
    if not pg_available:
        pytest.skip("PostgreSQL not available")
    created: list[PG] = []

    def factory(**overrides: Any) -> PG:
        pg = _make_pg(pg_config, pg_logger, **overrides)
        created.append(pg)
        return pg

    yield factory
    for pg in created:
        pg._schema_mgr.drop_schema(cascade=True)
        pg._engine.dispose()


@pytest.mark.integration
class TestReturnedObjects:
    """ORM objects returned from session() in each mode."""

    def test_returned_object_readable_by_default(self, make_pg):
        """Exit commit does not expire objects, so loaded attributes stay readable."""
        pg = make_pg()

        with pg.session() as session:
            item = session.get(_Item, 1)

        assert item is not None
        assert item.name == "first"

    def test_returned_object_expired_when_configured(self, make_pg):
        """With expire_on_commit=True the detached object cannot be refreshed."""
        pg = make_pg(expire_on_commit=True)

        with pg.session() as session:
            item = session.get(_Item, 1)

        with pytest.raises(DetachedInstanceError):
            _ = item.name

    def test_returned_object_readable_in_autocommit_mode(self, make_pg):
        """AUTOCOMMIT sessions ignore expire_on_commit and never expire objects."""
        pg = make_pg(expire_on_commit=True)

        with pg.session(autocommit=True) as session:
            item = session.get(_Item, 1)

        assert item is not None
        assert item.name == "first"
