"""
Tests for PostgreSQL schema isolation support.

Tests schema name validation, SchemaManager, and create_all_in_schema.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from appinfra.db.pg.schema import (
    SchemaManager,
    create_all_in_schema,
    validate_schema_name,
)


@pytest.mark.unit
class TestValidateSchemaName:
    """Test validate_schema_name function."""

    def test_valid_simple_name(self):
        """Test accepts simple lowercase name."""
        assert validate_schema_name("test") is True
        assert validate_schema_name("myschema") is True

    def test_valid_name_with_numbers(self):
        """Test accepts name with numbers (not at start)."""
        assert validate_schema_name("test123") is True
        assert validate_schema_name("schema2") is True

    def test_valid_name_with_underscores(self):
        """Test accepts name with underscores."""
        assert validate_schema_name("test_schema") is True
        assert validate_schema_name("my_test_schema") is True
        assert validate_schema_name("test_gw0") is True

    def test_valid_xdist_worker_schemas(self):
        """Test accepts typical pytest-xdist worker schema names."""
        assert validate_schema_name("test_gw0") is True
        assert validate_schema_name("test_gw1") is True
        assert validate_schema_name("test_master") is True

    def test_rejects_uppercase(self):
        """Test rejects names with uppercase letters."""
        assert validate_schema_name("Test") is False
        assert validate_schema_name("TEST") is False
        assert validate_schema_name("testSchema") is False

    def test_rejects_starting_with_number(self):
        """Test rejects names starting with number."""
        assert validate_schema_name("1test") is False
        assert validate_schema_name("123") is False

    def test_rejects_hyphens(self):
        """Test rejects names with hyphens (unlike extensions)."""
        assert validate_schema_name("test-schema") is False

    def test_rejects_special_characters(self):
        """Test rejects special characters."""
        assert validate_schema_name("test@schema") is False
        assert validate_schema_name("test$schema") is False
        assert validate_schema_name("test.schema") is False
        assert validate_schema_name("test schema") is False

    def test_rejects_empty_string(self):
        """Test rejects empty string."""
        assert validate_schema_name("") is False

    def test_rejects_starting_with_underscore(self):
        """Test rejects names starting with underscore."""
        assert validate_schema_name("_test") is False


@pytest.mark.unit
class TestSchemaManagerInit:
    """Test SchemaManager initialization."""

    def test_init_with_valid_schema(self):
        """Test initialization with valid schema name."""
        engine = Mock()
        logger = Mock()

        mgr = SchemaManager(engine, "test_schema", logger)

        assert mgr.schema == "test_schema"
        assert mgr.search_path == "test_schema, public"

    def test_init_sets_search_path_with_public(self):
        """Test search_path includes public for extension visibility."""
        engine = Mock()
        logger = Mock()

        mgr = SchemaManager(engine, "myschema", logger)

        assert "public" in mgr.search_path
        assert mgr.search_path == "myschema, public"

    def test_init_rejects_invalid_schema(self):
        """Test initialization rejects invalid schema names."""
        engine = Mock()
        logger = Mock()

        with pytest.raises(ValueError, match="Invalid schema name"):
            SchemaManager(engine, "Invalid-Schema", logger)

    def test_init_rejects_empty_schema(self):
        """Test initialization rejects empty schema name."""
        engine = Mock()
        logger = Mock()

        with pytest.raises(ValueError, match="Invalid schema name"):
            SchemaManager(engine, "", logger)


@pytest.mark.unit
class TestSchemaManagerListeners:
    """Test SchemaManager event listener management."""

    def test_setup_listeners_installs_events(self):
        """Test setup_listeners installs connect listener."""
        engine = Mock()
        logger = Mock()
        mgr = SchemaManager(engine, "test_schema", logger)

        with patch("appinfra.db.pg.schema.event") as mock_event:
            mgr.setup_listeners()

            # Verify connect listener was installed
            calls = mock_event.listens_for.call_args_list
            assert len(calls) == 1

            # Check 'connect' listener
            connect_call = [c for c in calls if c[0][1] == "connect"]
            assert len(connect_call) == 1

    def test_setup_listeners_is_idempotent(self):
        """Test calling setup_listeners twice only installs once."""
        engine = Mock()
        logger = Mock()
        mgr = SchemaManager(engine, "test_schema", logger)

        with patch("appinfra.db.pg.schema.event") as mock_event:
            mgr.setup_listeners()
            mgr.setup_listeners()  # Second call should be no-op

            # Should only have 1 call (connect), not 2
            calls = mock_event.listens_for.call_args_list
            assert len(calls) == 1

    def test_remove_listeners_removes_events(self):
        """Test remove_listeners removes installed listeners."""
        engine = Mock()
        logger = Mock()
        mgr = SchemaManager(engine, "test_schema", logger)

        with patch("appinfra.db.pg.schema.event") as mock_event:
            # Setup first
            mgr.setup_listeners()

            # Store the listener
            mgr._connect_listener = Mock()

            # Now remove
            mgr.remove_listeners()

            # Verify remove was called
            remove_calls = mock_event.remove.call_args_list
            assert len(remove_calls) == 1

    def test_remove_listeners_without_setup_is_noop(self):
        """Test remove_listeners without setup is a no-op."""
        engine = Mock()
        logger = Mock()
        mgr = SchemaManager(engine, "test_schema", logger)

        with patch("appinfra.db.pg.schema.event") as mock_event:
            mgr.remove_listeners()  # Should not raise

            assert mock_event.remove.call_count == 0

    def test_connect_listener_sets_search_path(self):
        """Test the connect event listener sets search_path correctly."""
        engine = Mock()
        logger = Mock()
        mgr = SchemaManager(engine, "test_schema", logger)

        # Capture the callbacks by mocking listens_for to return a passthrough decorator
        captured_callbacks = {}

        def mock_listens_for(target, event_name):
            def decorator(fn):
                captured_callbacks[event_name] = fn
                return fn

            return decorator

        with patch("appinfra.db.pg.schema.event.listens_for", mock_listens_for):
            mgr.setup_listeners()

        # Now invoke the captured connect callback with mock dbapi connection
        mock_dbapi_conn = Mock()
        mock_cursor = Mock()
        mock_dbapi_conn.cursor.return_value = mock_cursor

        captured_callbacks["connect"](mock_dbapi_conn, None)

        # Verify cursor was used to set search_path
        mock_dbapi_conn.cursor.assert_called_once()
        mock_cursor.execute.assert_called_once_with(
            'SET search_path TO "test_schema", public'
        )
        mock_cursor.close.assert_called_once()


@pytest.mark.unit
class TestSchemaManagerDDL:
    """Test SchemaManager DDL operations (create, drop, reset)."""

    def test_create_schema_executes_create_statement(self):
        """Test create_schema executes CREATE SCHEMA IF NOT EXISTS."""
        engine = Mock()
        mock_conn = MagicMock()
        engine.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = Mock(return_value=None)
        logger = Mock()

        mgr = SchemaManager(engine, "test_schema", logger)
        mgr.create_schema()

        # Verify SQL was executed
        mock_conn.execute.assert_called_once()
        sql_call = str(mock_conn.execute.call_args[0][0])
        assert "CREATE SCHEMA IF NOT EXISTS" in sql_call
        assert '"test_schema"' in sql_call

    def test_drop_schema_executes_drop_statement(self):
        """Test drop_schema executes DROP SCHEMA IF EXISTS."""
        engine = Mock()
        mock_conn = MagicMock()
        engine.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = Mock(return_value=None)
        logger = Mock()

        mgr = SchemaManager(engine, "test_schema", logger)
        mgr.drop_schema()

        mock_conn.execute.assert_called_once()
        sql_call = str(mock_conn.execute.call_args[0][0])
        assert "DROP SCHEMA IF EXISTS" in sql_call
        assert '"test_schema"' in sql_call
        assert "CASCADE" in sql_call

    def test_drop_schema_without_cascade(self):
        """Test drop_schema without cascade option."""
        engine = Mock()
        mock_conn = MagicMock()
        engine.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = Mock(return_value=None)
        logger = Mock()

        mgr = SchemaManager(engine, "test_schema", logger)
        mgr.drop_schema(cascade=False)

        sql_call = str(mock_conn.execute.call_args[0][0])
        assert "CASCADE" not in sql_call

    def test_reset_schema_drops_and_creates(self):
        """Test reset_schema drops then creates schema."""
        engine = Mock()
        mock_conn = MagicMock()
        engine.connect.return_value.__enter__ = Mock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = Mock(return_value=None)
        logger = Mock()

        mgr = SchemaManager(engine, "test_schema", logger)
        mgr.reset_schema()

        # Should have 2 execute calls (drop + create)
        assert mock_conn.execute.call_count == 2

        calls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
        assert any("DROP SCHEMA" in c for c in calls)
        assert any("CREATE SCHEMA" in c for c in calls)


@pytest.mark.unit
class TestCreateAllInSchema:
    """Test create_all_in_schema function."""

    def test_temporarily_sets_schema_on_tables(self):
        """Test function temporarily sets schema attribute on tables."""
        # Create mock base and tables
        mock_table1 = Mock()
        mock_table1.schema = None
        mock_table2 = Mock()
        mock_table2.schema = None

        mock_metadata = Mock()
        mock_metadata.tables = {"table1": mock_table1, "table2": mock_table2}
        mock_metadata.create_all = Mock()

        mock_base = Mock()
        mock_base.metadata = mock_metadata

        engine = Mock()

        create_all_in_schema(mock_base, engine, "test_schema")

        # After function completes, schemas should be restored to None
        assert mock_table1.schema is None
        assert mock_table2.schema is None

        # create_all should have been called
        mock_metadata.create_all.assert_called_once_with(engine)

    def test_restores_original_schema_on_error(self):
        """Test function restores original schema even if create_all fails."""
        mock_table = Mock()
        mock_table.schema = "original_schema"

        mock_metadata = Mock()
        mock_metadata.tables = {"table1": mock_table}
        mock_metadata.create_all = Mock(side_effect=Exception("DB error"))

        mock_base = Mock()
        mock_base.metadata = mock_metadata

        engine = Mock()

        with pytest.raises(Exception, match="DB error"):
            create_all_in_schema(mock_base, engine, "test_schema")

        # Schema should be restored even after error
        assert mock_table.schema == "original_schema"

    def test_handles_empty_metadata(self):
        """Test function handles base with no tables."""
        mock_metadata = Mock()
        mock_metadata.tables = {}
        mock_metadata.create_all = Mock()

        mock_base = Mock()
        mock_base.metadata = mock_metadata

        engine = Mock()

        create_all_in_schema(mock_base, engine, "test_schema")

        mock_metadata.create_all.assert_called_once_with(engine)

    def test_rejects_invalid_schema_name(self):
        """Test function rejects invalid schema names."""
        mock_base = Mock()
        engine = Mock()

        with pytest.raises(ValueError, match="Invalid schema name"):
            create_all_in_schema(mock_base, engine, "Invalid-Schema")

    def test_rejects_empty_schema_name(self):
        """Test function rejects empty schema name."""
        mock_base = Mock()
        engine = Mock()

        with pytest.raises(ValueError, match="Invalid schema name"):
            create_all_in_schema(mock_base, engine, "")
