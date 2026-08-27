# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Comprehensive tests for DatabaseLoggingBuilder.

Tests fluent API, config loading, and builder patterns.
"""

from unittest.mock import Mock

import pytest

from appinfra.log.builder.database import (
    DatabaseLoggingBuilder,
    create_database_logger,
    create_database_logger_from_config,
    load_database_logging_config,
)
from appinfra.log.builder.database.config import DatabaseHandlerConfig


@pytest.fixture
def mock_db_interface():
    """Create mock database interface."""
    db = Mock()
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    db.session.return_value = session
    return db


@pytest.mark.unit
class TestDatabaseLoggingBuilderInit:
    """Test DatabaseLoggingBuilder initialization."""

    def test_basic_initialization(self):
        """Test builder initializes with logger name."""
        builder = DatabaseLoggingBuilder("test_logger")

        assert builder._name == "test_logger"
        assert builder._handlers == []


@pytest.mark.unit
class TestWithDatabaseTable:
    """Test with_database_table method."""

    def test_adds_database_handler(self, mock_db_interface):
        """Test adds database handler to builder."""
        builder = DatabaseLoggingBuilder("test")

        result = builder.with_database_table(
            table_name="logs",
            db_interface=mock_db_interface,
        )

        assert result is builder  # Fluent interface
        assert len(builder._handlers) == 1
        assert isinstance(builder._handlers[0], DatabaseHandlerConfig)

    def test_sets_all_parameters(self, mock_db_interface):
        """Test sets all handler parameters correctly."""
        custom_mapper = Mock()
        custom_columns = {"timestamp": "ts"}

        builder = DatabaseLoggingBuilder("test").with_database_table(
            table_name="custom_logs",
            db_interface=mock_db_interface,
            level="debug",
            columns=custom_columns,
            data_mapper=custom_mapper,
            batch_size=50,
            flush_interval=30.0,
            critical_flush_enabled=True,
            critical_trigger_fields=["fatal"],
            critical_flush_timeout=10.0,
            fallback_to_console=False,
        )

        handler_config = builder._handlers[0]
        assert handler_config.table_name == "custom_logs"
        assert handler_config.level == "debug"
        assert handler_config.columns == custom_columns
        assert handler_config.data_mapper == custom_mapper
        assert handler_config.batch_size == 50
        assert handler_config.flush_interval == 30.0
        assert handler_config.critical_flush_enabled is True


@pytest.mark.unit
class TestWithAuditTable:
    """Test with_audit_table convenience method."""

    def test_creates_audit_table_handler(self, mock_db_interface):
        """Test creates handler with audit table columns."""
        builder = DatabaseLoggingBuilder("audit").with_audit_table(
            db_interface=mock_db_interface,
        )

        handler_config = builder._handlers[0]
        assert handler_config.table_name == "audit_logs"
        assert "created_at" in handler_config.columns.values()
        assert "action_description" in handler_config.columns.values()

    def test_uses_audit_specific_defaults(self, mock_db_interface):
        """Test uses audit-specific default batch settings."""
        builder = DatabaseLoggingBuilder("audit").with_audit_table(
            db_interface=mock_db_interface,
        )

        handler_config = builder._handlers[0]
        assert handler_config.batch_size == 10
        assert handler_config.flush_interval == 5.0


@pytest.mark.unit
class TestWithErrorTable:
    """Test with_error_table convenience method."""

    def test_creates_error_table_handler(self, mock_db_interface):
        """Test creates handler with error table columns."""
        builder = DatabaseLoggingBuilder("errors").with_error_table(
            db_interface=mock_db_interface,
        )

        handler_config = builder._handlers[0]
        assert handler_config.table_name == "error_logs"
        assert "error_time" in handler_config.columns.values()
        assert "stack_trace" in handler_config.columns.values()

    def test_uses_error_specific_defaults(self, mock_db_interface):
        """Test uses error-specific default batch settings."""
        builder = DatabaseLoggingBuilder("errors").with_error_table(
            db_interface=mock_db_interface,
        )

        handler_config = builder._handlers[0]
        assert handler_config.batch_size == 5
        assert handler_config.flush_interval == 2.0


@pytest.mark.unit
class TestWithCustomTable:
    """Test with_custom_table method."""

    def test_creates_handler_with_custom_mapper(self, mock_db_interface):
        """Test creates handler with custom data mapper."""
        custom_mapper = Mock()

        builder = DatabaseLoggingBuilder("custom").with_custom_table(
            table_name="custom_logs",
            db_interface=mock_db_interface,
            data_mapper=custom_mapper,
        )

        handler_config = builder._handlers[0]
        assert handler_config.table_name == "custom_logs"
        assert handler_config.data_mapper == custom_mapper


@pytest.mark.unit
class TestWithCriticalErrorFlush:
    """Test with_critical_error_flush configuration."""

    def test_enables_critical_flush_on_all_handlers(self, mock_db_interface):
        """Test enables critical flush on all database handlers."""
        builder = (
            DatabaseLoggingBuilder("test")
            .with_database_table("logs1", mock_db_interface)
            .with_database_table("logs2", mock_db_interface)
            .with_critical_error_flush(
                enabled=True, trigger_fields=["fatal"], timeout=3.0
            )
        )

        for handler_config in builder._handlers:
            assert handler_config.critical_flush_enabled is True
            assert "fatal" in handler_config.critical_trigger_fields
            assert handler_config.critical_flush_timeout == 3.0


@pytest.mark.unit
class TestBuild:
    """Test build method."""

    def test_builds_logger_with_handlers(self, mock_db_interface):
        """Test builds logger with configured database handlers."""
        builder = (
            DatabaseLoggingBuilder("test")
            .with_level("info")
            .with_database_table("logs", mock_db_interface)
        )

        logger = builder.build()

        assert logger.name == "test"
        assert len(logger.handlers) > 0

    def test_builds_logger_with_multiple_tables(self, mock_db_interface):
        """Test builds logger with multiple database handlers."""
        builder = (
            DatabaseLoggingBuilder("multi")
            .with_level("debug")
            .with_database_table("logs", mock_db_interface)
            .with_audit_table(mock_db_interface)
            .with_error_table(mock_db_interface)
        )

        logger = builder.build()

        assert len(logger.handlers) >= 3


@pytest.mark.unit
class TestCreateDatabaseLogger:
    """Test create_database_logger utility function."""

    def test_creates_builder_instance(self):
        """Test creates DatabaseLoggingBuilder."""
        builder = create_database_logger("test")

        assert isinstance(builder, DatabaseLoggingBuilder)
        assert builder._name == "test"


@pytest.mark.unit
class TestLoadDatabaseLoggingConfig:
    """Test load_database_logging_config function."""

    def test_loads_from_handler_config(self):
        """Test loads config from handler configuration."""
        handler_config = {
            "batch_size": 20,
            "flush_interval": 15,
            "critical_flush": {
                "enabled": True,
                "trigger_fields": ["fatal", "critical"],
                "timeout": 10.0,
                "fallback_to_console": False,
            },
        }

        result = load_database_logging_config({}, handler_config)

        assert result["default_batch_size"] == 20
        assert result["default_flush_interval"] == 15
        assert result["critical_flush"]["enabled"] is True
        assert "fatal" in result["critical_flush"]["trigger_fields"]

    def test_loads_from_top_level_config(self):
        """Test loads config from top-level configuration (backward compat)."""
        config_dict = {
            "database_logging": {
                "default_batch_size": 100,
                "default_flush_interval": 60,
                "critical_flush": {
                    "enabled": False,
                },
            }
        }

        result = load_database_logging_config(config_dict)

        assert result["default_batch_size"] == 100
        assert result["default_flush_interval"] == 60
        assert result["critical_flush"]["enabled"] is False

    def test_uses_defaults_for_missing_values(self):
        """Test uses default values when config is incomplete."""
        result = load_database_logging_config({})

        assert result["default_batch_size"] == 10
        assert result["default_flush_interval"] == 30
        assert result["critical_flush"]["enabled"] is True


@pytest.mark.unit
class TestCreateDatabaseLoggerFromConfig:
    """Test create_database_logger_from_config function."""

    def test_creates_builder_from_config(self, mock_db_interface):
        """Test creates configured builder from config dict."""
        config_dict = {
            "database_logging": {
                "default_batch_size": 25,
                "default_flush_interval": 10,
            }
        }

        builder = create_database_logger_from_config(
            name="from_config",
            config_dict=config_dict,
            db_interface=mock_db_interface,
            table_name="app_logs",
        )

        assert isinstance(builder, DatabaseLoggingBuilder)
        assert len(builder._handlers) == 1
        handler_config = builder._handlers[0]
        assert handler_config.table_name == "app_logs"
        assert handler_config.batch_size == 25
        assert handler_config.flush_interval == 10

    def test_uses_handler_config_when_provided(self, mock_db_interface):
        """Test uses handler-specific config when provided."""
        config_dict = {}
        handler_config = {
            "batch_size": 5,
            "flush_interval": 1.0,
        }

        builder = create_database_logger_from_config(
            name="test",
            config_dict=config_dict,
            db_interface=mock_db_interface,
            handler_config=handler_config,
        )

        assert builder._handlers[0].batch_size == 5
        assert builder._handlers[0].flush_interval == 1.0
