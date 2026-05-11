"""
Tests for ScopedPG - per-schema isolation with dedicated connection pool.

Tests schema name validation, delegation to internal PG, ensure_schema(),
and caching behavior.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from appinfra.db.pg import ScopedPG


@pytest.mark.unit
class TestScopedPGInit:
    """Test ScopedPG initialization and schema validation."""

    def test_init_rejects_invalid_schema(self):
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

    def test_init_creates_internal_pg_with_schema(self):
        """Test initialization creates internal PG with correct schema."""
        mock_parent_pg = MagicMock()
        mock_parent_pg.cfg = {"url": "postgresql://localhost/test"}
        mock_lg = MagicMock()

        with patch("appinfra.db.pg.pg.PG") as MockPG:
            mock_inner_pg = MagicMock()
            MockPG.return_value = mock_inner_pg

            scoped = ScopedPG(mock_lg, mock_parent_pg, "test_schema")

            # Verify internal PG was created with parent's config and schema
            MockPG.assert_called_once_with(
                mock_lg, mock_parent_pg.cfg, schema="test_schema"
            )
            assert scoped._pg is mock_inner_pg
            assert scoped._parent_pg is mock_parent_pg
            assert scoped.schema == "test_schema"


@pytest.mark.unit
class TestScopedPGSession:
    """Test ScopedPG session delegation."""

    def test_session_delegates_to_internal_pg(self):
        """Test session() delegates to internal PG's session()."""
        mock_parent_pg = MagicMock()
        mock_parent_pg.cfg = {}
        mock_lg = MagicMock()

        with patch("appinfra.db.pg.pg.PG") as MockPG:
            mock_inner_pg = MagicMock()
            mock_session = MagicMock()
            mock_inner_pg.session.return_value.__enter__ = Mock(
                return_value=mock_session
            )
            mock_inner_pg.session.return_value.__exit__ = Mock(return_value=False)
            MockPG.return_value = mock_inner_pg

            scoped = ScopedPG(mock_lg, mock_parent_pg, "my_schema")

            with scoped.session() as session:
                assert session is mock_session

            mock_inner_pg.session.assert_called_once_with(autocommit=False)

    def test_session_autocommit_delegates_to_internal_pg(self):
        """Test session(autocommit=True) delegates to internal PG."""
        mock_parent_pg = MagicMock()
        mock_parent_pg.cfg = {}
        mock_lg = MagicMock()

        with patch("appinfra.db.pg.pg.PG") as MockPG:
            mock_inner_pg = MagicMock()
            mock_session = MagicMock()
            mock_inner_pg.session.return_value.__enter__ = Mock(
                return_value=mock_session
            )
            mock_inner_pg.session.return_value.__exit__ = Mock(return_value=False)
            MockPG.return_value = mock_inner_pg

            scoped = ScopedPG(mock_lg, mock_parent_pg, "my_schema")

            with scoped.session(autocommit=True) as session:
                assert session is mock_session

            mock_inner_pg.session.assert_called_once_with(autocommit=True)


@pytest.mark.unit
class TestScopedPGEnsureSchema:
    """Test ScopedPG ensure_schema method."""

    def test_ensure_schema_uses_parent_engine(self):
        """Test ensure_schema creates schema using parent's engine."""
        mock_conn = MagicMock()
        mock_parent_engine = MagicMock()
        mock_parent_engine.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_parent_engine.connect.return_value.__exit__ = Mock(return_value=False)
        mock_parent_pg = MagicMock()
        mock_parent_pg.engine = mock_parent_engine
        mock_parent_pg.readonly = False
        mock_parent_pg.cfg = {}
        mock_lg = MagicMock()

        with patch("appinfra.db.pg.pg.PG"):
            scoped = ScopedPG(mock_lg, mock_parent_pg, "new_schema")
            scoped.ensure_schema()

        # Verify CREATE SCHEMA was executed on parent's engine
        mock_parent_engine.connect.assert_called_once()
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0][0]
        assert 'CREATE SCHEMA IF NOT EXISTS "new_schema"' in str(call_args)
        mock_conn.commit.assert_called_once()

    def test_ensure_schema_logs_trace(self):
        """Test ensure_schema logs trace message."""
        mock_conn = MagicMock()
        mock_parent_engine = MagicMock()
        mock_parent_engine.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        mock_parent_engine.connect.return_value.__exit__ = Mock(return_value=False)
        mock_parent_pg = MagicMock()
        mock_parent_pg.engine = mock_parent_engine
        mock_parent_pg.readonly = False
        mock_parent_pg.cfg = {}
        mock_lg = MagicMock()

        with patch("appinfra.db.pg.pg.PG"):
            scoped = ScopedPG(mock_lg, mock_parent_pg, "new_schema")
            scoped.ensure_schema()

        mock_lg.trace.assert_called_once()
        call_kwargs = mock_lg.trace.call_args
        assert "ensured schema exists" in call_kwargs[0][0]
        assert call_kwargs[1]["extra"]["schema"] == "new_schema"

    def test_ensure_schema_raises_on_readonly(self):
        """Test ensure_schema raises DatabaseError if parent PG is readonly."""
        from appinfra.errors import DatabaseError

        mock_parent_pg = MagicMock()
        mock_parent_pg.readonly = True
        mock_parent_pg.cfg = {}
        mock_lg = MagicMock()

        with patch("appinfra.db.pg.pg.PG"):
            scoped = ScopedPG(mock_lg, mock_parent_pg, "new_schema")

            with pytest.raises(DatabaseError, match="readonly"):
                scoped.ensure_schema()


@pytest.mark.unit
class TestScopedPGProperties:
    """Test ScopedPG property accessors."""

    def test_schema_property(self):
        """Test schema property returns schema name."""
        mock_parent_pg = MagicMock()
        mock_parent_pg.cfg = {}
        mock_lg = MagicMock()

        with patch("appinfra.db.pg.pg.PG"):
            scoped = ScopedPG(mock_lg, mock_parent_pg, "test_schema")

        assert scoped.schema == "test_schema"

    def test_engine_property_returns_inner_pg_engine(self):
        """Test engine property returns internal PG's engine."""
        mock_parent_pg = MagicMock()
        mock_parent_pg.cfg = {}
        mock_lg = MagicMock()

        with patch("appinfra.db.pg.pg.PG") as MockPG:
            mock_inner_engine = MagicMock()
            mock_inner_pg = MagicMock()
            mock_inner_pg.engine = mock_inner_engine
            MockPG.return_value = mock_inner_pg

            scoped = ScopedPG(mock_lg, mock_parent_pg, "test_schema")

            assert scoped.engine is mock_inner_engine

    def test_cfg_property_returns_inner_pg_cfg(self):
        """Test cfg property returns internal PG's config."""
        mock_parent_pg = MagicMock()
        mock_parent_pg.cfg = {"original": True}
        mock_lg = MagicMock()

        with patch("appinfra.db.pg.pg.PG") as MockPG:
            mock_inner_pg = MagicMock()
            mock_inner_pg.cfg = {"inherited": True}
            MockPG.return_value = mock_inner_pg

            scoped = ScopedPG(mock_lg, mock_parent_pg, "test_schema")

            assert scoped.cfg == {"inherited": True}


@pytest.mark.unit
class TestPGScopedCaching:
    """Test PG.scoped() caching behavior."""

    def test_scoped_caches_by_schema_name(self):
        """Test PG.scoped() returns cached instance for same schema."""
        import threading

        from appinfra.db.pg import PG

        # Create a minimal PG-like object with cache
        pg = object.__new__(PG)
        pg._lg = MagicMock()
        pg._cfg = {"url": "postgresql://localhost/test"}
        pg._scoped_cache = {}
        pg._scoped_cache_lock = threading.Lock()

        with patch("appinfra.db.pg.pg.ScopedPG") as MockScopedPG:
            mock_scoped = MagicMock()
            MockScopedPG.return_value = mock_scoped

            # First call creates new ScopedPG
            scoped1 = pg.scoped("test_schema")
            assert scoped1 is mock_scoped
            assert MockScopedPG.call_count == 1

            # Second call with same schema returns cached
            scoped2 = pg.scoped("test_schema")
            assert scoped2 is mock_scoped
            assert MockScopedPG.call_count == 1  # Not called again

    def test_scoped_creates_new_for_different_schemas(self):
        """Test PG.scoped() creates different instances for different schemas."""
        import threading

        from appinfra.db.pg import PG

        pg = object.__new__(PG)
        pg._lg = MagicMock()
        pg._cfg = {"url": "postgresql://localhost/test"}
        pg._scoped_cache = {}
        pg._scoped_cache_lock = threading.Lock()

        with patch("appinfra.db.pg.pg.ScopedPG") as MockScopedPG:
            mock_scoped_a = MagicMock()
            mock_scoped_b = MagicMock()
            MockScopedPG.side_effect = [mock_scoped_a, mock_scoped_b]

            scoped_a = pg.scoped("schema_a")
            scoped_b = pg.scoped("schema_b")

            assert scoped_a is mock_scoped_a
            assert scoped_b is mock_scoped_b
            assert MockScopedPG.call_count == 2

    def test_dispose_scoped_cache_disposes_all(self):
        """Test PG.dispose_scoped_cache() disposes all cached ScopedPG instances."""
        import threading

        from appinfra.db.pg import PG

        pg = object.__new__(PG)
        pg._lg = MagicMock()
        pg._scoped_cache = {}
        pg._scoped_cache_lock = threading.Lock()

        # Create mock scoped instances with mock engines
        mock_scoped_a = MagicMock()
        mock_scoped_a._pg._engine = MagicMock()
        mock_scoped_b = MagicMock()
        mock_scoped_b._pg._engine = MagicMock()

        pg._scoped_cache = {"schema_a": mock_scoped_a, "schema_b": mock_scoped_b}

        pg.dispose_scoped_cache()

        # Verify all engines were disposed
        mock_scoped_a._pg._engine.dispose.assert_called_once()
        mock_scoped_b._pg._engine.dispose.assert_called_once()
        # Verify cache was cleared
        assert pg._scoped_cache == {}
        pg._lg.trace.assert_called_once()


@pytest.mark.unit
class TestScopedPGDispose:
    """Test ScopedPG dispose method."""

    def test_dispose_cleans_up_resources(self):
        """Test ScopedPG.dispose() disposes engine and removes from cache."""
        mock_parent_pg = MagicMock()
        mock_parent_pg.cfg = {}
        mock_parent_pg._scoped_cache = {}
        mock_parent_pg._scoped_cache_lock = MagicMock()
        mock_parent_pg._scoped_cache_lock.__enter__ = Mock(return_value=None)
        mock_parent_pg._scoped_cache_lock.__exit__ = Mock(return_value=False)
        mock_lg = MagicMock()

        with patch("appinfra.db.pg.pg.PG") as MockPG:
            mock_inner_pg = MagicMock()
            mock_inner_pg._engine = MagicMock()
            MockPG.return_value = mock_inner_pg

            scoped = ScopedPG(mock_lg, mock_parent_pg, "test_schema")
            # Add to cache
            mock_parent_pg._scoped_cache["test_schema"] = scoped

            scoped.dispose()

            # Verify engine was disposed
            mock_inner_pg._engine.dispose.assert_called_once()
            # Verify removed from cache
            assert "test_schema" not in mock_parent_pg._scoped_cache
            mock_lg.trace.assert_called()
