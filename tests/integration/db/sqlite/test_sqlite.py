# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for the SQLite database interface against a file-backed database.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm.exc import DetachedInstanceError

from appinfra.db.sqlite import SQLite


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    logger = Mock()
    logger.debug = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    return logger


def _sqlite_with_row(mock_logger, tmp_path, **cfg_fields):
    """Create a file-backed SQLite holding one row, plus its mapped class."""
    Base = declarative_base()

    class Item(Base):
        __tablename__ = "items"
        id = Column(Integer, primary_key=True)
        name = Column(String(32))

    config = SimpleNamespace(url=f"sqlite:///{tmp_path / 'items.db'}", **cfg_fields)
    with patch(
        "appinfra.db.sqlite.sqlite.LoggerFactory.derive", return_value=mock_logger
    ):
        db = SQLite(mock_logger, config)
    db.migrate(Base)
    with db.session() as session:
        session.add(Item(id=1, name="first"))
    return db, Item


class TestSQLiteReturnedObjects:
    """ORM objects returned out of session()."""

    def test_returned_object_readable_by_default(self, mock_logger, tmp_path):
        """Exit commit does not expire objects, so loaded attributes stay readable."""
        db, Item = _sqlite_with_row(mock_logger, tmp_path)

        with db.session() as session:
            item = session.get(Item, 1)
        db.dispose()

        assert item.name == "first"

    def test_returned_object_expired_when_configured(self, mock_logger, tmp_path):
        """With expire_on_commit=True the detached object cannot be refreshed."""
        db, Item = _sqlite_with_row(mock_logger, tmp_path, expire_on_commit=True)

        with db.session() as session:
            item = session.get(Item, 1)
        db.dispose()

        with pytest.raises(DetachedInstanceError):
            _ = item.name
