"""Tests for appinfra.db.pg.pg error handling and edge cases."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from appinfra.db.pg.connection import validate_readonly_config
from appinfra.db.pg.core import validate_init_params
from appinfra.db.pg.pg import PG
from appinfra.dot_dict import DotDict


@pytest.mark.unit
class TestPGValidation:
    """Test PG class input validation."""

    def testvalidate_init_params_rejects_none_logger(self):
        """Test that validate_init_params raises ValueError for None logger."""
        mock_cfg = Mock()

        with pytest.raises(ValueError) as exc_info:
            validate_init_params(None, mock_cfg)

        assert "Logger cannot be None" in str(exc_info.value)

    def testvalidate_init_params_rejects_none_config(self):
        """Test that validate_init_params raises ValueError for None config."""
        mock_logger = Mock()

        with pytest.raises(ValueError) as exc_info:
            validate_init_params(mock_logger, None)

        assert "Configuration cannot be None" in str(exc_info.value)

    def testvalidate_init_params_accepts_valid_inputs(self):
        """Test that validate_init_params accepts valid inputs."""
        mock_logger = Mock()
        mock_cfg = Mock()

        # Should not raise any exception
        validate_init_params(mock_logger, mock_cfg)

    def testvalidate_readonly_config_rejects_create_db_in_readonly(self):
        """Test that validate_readonly_config raises ValueError for create_db in readonly mode."""
        with pytest.raises(ValueError) as exc_info:
            validate_readonly_config(readonly=True, create_db=True)

        assert "Cannot create database in readonly mode" in str(exc_info.value)

    def testvalidate_readonly_config_accepts_valid_combinations(self):
        """Test that validate_readonly_config accepts valid combinations."""
        # Should not raise any exception
        validate_readonly_config(readonly=False, create_db=True)
        validate_readonly_config(readonly=False, create_db=False)
        validate_readonly_config(readonly=True, create_db=False)


@pytest.mark.unit
class TestPGHelperFunctions:
    """Test PG helper functions."""

    def testcreate_sqlalchemy_engine_with_nullpool(self):
        """Test that create_sqlalchemy_engine creates engine with NullPool."""
        import sqlalchemy

        from appinfra.db.pg.core import create_sqlalchemy_engine

        # Create an in-memory SQLite engine for testing
        engine = create_sqlalchemy_engine("sqlite:///:memory:")

        # Verify it's an engine
        assert isinstance(engine, sqlalchemy.engine.Engine)

        # Verify NullPool is used
        assert isinstance(engine.pool, sqlalchemy.pool.NullPool)

    def testinitialize_performance_cache(self):
        """Test that initialize_performance_cache sets dialect and regex."""
        import re

        import sqlalchemy

        from appinfra.db.pg.core import initialize_performance_cache

        # Create a mock PG instance
        mock_pg = Mock()
        mock_engine = sqlalchemy.create_engine("sqlite:///:memory:")
        mock_pg._engine = mock_engine

        # Initialize cache
        initialize_performance_cache(mock_pg)

        # Verify dialect was cached
        assert mock_pg._dialect == mock_engine.dialect

        # Verify regex was cached
        assert hasattr(mock_pg, "_cached_regex")
        assert isinstance(mock_pg._cached_regex, re.Pattern)

    def testcreate_engine_and_session(self):
        """Test that create_engine_and_session creates engine and session."""
        import sqlalchemy

        from appinfra.db.pg.core import create_engine_and_session

        # Create mock config
        mock_cfg = Mock()
        mock_cfg.url = "sqlite:///:memory:"

        # Create engine and session
        engine, session_cls = create_engine_and_session(mock_cfg)

        # Verify engine was created
        assert isinstance(engine, sqlalchemy.engine.Engine)

        # Verify NullPool was used
        assert isinstance(engine.pool, sqlalchemy.pool.NullPool)

        # Verify session maker was created
        assert callable(session_cls)


@pytest.mark.unit
class TestPGErrorHandlers:
    """Test PG error handling functions."""

    def testlog_query_with_timing_normal_case(self):
        """Test log_query_with_timing in normal case."""
        from appinfra.db.pg.core import log_query_with_timing

        # Create mock logger
        mock_logger = Mock()
        mock_logger.isEnabledFor = Mock(return_value=True)
        mock_logger._log = Mock()

        # Call function
        log_query_with_timing(
            mock_logger, 10, 0.5, "SELECT 1", "postgresql://localhost"
        )

        # Verify logging was called
        mock_logger.isEnabledFor.assert_called_once_with(10)
        mock_logger._log.assert_called_once()

    def testlog_query_with_timing_exception_fallback(self):
        """Test log_query_with_timing fallback to stderr on exception (lines 125-131)."""
        import sys
        from io import StringIO

        from appinfra.db.pg.core import log_query_with_timing

        # Create mock logger that raises exception
        mock_logger = Mock()
        mock_logger.isEnabledFor = Mock(side_effect=Exception("Logger error"))

        # Capture stderr
        captured_stderr = StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured_stderr

        try:
            # Call function - should catch exception and write to stderr
            log_query_with_timing(
                mock_logger, 10, 0.5, "SELECT 1", "postgresql://localhost"
            )

            # Verify stderr was written
            stderr_output = captured_stderr.getvalue()
            assert "UNABLE TO LOG" in stderr_output
            assert "Logger error" in stderr_output

        finally:
            sys.stderr = old_stderr

    def testhandle_sqlalchemy_error_logs_and_raises(self):
        """Test handle_sqlalchemy_error logs error and re-raises."""
        from appinfra.db.pg.connection import handle_sqlalchemy_error

        # Create mocks
        mock_logger = Mock()
        lg_extra = {"url": "postgresql://localhost"}
        error = Exception("Connection failed")

        # Call function within exception context - should re-raise
        with pytest.raises(Exception) as exc_info:
            try:
                raise error
            except Exception as e:
                handle_sqlalchemy_error(mock_logger, lg_extra, e, 0.0)

        # Verify error was logged
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert "failed to connect to db" in call_args[0]

        # Verify original exception was raised
        assert exc_info.value is error

    def testhandle_general_error_logs_and_wraps(self):
        """Test handle_general_error logs and wraps in SQLAlchemyError."""
        import sqlalchemy.exc

        from appinfra.db.pg.connection import handle_general_error

        # Create mocks
        mock_logger = Mock()
        lg_extra = {"url": "postgresql://localhost"}
        error = ValueError("Unexpected error")

        # Call function - should wrap and raise
        with pytest.raises(sqlalchemy.exc.SQLAlchemyError) as exc_info:
            handle_general_error(mock_logger, lg_extra, error, 0.0)

        # Verify error was logged
        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args
        assert "unexpected error connecting to db" in call_args[0]

        # Verify exception was wrapped
        assert "Database connection failed" in str(exc_info.value)
        assert exc_info.value.__cause__ is error


@pytest.mark.unit
class TestPGDictConfig:
    """Test PG class dict config normalization."""

    @patch("appinfra.db.pg.pg.LoggerFactory")
    @patch.object(PG, "_create_managers")
    @patch.object(PG, "_initialize_subsystems")
    @patch.object(PG, "_create_engine_and_session")
    def test_pg_accepts_dict_config(
        self,
        mock_create_engine,
        mock_init_subsystems,
        mock_create_managers,
        mock_logger_factory,
    ):
        """Test that PG accepts dict config and normalizes it to DotDict."""
        mock_logger = Mock()
        mock_logger_factory.derive.return_value = mock_logger

        dict_config = {
            "url": "postgresql://user:pass@localhost/testdb",
            "create_db": True,
            "readonly": False,
        }

        pg = PG(mock_logger, dict_config)

        # Verify config was normalized to DotDict
        assert isinstance(pg._cfg, DotDict)
        assert pg._cfg.url == "postgresql://user:pass@localhost/testdb"
        assert pg._cfg.create_db is True
        assert pg._cfg.readonly is False

    @patch("appinfra.db.pg.pg.LoggerFactory")
    @patch.object(PG, "_create_managers")
    @patch.object(PG, "_initialize_subsystems")
    @patch.object(PG, "_create_engine_and_session")
    def test_pg_preserves_object_config(
        self,
        mock_create_engine,
        mock_init_subsystems,
        mock_create_managers,
        mock_logger_factory,
    ):
        """Test that PG preserves object config without converting."""
        mock_logger = Mock()
        mock_logger_factory.derive.return_value = mock_logger

        object_config = SimpleNamespace(
            url="postgresql://user:pass@localhost/testdb",
            create_db=False,
        )

        pg = PG(mock_logger, object_config)

        # Verify config was preserved as-is
        assert pg._cfg is object_config

    @patch("appinfra.db.pg.pg.LoggerFactory")
    @patch.object(PG, "_create_managers")
    @patch.object(PG, "_initialize_subsystems")
    @patch.object(PG, "_create_engine_and_session")
    def test_dict_config_create_db_accessible_via_getattr(
        self,
        mock_create_engine,
        mock_init_subsystems,
        mock_create_managers,
        mock_logger_factory,
    ):
        """Test that dict config values are accessible via getattr after normalization."""
        mock_logger = Mock()
        mock_logger_factory.derive.return_value = mock_logger

        dict_config = {
            "url": "postgresql://user:pass@localhost/testdb",
            "create_db": True,
            "pool_size": 10,
        }

        pg = PG(mock_logger, dict_config)

        # Verify getattr works as expected (this was the original bug)
        assert getattr(pg._cfg, "create_db", False) is True
        assert getattr(pg._cfg, "pool_size", 5) == 10
        assert getattr(pg._cfg, "missing_key", "default") == "default"


@pytest.mark.unit
class TestPGLifecycleHooks:
    """Test PG lifecycle hook registration."""

    @patch("appinfra.db.pg.pg.LoggerFactory")
    @patch.object(PG, "_create_managers")
    @patch.object(PG, "_initialize_subsystems")
    @patch.object(PG, "_create_engine_and_session")
    def test_hook_lists_initialized_empty(
        self,
        mock_create_engine,
        mock_init_subsystems,
        mock_create_managers,
        mock_logger_factory,
    ):
        """Test that hook lists are initialized as empty."""
        mock_logger = Mock()
        mock_logger_factory.derive.return_value = mock_logger

        pg = PG(mock_logger, {"url": "postgresql://localhost/testdb"})

        assert pg._before_migrate_hooks == []
        assert pg._after_migrate_hooks == []

    @patch("appinfra.db.pg.pg.LoggerFactory")
    @patch.object(PG, "_create_managers")
    @patch.object(PG, "_initialize_subsystems")
    @patch.object(PG, "_create_engine_and_session")
    def test_on_before_migrate_registers_hook(
        self,
        mock_create_engine,
        mock_init_subsystems,
        mock_create_managers,
        mock_logger_factory,
    ):
        """Test that on_before_migrate registers a hook."""
        mock_logger = Mock()
        mock_logger_factory.derive.return_value = mock_logger

        pg = PG(mock_logger, {"url": "postgresql://localhost/testdb"})

        def my_hook(conn):
            pass

        result = pg.on_before_migrate(my_hook)

        assert my_hook in pg._before_migrate_hooks
        assert result is my_hook  # Returns callback for decorator use

    @patch("appinfra.db.pg.pg.LoggerFactory")
    @patch.object(PG, "_create_managers")
    @patch.object(PG, "_initialize_subsystems")
    @patch.object(PG, "_create_engine_and_session")
    def test_on_after_migrate_registers_hook(
        self,
        mock_create_engine,
        mock_init_subsystems,
        mock_create_managers,
        mock_logger_factory,
    ):
        """Test that on_after_migrate registers a hook."""
        mock_logger = Mock()
        mock_logger_factory.derive.return_value = mock_logger

        pg = PG(mock_logger, {"url": "postgresql://localhost/testdb"})

        def my_hook(conn):
            pass

        result = pg.on_after_migrate(my_hook)

        assert my_hook in pg._after_migrate_hooks
        assert result is my_hook  # Returns callback for decorator use

    @patch("appinfra.db.pg.pg.LoggerFactory")
    @patch.object(PG, "_create_managers")
    @patch.object(PG, "_initialize_subsystems")
    @patch.object(PG, "_create_engine_and_session")
    def test_hooks_can_be_used_as_decorators(
        self,
        mock_create_engine,
        mock_init_subsystems,
        mock_create_managers,
        mock_logger_factory,
    ):
        """Test that hook methods work as decorators."""
        mock_logger = Mock()
        mock_logger_factory.derive.return_value = mock_logger

        pg = PG(mock_logger, {"url": "postgresql://localhost/testdb"})

        @pg.on_before_migrate
        def setup_schema(conn):
            pass

        @pg.on_after_migrate
        def seed_data(conn):
            pass

        assert setup_schema in pg._before_migrate_hooks
        assert seed_data in pg._after_migrate_hooks


@pytest.mark.unit
class TestPGExtensionValidation:
    """Test PG extension name validation."""

    @patch("appinfra.db.pg.pg.LoggerFactory")
    @patch.object(PG, "_create_managers")
    @patch.object(PG, "_initialize_subsystems")
    @patch.object(PG, "_create_engine_and_session")
    def test_valid_extension_names(
        self,
        mock_create_engine,
        mock_init_subsystems,
        mock_create_managers,
        mock_logger_factory,
    ):
        """Test that valid extension names pass validation."""
        mock_logger = Mock()
        mock_logger_factory.derive.return_value = mock_logger

        pg = PG(mock_logger, {"url": "postgresql://localhost/testdb"})

        valid_names = ["vector", "pg_trgm", "postgis", "timescaledb", "some-ext"]
        for name in valid_names:
            assert pg._is_valid_extension_name(name), f"{name} should be valid"

    @patch("appinfra.db.pg.pg.LoggerFactory")
    @patch.object(PG, "_create_managers")
    @patch.object(PG, "_initialize_subsystems")
    @patch.object(PG, "_create_engine_and_session")
    def test_invalid_extension_names(
        self,
        mock_create_engine,
        mock_init_subsystems,
        mock_create_managers,
        mock_logger_factory,
    ):
        """Test that invalid extension names fail validation."""
        mock_logger = Mock()
        mock_logger_factory.derive.return_value = mock_logger

        pg = PG(mock_logger, {"url": "postgresql://localhost/testdb"})

        invalid_names = [
            "Vector",  # uppercase
            "123ext",  # starts with number
            "ext.name",  # contains dot
            "ext name",  # contains space
            "ext;drop",  # contains semicolon (SQL injection attempt)
            "",  # empty
        ]
        for name in invalid_names:
            assert not pg._is_valid_extension_name(name), f"{name} should be invalid"

    @patch("appinfra.db.pg.pg.LoggerFactory")
    @patch.object(PG, "_create_managers")
    @patch.object(PG, "_initialize_subsystems")
    @patch.object(PG, "_create_engine_and_session")
    def test_create_extensions_skips_invalid(
        self,
        mock_create_engine,
        mock_init_subsystems,
        mock_create_managers,
        mock_logger_factory,
    ):
        """Test that _create_extensions skips invalid extension names."""
        mock_logger = Mock()
        mock_logger_factory.derive.return_value = mock_logger

        pg = PG(
            mock_logger,
            {"url": "postgresql://localhost/testdb", "extensions": ["Invalid_Ext"]},
        )
        pg._lg_extra = {}

        # Mock the engine.connect() context manager
        mock_conn = Mock()
        mock_context = Mock()
        mock_context.__enter__ = Mock(return_value=mock_conn)
        mock_context.__exit__ = Mock(return_value=False)
        pg._engine = Mock()
        pg._engine.connect.return_value = mock_context

        # Call _create_extensions
        pg._create_extensions()

        # Verify warning was logged for invalid name
        mock_logger.warning.assert_called_once()
        assert "skipping invalid extension" in mock_logger.warning.call_args[0][0]

        # Verify no execute was called (extension was skipped)
        mock_conn.execute.assert_not_called()

    @patch("appinfra.db.pg.pg.LoggerFactory")
    @patch.object(PG, "_create_managers")
    @patch.object(PG, "_initialize_subsystems")
    @patch.object(PG, "_create_engine_and_session")
    def test_create_extensions_creates_valid(
        self,
        mock_create_engine,
        mock_init_subsystems,
        mock_create_managers,
        mock_logger_factory,
    ):
        """Test that _create_extensions creates valid extensions."""
        mock_logger = Mock()
        mock_logger_factory.derive.return_value = mock_logger

        pg = PG(
            mock_logger,
            {
                "url": "postgresql://localhost/testdb",
                "extensions": ["pg_trgm", "vector"],
            },
        )
        pg._lg_extra = {}

        # Mock the engine.connect() context manager
        mock_conn = Mock()
        mock_context = Mock()
        mock_context.__enter__ = Mock(return_value=mock_conn)
        mock_context.__exit__ = Mock(return_value=False)
        pg._engine = Mock()
        pg._engine.connect.return_value = mock_context

        # Call _create_extensions
        pg._create_extensions()

        # Verify execute and commit were called for each extension (separate transactions)
        assert mock_conn.execute.call_count == 2
        assert mock_conn.commit.call_count == 2

    @patch("appinfra.db.pg.pg.LoggerFactory")
    @patch.object(PG, "_create_managers")
    @patch.object(PG, "_initialize_subsystems")
    @patch.object(PG, "_create_engine_and_session")
    def test_create_extensions_no_extensions(
        self,
        mock_create_engine,
        mock_init_subsystems,
        mock_create_managers,
        mock_logger_factory,
    ):
        """Test that _create_extensions does nothing with no extensions."""
        mock_logger = Mock()
        mock_logger_factory.derive.return_value = mock_logger

        pg = PG(mock_logger, {"url": "postgresql://localhost/testdb"})
        pg._engine = Mock()

        # Call _create_extensions
        pg._create_extensions()

        # Verify connect was never called (early return)
        pg._engine.connect.assert_not_called()


@pytest.fixture
def mocked_pg():
    """
    Build a PG with init dependencies patched out and managers stubbed.

    Yields the configured PG and unwinds the four patches when the test ends.
    Tests can override the cfg by calling the inner factory; the default cfg
    covers the common case.
    """
    with (
        patch("appinfra.db.pg.pg.LoggerFactory") as lf,
        patch.object(PG, "_create_managers"),
        patch.object(PG, "_initialize_subsystems"),
        patch.object(PG, "_create_engine_and_session"),
    ):

        def _build(cfg=None):
            mock_logger = Mock()
            lf.derive.return_value = mock_logger
            pg = PG(mock_logger, cfg or {"url": "postgresql://localhost/testdb"})
            pg._engine = Mock()
            pg._connection_mgr = Mock()
            pg._session_mgr = Mock()
            pg._reconnect_strategy = Mock()
            pg._schema_mgr = None
            return pg

        # Default-built instance; tests needing a custom cfg call _build(cfg=...)
        pg = _build()
        pg.build = _build  # type: ignore[attr-defined]
        yield pg


@pytest.mark.unit
class TestPGPropertiesAndDelegations:
    """Cover trivial property accessors and manager delegations."""

    def test_cfg_property_returns_stored_config(self, mocked_pg):
        pg = mocked_pg.build({"url": "postgresql://localhost/db", "extra": 1})
        assert pg.cfg is pg._cfg

    def test_url_property_stringifies_engine_url(self, mocked_pg):
        # Use a non-string object whose str() is well-defined, so we actually
        # verify the property calls str() on engine.url rather than passing it
        # through identity-style.
        url_obj = Mock()
        url_obj.__str__ = Mock(return_value="postgresql://localhost/db")
        mocked_pg._engine.url = url_obj
        assert mocked_pg.url == "postgresql://localhost/db"
        url_obj.__str__.assert_called_once()

    def test_engine_property_returns_underlying_engine(self, mocked_pg):
        assert mocked_pg.engine is mocked_pg._engine

    def test_schema_property_none_without_schema_mgr(self, mocked_pg):
        assert mocked_pg.schema is None

    def test_schema_property_returns_schema_when_mgr_present(self, mocked_pg):
        mocked_pg._schema_mgr = Mock(schema="my_schema")
        assert mocked_pg.schema == "my_schema"

    def test_create_schema_invokes_mgr(self, mocked_pg):
        mocked_pg._schema_mgr = Mock()
        mocked_pg.create_schema()
        mocked_pg._schema_mgr.create_schema.assert_called_once()

    def test_create_schema_noop_without_mgr(self, mocked_pg):
        mocked_pg.create_schema()  # Should not raise

    def test_connect_delegates_to_connection_mgr(self, mocked_pg):
        sentinel = Mock()
        mocked_pg._connection_mgr.connect.return_value = sentinel
        assert mocked_pg.connect() is sentinel
        mocked_pg._connection_mgr.connect.assert_called_once()

    def test_create_session_syncs_health_then_returns_session(self, mocked_pg):
        mocked_pg._reconnect_strategy.is_healthy.return_value = True
        sentinel = Mock()
        mocked_pg._session_mgr.session.return_value = sentinel
        assert mocked_pg._create_session() is sentinel
        mocked_pg._session_mgr.set_connection_health.assert_called_once_with(True)

    def test_health_check_delegates(self, mocked_pg):
        mocked_pg._connection_mgr.health_check.return_value = {"ok": True}
        assert mocked_pg.health_check() == {"ok": True}

    def test_get_pool_status_delegates(self, mocked_pg):
        mocked_pg._connection_mgr.get_pool_status.return_value = {"size": 5}
        assert mocked_pg.get_pool_status() == {"size": 5}

    def test_reconnect_syncs_health_and_returns_result(self, mocked_pg):
        mocked_pg._reconnect_strategy.reconnect.return_value = True
        mocked_pg._reconnect_strategy.is_healthy.return_value = True
        assert mocked_pg.reconnect(max_retries=3, initial_delay=0.1) is True
        mocked_pg._reconnect_strategy.reconnect.assert_called_once_with(3, 0.1)
        mocked_pg._session_mgr.set_connection_health.assert_called_once_with(True)

    def test_setup_query_logging_wires_callbacks_when_level_set(self, mocked_pg):
        mocked_pg._query_logger = Mock()
        mocked_pg._lg_extra = {"k": "v"}
        mocked_pg._setup_query_logging(query_lg_level="DEBUG")
        mocked_pg._query_logger.setup_callbacks.assert_called_once_with({"k": "v"})

    @patch("appinfra.db.pg.schema.SchemaManager")
    def test_initialize_schema_isolation_builds_schema_mgr(
        self, mock_schema_mgr_cls, mocked_pg
    ):
        cfg = SimpleNamespace(isolation_schema=None, schema="my_schema")
        mocked_pg._initialize_schema_isolation(schema=None, cfg=cfg)
        mock_schema_mgr_cls.assert_called_once()
        assert mocked_pg._schema_mgr is mock_schema_mgr_cls.return_value
        mocked_pg._schema_mgr.setup_listeners.assert_called_once()


@pytest.mark.unit
class TestDisposeROEngine:
    """Cover the _dispose_ro_engine helper used by the pg_connection_ro fixture.

    The disposal block was originally added to prevent the SQLAlchemy engine from
    hanging when RO event listeners stay registered. These tests pin the
    remove/dispose call sequence so future refactors can't silently drop it.
    """

    def _make_pg(
        self, *, with_listeners=("readonly", "after_execute", "before_cursor")
    ):
        pg = Mock(spec=["_engine"])
        pg._engine = Mock()
        for name in with_listeners:
            setattr(pg, f"_{name}_listener", Mock())
        return pg

    def test_noop_when_no_engine_attr(self):
        from tests.fixtures.pg_integration import _dispose_ro_engine

        pg = Mock(spec=[])  # no _engine attribute at all
        _dispose_ro_engine(pg)  # should not raise

    def test_noop_when_engine_is_none(self):
        from tests.fixtures.pg_integration import _dispose_ro_engine

        pg = Mock(spec=["_engine"])
        pg._engine = None
        _dispose_ro_engine(pg)  # should not raise

    @patch("sqlalchemy.event")
    def test_removes_all_listeners_then_disposes(self, mock_event):
        from tests.fixtures.pg_integration import _dispose_ro_engine

        pg = self._make_pg()
        _dispose_ro_engine(pg)

        mock_event.remove.assert_any_call(pg._engine, "begin", pg._readonly_listener)
        mock_event.remove.assert_any_call(
            pg._engine, "after_execute", pg._after_execute_listener
        )
        mock_event.remove.assert_any_call(
            pg._engine, "before_cursor_execute", pg._before_cursor_listener
        )
        assert mock_event.remove.call_count == 3
        pg._engine.dispose.assert_called_once()

    @patch("sqlalchemy.event")
    def test_skips_missing_listeners_but_still_disposes(self, mock_event):
        from tests.fixtures.pg_integration import _dispose_ro_engine

        # Only the readonly listener is present.
        pg = self._make_pg(with_listeners=("readonly",))
        _dispose_ro_engine(pg)

        mock_event.remove.assert_called_once_with(
            pg._engine, "begin", pg._readonly_listener
        )
        pg._engine.dispose.assert_called_once()
