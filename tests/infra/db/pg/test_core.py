# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Comprehensive tests for core PG utilities.

Tests configuration validation, query logging, event listeners, and initialization helpers.
"""

from unittest.mock import Mock, patch

import pytest
import sqlalchemy

from appinfra.db.pg.core import (
    ConfigValidator,
    QueryLogger,
    configure_readonly_mode,
    create_engine_and_session,
    create_sqlalchemy_engine,
    initialize_connection_health,
    initialize_logging_context,
    initialize_performance_cache,
    initialize_performance_optimizations,
    log_query_with_timing,
    validate_init_params,
)


@pytest.mark.unit
class TestConfigValidator:
    """Test ConfigValidator class."""

    def test_valid_postgresql_url(self):
        """Test accepts valid PostgreSQL URL."""
        cfg = Mock()
        cfg.url = "postgresql://user:pass@localhost/testdb"

        ConfigValidator.validate_config(cfg)  # Should not raise

    def test_valid_postgres_url(self):
        """Test accepts postgres:// scheme."""
        cfg = Mock()
        cfg.url = "postgres://localhost/testdb"

        ConfigValidator.validate_config(cfg)  # Should not raise

    def test_rejects_missing_url(self):
        """Test rejects config without URL."""
        cfg = Mock(spec=[])  # No url attribute

        with pytest.raises(ValueError, match="Database URL is required"):
            ConfigValidator.validate_config(cfg)

    def test_rejects_empty_url(self):
        """Test rejects empty URL."""
        cfg = Mock()
        cfg.url = ""

        with pytest.raises(ValueError, match="Database URL is required"):
            ConfigValidator.validate_config(cfg)

    def test_rejects_non_string_url(self):
        """Test rejects non-string URL."""
        cfg = Mock()
        cfg.url = 12345

        with pytest.raises(ValueError, match="must be a string"):
            ConfigValidator.validate_config(cfg)

    def test_rejects_invalid_scheme(self):
        """Test rejects URLs with wrong scheme."""
        cfg = Mock()
        cfg.url = "mysql://localhost/test"

        with pytest.raises(ValueError, match="must start with"):
            ConfigValidator.validate_config(cfg)

    def test_get_engine_kwargs_with_defaults(self):
        """Test get_engine_kwargs returns default values when attrs missing."""
        cfg = Mock(spec=[])  # Empty spec = no attributes

        kwargs = ConfigValidator.get_engine_kwargs(cfg)

        assert kwargs["pool_size"] == 5
        assert kwargs["max_overflow"] == 10
        assert kwargs["pool_timeout"] == 30
        assert kwargs["pool_recycle"] == 3600
        assert kwargs["pool_pre_ping"] is True
        assert kwargs["echo"] is False

    def test_get_engine_kwargs_with_custom_values(self):
        """Test get_engine_kwargs uses custom config values."""
        cfg = Mock()
        cfg.pool_size = 20
        cfg.max_overflow = 30

        kwargs = ConfigValidator.get_engine_kwargs(cfg)

        assert kwargs["pool_size"] == 20
        assert kwargs["max_overflow"] == 30

    def test_config_works_with_simple_namespace(self):
        """Test both methods work with SimpleNamespace config."""
        from types import SimpleNamespace

        cfg = SimpleNamespace(
            url="postgresql://localhost/testdb",
            pool_size=15,
            max_overflow=25,
        )

        # Both should work with same config object
        ConfigValidator.validate_config(cfg)  # Should not raise
        kwargs = ConfigValidator.get_engine_kwargs(cfg)

        assert kwargs["pool_size"] == 15
        assert kwargs["max_overflow"] == 25

    def test_config_works_with_dataclass(self):
        """Test both methods work with dataclass config."""
        from dataclasses import dataclass

        @dataclass
        class DBConfig:
            url: str
            pool_size: int = 10
            echo: bool = True

        cfg = DBConfig(url="postgresql://localhost/testdb")

        # Both should work with same config object
        ConfigValidator.validate_config(cfg)  # Should not raise
        kwargs = ConfigValidator.get_engine_kwargs(cfg)

        assert kwargs["pool_size"] == 10
        assert kwargs["echo"] is True


@pytest.mark.unit
class TestQueryLogger:
    """Test QueryLogger class."""

    def test_initialization(self):
        """Test QueryLogger initializes correctly."""
        engine = Mock()
        logger = Mock()

        query_logger = QueryLogger(engine, logger, query_lg_level=10)

        assert query_logger._engine == engine
        assert query_logger._lg == logger
        assert query_logger._query_lg_level == 10

    def test_format_query_string_normalizes_whitespace(self):
        """Test format_query_string normalizes whitespace."""
        engine = Mock()
        logger = Mock()
        query_logger = QueryLogger(engine, logger, query_lg_level=None)

        query = "SELECT\n  col1,\n\t col2\n FROM  table"
        formatted = query_logger.format_query_string(query)

        assert "\n" not in formatted
        assert "\t" not in formatted
        assert "  " not in formatted  # No double spaces

    def test_format_query_string_caching(self):
        """Test format_query_string caches results."""
        engine = Mock()
        logger = Mock()
        query_logger = QueryLogger(engine, logger, query_lg_level=None)

        query = "SELECT * FROM test"

        # Call multiple times
        result1 = query_logger.format_query_string(query)
        result2 = query_logger.format_query_string(query)

        # Should return same cached result
        assert result1 is result2

    def test_setup_callbacks_registers_listeners(self):
        """Test setup_callbacks registers event listeners."""
        engine = Mock()
        logger = Mock()
        query_logger = QueryLogger(engine, logger, query_lg_level=10)

        with patch("sqlalchemy.event.listen") as mock_listen:
            query_logger.setup_callbacks({"url": "test"})

            # Should register before_cursor_execute and after_execute
            assert mock_listen.call_count >= 1


@pytest.mark.unit
class TestLogQueryWithTiming:
    """Test log_query_with_timing function."""

    def test_logs_query_when_level_enabled(self):
        """Test logs query when log level is enabled."""
        logger = Mock()
        logger.isEnabledFor = Mock(return_value=True)
        logger._log = Mock()

        log_query_with_timing(logger, 10, 0.5, "SELECT 1", "postgresql://localhost")

        logger.isEnabledFor.assert_called_once_with(10)
        logger._log.assert_called_once()

    def test_skips_logging_when_level_disabled(self):
        """Test skips logging when log level is disabled."""
        logger = Mock()
        logger.isEnabledFor = Mock(return_value=False)
        logger._log = Mock()

        log_query_with_timing(logger, 10, 0.5, "SELECT 1", "postgresql://localhost")

        logger._log.assert_not_called()

    def test_fallback_to_stderr_on_exception(self):
        """Test writes to stderr when logging fails."""
        import sys
        from io import StringIO

        logger = Mock()
        logger.isEnabledFor = Mock(side_effect=Exception("Logger broken"))

        captured = StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured

        try:
            log_query_with_timing(logger, 10, 0.5, "SELECT 1", "postgresql://localhost")

            output = captured.getvalue()
            assert "UNABLE TO LOG" in output
            assert "Logger broken" in output

        finally:
            sys.stderr = old_stderr


@pytest.mark.unit
class TestInitializationHelpers:
    """Test initialization helper functions."""

    def test_validate_init_params_accepts_valid_inputs(self):
        """Test validate_init_params accepts valid inputs."""
        validate_init_params(Mock(), Mock())  # Should not raise

    def test_create_sqlalchemy_engine(self):
        """Test create_sqlalchemy_engine creates engine with NullPool."""
        engine = create_sqlalchemy_engine("sqlite:///:memory:")

        assert isinstance(engine, sqlalchemy.engine.Engine)
        assert isinstance(engine.pool, sqlalchemy.pool.NullPool)

    def test_create_engine_and_session(self):
        """Test create_engine_and_session returns tuple."""
        cfg = Mock()
        cfg.url = "sqlite:///:memory:"

        engine, session_cls = create_engine_and_session(cfg)

        assert isinstance(engine, sqlalchemy.engine.Engine)
        assert callable(session_cls)

    def test_initialize_connection_health(self):
        """Test initialize_connection_health sets attributes."""
        pg = Mock()
        pg._cfg = Mock(spec=[])  # Empty spec so getattr returns defaults

        initialize_connection_health(pg)

        assert pg._connection_healthy is True
        assert pg._auto_reconnect is True
        assert pg._max_retries == 3
        assert pg._retry_delay == 1.0

    def test_initialize_logging_context(self):
        """Test initialize_logging_context sets context and level."""
        pg = Mock()
        pg._engine = Mock()
        pg._engine.url = "postgresql://localhost/test"
        pg.readonly = False

        initialize_logging_context(pg, "debug")

        assert pg._lg_extra["url"] == pg._engine.url
        assert pg._lg_extra["readonly"] is False

    def test_initialize_performance_cache(self):
        """Test initialize_performance_cache sets dialect and regex."""
        import re

        pg = Mock()
        engine = sqlalchemy.create_engine("sqlite:///:memory:")
        pg._engine = engine

        initialize_performance_cache(pg)

        assert pg._dialect == engine.dialect
        assert isinstance(pg._cached_regex, re.Pattern)

    def test_initialize_performance_optimizations(self):
        """Test initialize_performance_optimizations sets caches."""
        import re

        pg = Mock()

        initialize_performance_optimizations(pg)

        assert isinstance(pg._whitespace_regex, re.Pattern)
        assert pg._dialect is not None

    def test_configure_readonly_mode_when_readonly(self):
        """Test configure_readonly_mode sets up event listener."""
        pg = Mock()
        pg.readonly = True
        pg._cfg = Mock(
            spec=[]
        )  # Empty spec so getattr(cfg, "create_db", False) returns False
        pg._engine = Mock()

        with patch("sqlalchemy.event.listen") as mock_listen:
            configure_readonly_mode(pg)

            # Should register event listener
            mock_listen.assert_called_once()
            assert hasattr(pg, "_readonly_listener")

    def test_configure_readonly_mode_when_not_readonly(self):
        """Test configure_readonly_mode does nothing when readonly=False."""
        pg = Mock()
        pg.readonly = False
        pg._cfg = Mock()
        pg._engine = Mock()

        with patch("sqlalchemy.event.listen") as mock_listen:
            configure_readonly_mode(pg)

            # Should not register listener
            mock_listen.assert_not_called()

    def test_configure_readonly_mode_rejects_create_db(self):
        """Test configure_readonly_mode raises error when create_db is True."""
        pg = Mock()
        pg.readonly = True
        pg._cfg = Mock()
        pg._cfg.create_db = True  # Set attribute instead of mocking .get()

        with pytest.raises(
            ValueError, match="Cannot create database in read-only mode"
        ):
            configure_readonly_mode(pg)
