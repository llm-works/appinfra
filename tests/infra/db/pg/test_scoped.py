"""
Tests for ScopedPG - per-operation schema selection.

Tests schema name validation, session context manager behavior,
ensure_schema(), and multi-schema isolation.
"""

from unittest.mock import MagicMock, Mock

import pytest

from appinfra.db.pg.scoped import ScopedPG


@pytest.mark.unit
class TestScopedPGInit:
    """Test ScopedPG initialization."""

    def test_init_with_valid_schema(self):
        """Test initialization with valid schema name."""
        mock_pg = MagicMock()
        mock_lg = MagicMock()

        scoped = ScopedPG(mock_lg, mock_pg, "test_schema")

        assert scoped.schema == "test_schema"
        assert scoped._pg is mock_pg
        assert scoped._lg is mock_lg

    def test_init_with_invalid_schema_raises(self):
        """Test initialization with invalid schema name raises ValueError."""
        mock_pg = MagicMock()
        mock_lg = MagicMock()

        with pytest.raises(ValueError, match="Invalid schema name"):
            ScopedPG(mock_lg, mock_pg, "Invalid-Schema")

    def test_init_rejects_uppercase(self):
        """Test uppercase schema names are rejected."""
        mock_pg = MagicMock()
        mock_lg = MagicMock()

        with pytest.raises(ValueError):
            ScopedPG(mock_lg, mock_pg, "TestSchema")

    def test_init_rejects_hyphens(self):
        """Test hyphenated schema names are rejected."""
        mock_pg = MagicMock()
        mock_lg = MagicMock()

        with pytest.raises(ValueError):
            ScopedPG(mock_lg, mock_pg, "test-schema")

    def test_init_rejects_starting_with_number(self):
        """Test schema names starting with number are rejected."""
        mock_pg = MagicMock()
        mock_lg = MagicMock()

        with pytest.raises(ValueError):
            ScopedPG(mock_lg, mock_pg, "1test")


@pytest.mark.unit
class TestScopedPGSession:
    """Test ScopedPG session context manager."""

    def test_session_sets_search_path(self):
        """Test session sets search_path on entry."""
        mock_session = MagicMock()
        mock_pg = MagicMock()
        mock_pg.session.return_value = mock_session
        mock_lg = MagicMock()

        scoped = ScopedPG(mock_lg, mock_pg, "my_schema")

        with scoped.session() as session:
            assert session is mock_session

        # Verify search_path was set
        mock_session.execute.assert_called()
        call_args = mock_session.execute.call_args[0][0]
        assert 'SET LOCAL search_path TO "my_schema", public' in str(call_args)

    def test_session_commits_on_success(self):
        """Test session commits on successful exit."""
        mock_session = MagicMock()
        mock_pg = MagicMock()
        mock_pg.session.return_value = mock_session
        mock_lg = MagicMock()

        scoped = ScopedPG(mock_lg, mock_pg, "my_schema")

        with scoped.session():
            pass

        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()
        mock_session.close.assert_called_once()

    def test_session_rollback_on_exception(self):
        """Test session rolls back on exception."""
        mock_session = MagicMock()
        mock_pg = MagicMock()
        mock_pg.session.return_value = mock_session
        mock_lg = MagicMock()

        scoped = ScopedPG(mock_lg, mock_pg, "my_schema")

        with pytest.raises(RuntimeError):
            with scoped.session():
                raise RuntimeError("test error")

        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()
        mock_session.close.assert_called_once()

    def test_session_logs_warning_on_rollback(self):
        """Test session logs warning when rolling back."""
        mock_session = MagicMock()
        mock_pg = MagicMock()
        mock_pg.session.return_value = mock_session
        mock_lg = MagicMock()

        scoped = ScopedPG(mock_lg, mock_pg, "my_schema")
        test_error = RuntimeError("test error")

        with pytest.raises(RuntimeError):
            with scoped.session():
                raise test_error

        mock_lg.warning.assert_called_once()
        call_kwargs = mock_lg.warning.call_args
        assert "session rollback" in call_kwargs[0][0]
        assert call_kwargs[1]["extra"]["exception"] is test_error

    def test_session_closes_even_on_commit_failure(self):
        """Test session closes even if commit raises."""
        mock_session = MagicMock()
        mock_session.commit.side_effect = RuntimeError("commit failed")
        mock_pg = MagicMock()
        mock_pg.session.return_value = mock_session
        mock_lg = MagicMock()

        scoped = ScopedPG(mock_lg, mock_pg, "my_schema")

        with pytest.raises(RuntimeError, match="commit failed"):
            with scoped.session():
                pass

        mock_session.close.assert_called_once()


@pytest.mark.unit
class TestScopedPGEnsureSchema:
    """Test ScopedPG ensure_schema method."""

    def test_ensure_schema_creates_schema(self):
        """Test ensure_schema creates schema if not exists."""
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = Mock(return_value=False)
        mock_pg = MagicMock()
        mock_pg.engine = mock_engine
        mock_pg.readonly = False
        mock_lg = MagicMock()

        scoped = ScopedPG(mock_lg, mock_pg, "new_schema")
        scoped.ensure_schema()

        # Verify CREATE SCHEMA was executed
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0][0]
        assert 'CREATE SCHEMA IF NOT EXISTS "new_schema"' in str(call_args)
        mock_conn.commit.assert_called_once()

    def test_ensure_schema_logs_info(self):
        """Test ensure_schema logs info message."""
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = Mock(return_value=False)
        mock_pg = MagicMock()
        mock_pg.engine = mock_engine
        mock_pg.readonly = False
        mock_lg = MagicMock()

        scoped = ScopedPG(mock_lg, mock_pg, "new_schema")
        scoped.ensure_schema()

        mock_lg.info.assert_called_once()
        call_kwargs = mock_lg.info.call_args
        assert "ensured schema exists" in call_kwargs[0][0]
        assert call_kwargs[1]["extra"]["schema"] == "new_schema"

    def test_ensure_schema_raises_on_readonly(self):
        """Test ensure_schema raises DatabaseError if PG is readonly."""
        from appinfra.exceptions import DatabaseError

        mock_pg = MagicMock()
        mock_pg.readonly = True
        mock_lg = MagicMock()

        scoped = ScopedPG(mock_lg, mock_pg, "new_schema")

        with pytest.raises(DatabaseError, match="readonly"):
            scoped.ensure_schema()


@pytest.mark.unit
class TestScopedPGProperties:
    """Test ScopedPG property accessors."""

    def test_schema_property(self):
        """Test schema property returns schema name."""
        mock_pg = MagicMock()
        mock_lg = MagicMock()

        scoped = ScopedPG(mock_lg, mock_pg, "test_schema")

        assert scoped.schema == "test_schema"

    def test_engine_property(self):
        """Test engine property returns PG engine."""
        mock_engine = MagicMock()
        mock_pg = MagicMock()
        mock_pg.engine = mock_engine
        mock_lg = MagicMock()

        scoped = ScopedPG(mock_lg, mock_pg, "test_schema")

        assert scoped.engine is mock_engine


@pytest.mark.unit
class TestPGScopedMethod:
    """Test PG.scoped() method."""

    def test_scoped_returns_scoped_pg(self):
        """Test PG.scoped() returns ScopedPG instance."""
        from appinfra.db.pg import PG

        # Create a minimal PG-like object to test scoped() method
        pg = object.__new__(PG)
        pg._lg = MagicMock()
        pg._engine = MagicMock()

        scoped = pg.scoped("test_schema")

        assert isinstance(scoped, ScopedPG)
        assert scoped.schema == "test_schema"
        assert scoped._pg is pg
