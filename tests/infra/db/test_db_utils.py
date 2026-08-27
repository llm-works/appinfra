# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for database utilities.

Tests session detachment utilities for safely using ORM objects
after session close.
"""

from unittest.mock import Mock, patch

import pytest

from appinfra.db.utils import detach, detach_all


@pytest.fixture
def mock_mapper():
    """Create mock mapper with columns."""
    col1 = Mock()
    col1.key = "id"
    col2 = Mock()
    col2.key = "name"
    col3 = Mock()
    col3.key = "email"

    mapper = Mock()
    mapper.columns = [col1, col2, col3]
    return mapper


@pytest.fixture
def mock_session():
    """Create mock session."""
    session = Mock()
    session.expunge = Mock()
    return session


@pytest.fixture
def mock_obj():
    """Create mock ORM object."""
    obj = Mock()
    obj.id = 1
    obj.name = "test"
    obj.email = "test@example.com"
    return obj


@pytest.mark.unit
class TestDetach:
    """Test detach function."""

    def test_returns_none_for_none_input(self, mock_session):
        """Test returns None when input is None."""
        result = detach(None, mock_session)

        assert result is None
        mock_session.expunge.assert_not_called()

    def test_loads_all_column_attributes(self, mock_obj, mock_session, mock_mapper):
        """Test forces loading of all column attributes."""
        with patch("appinfra.db.utils.inspect", return_value=mock_mapper):
            with patch("appinfra.db.utils.make_transient"):
                detach(mock_obj, mock_session)

        # Verify all columns were accessed
        assert mock_obj.id == 1
        assert mock_obj.name == "test"
        assert mock_obj.email == "test@example.com"

    def test_expunges_object_from_session(self, mock_obj, mock_session, mock_mapper):
        """Test expunges object from session."""
        with patch("appinfra.db.utils.inspect", return_value=mock_mapper):
            with patch("appinfra.db.utils.make_transient"):
                detach(mock_obj, mock_session)

        mock_session.expunge.assert_called_once_with(mock_obj)

    def test_makes_object_transient(self, mock_obj, mock_session, mock_mapper):
        """Test marks object as transient."""
        with patch("appinfra.db.utils.inspect", return_value=mock_mapper):
            with patch("appinfra.db.utils.make_transient") as mock_make_transient:
                detach(mock_obj, mock_session)

        mock_make_transient.assert_called_once_with(mock_obj)

    def test_returns_detached_object(self, mock_obj, mock_session, mock_mapper):
        """Test returns the detached object."""
        with patch("appinfra.db.utils.inspect", return_value=mock_mapper):
            with patch("appinfra.db.utils.make_transient"):
                result = detach(mock_obj, mock_session)

        assert result is mock_obj


@pytest.mark.unit
class TestDetachAll:
    """Test detach_all function."""

    def test_empty_list_returns_empty_list(self, mock_session):
        """Test returns empty list for empty input."""
        result = detach_all([], mock_session)

        assert result == []

    def test_detaches_all_objects(self, mock_session, mock_mapper):
        """Test detaches all objects in list."""
        obj1 = Mock(id=1, name="one")
        obj2 = Mock(id=2, name="two")
        obj3 = Mock(id=3, name="three")

        with patch("appinfra.db.utils.inspect", return_value=mock_mapper):
            with patch("appinfra.db.utils.make_transient"):
                result = detach_all([obj1, obj2, obj3], mock_session)

        assert len(result) == 3
        assert mock_session.expunge.call_count == 3

    def test_preserves_order(self, mock_session, mock_mapper):
        """Test preserves order of objects."""
        obj1 = Mock(id=1)
        obj2 = Mock(id=2)

        with patch("appinfra.db.utils.inspect", return_value=mock_mapper):
            with patch("appinfra.db.utils.make_transient"):
                result = detach_all([obj1, obj2], mock_session)

        assert result[0] is obj1
        assert result[1] is obj2
