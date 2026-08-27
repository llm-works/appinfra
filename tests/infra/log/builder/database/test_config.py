# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Comprehensive tests for DatabaseHandlerConfig.

Tests data mapping, column configuration, and handler creation.
"""

import logging
from datetime import datetime
from unittest.mock import Mock

import pytest

from appinfra.log.builder.database.config import DatabaseHandlerConfig
from appinfra.log.config import LogConfig


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
class TestDatabaseHandlerConfigInit:
    """Test DatabaseHandlerConfig initialization."""

    def test_basic_initialization(self, mock_db_interface):
        """Test config initializes with required parameters."""
        config = DatabaseHandlerConfig(
            table_name="test_logs",
            db_interface=mock_db_interface,
        )

        assert config.table_name == "test_logs"
        assert config.db_interface == mock_db_interface
        assert config.batch_size == 1
        assert config.flush_interval == 0.0
        assert config.critical_flush_enabled is False

    def test_sets_custom_parameters(self, mock_db_interface):
        """Test config accepts custom parameters."""
        custom_columns = {"timestamp": "ts", "message": "msg"}
        custom_mapper = Mock()

        config = DatabaseHandlerConfig(
            table_name="custom_logs",
            db_interface=mock_db_interface,
            level="error",
            columns=custom_columns,
            data_mapper=custom_mapper,
            batch_size=50,
            flush_interval=10.0,
            critical_flush_enabled=True,
            critical_trigger_fields=["fatal"],
            critical_flush_timeout=3.0,
            fallback_to_console=False,
        )

        assert config.columns == custom_columns
        assert config.data_mapper == custom_mapper
        assert config.batch_size == 50
        assert config.flush_interval == 10.0
        assert config.critical_flush_enabled is True
        assert config.critical_trigger_fields == ["fatal"]
        assert config.critical_flush_timeout == 3.0
        assert config.fallback_to_console is False

    def test_uses_default_columns_when_not_provided(self, mock_db_interface):
        """Test uses default column mapping when not provided."""
        config = DatabaseHandlerConfig(
            table_name="test_logs",
            db_interface=mock_db_interface,
        )

        assert "timestamp" in config.columns
        assert "level" in config.columns
        assert "message" in config.columns
        assert "exception" in config.columns

    def test_uses_default_data_mapper(self, mock_db_interface):
        """Test uses default data mapper when not provided."""
        config = DatabaseHandlerConfig(
            table_name="test_logs",
            db_interface=mock_db_interface,
        )

        assert config.data_mapper == config._default_data_mapper


@pytest.mark.unit
class TestDefaultDataMapper:
    """Test _default_data_mapper method."""

    def test_maps_basic_fields(self, mock_db_interface):
        """Test maps timestamp, level, logger, message."""
        config = DatabaseHandlerConfig(
            table_name="test_logs",
            db_interface=mock_db_interface,
        )

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        setattr(record, "__infra__extra", None)

        data = config._default_data_mapper(record)

        assert isinstance(data["timestamp"], datetime)
        assert data["level"] == "INFO"
        assert data["logger_name"] == "test.logger"
        assert data["message"] == "Test message"

    def test_maps_optional_fields(self, mock_db_interface):
        """Test maps optional fields like module, function, line."""
        config = DatabaseHandlerConfig(
            table_name="test_logs",
            db_interface=mock_db_interface,
        )

        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="/path/to/test.py",
            lineno=10,
            msg="Debug",
            args=(),
            exc_info=None,
        )
        record.module = "test_module"
        record.funcName = "test_function"
        record.process = 1234
        record.thread = 5678
        setattr(record, "__infra__extra", None)

        data = config._default_data_mapper(record)

        assert data["module"] == "test_module"
        assert data["function"] == "test_function"
        assert data["line_number"] == 10
        assert data["process_id"] == 1234
        assert data["thread_id"] == 5678

    def test_maps_exception_info(self, mock_db_interface):
        """Test maps exception traceback."""
        config = DatabaseHandlerConfig(
            table_name="test_logs",
            db_interface=mock_db_interface,
        )

        try:
            raise ValueError("Test exception")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )
        setattr(record, "__infra__extra", None)

        data = config._default_data_mapper(record)

        assert "exception_info" in data
        assert "ValueError" in data["exception_info"]
        assert "Test exception" in data["exception_info"]

    def test_maps_extra_fields_as_json(self, mock_db_interface):
        """Test maps extra fields as JSON."""
        config = DatabaseHandlerConfig(
            table_name="test_logs",
            db_interface=mock_db_interface,
        )

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Message",
            args=(),
            exc_info=None,
        )
        setattr(record, "__infra__extra", {"user_id": 123, "action": "login"})

        data = config._default_data_mapper(record)

        assert "extra_data" in data
        import json

        extra = json.loads(data["extra_data"])
        assert extra["user_id"] == 123
        assert extra["action"] == "login"

    def test_maps_standard_line_number(self, mock_db_interface):
        """Test maps standard line number (int)."""
        config = DatabaseHandlerConfig(
            table_name="test_logs",
            db_interface=mock_db_interface,
        )

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Message",
            args=(),
            exc_info=None,
        )

        data = config._default_data_mapper(record)

        assert data["line_number"] == 42


@pytest.mark.unit
class TestCreateHandler:
    """Test create_handler method."""

    def test_creates_database_handler(self, mock_db_interface):
        """Test creates DatabaseHandler instance."""
        config = DatabaseHandlerConfig(
            table_name="test_logs",
            db_interface=mock_db_interface,
        )
        log_config = LogConfig.from_params(level="info", location=0, micros=False)
        logger = Mock()

        handler = config.create_handler(log_config, logger=logger)

        from appinfra.log.builder.database.handler import DatabaseHandler

        assert isinstance(handler, DatabaseHandler)
        assert handler.handler_config == config

    def test_requires_logger_parameter(self, mock_db_interface):
        """Test raises ValueError when logger is None."""
        config = DatabaseHandlerConfig(
            table_name="test_logs",
            db_interface=mock_db_interface,
        )
        log_config = LogConfig.from_params(level="info", location=0, micros=False)

        with pytest.raises(ValueError, match="requires a logger instance"):
            config.create_handler(log_config, logger=None)

    def test_passes_lifecycle_manager(self, mock_db_interface):
        """Test passes lifecycle manager to handler."""
        config = DatabaseHandlerConfig(
            table_name="test_logs",
            db_interface=mock_db_interface,
        )
        log_config = LogConfig.from_params(level="info", location=0, micros=False)
        logger = Mock()
        lifecycle_mgr = Mock()

        handler = config.create_handler(
            log_config, logger=logger, lifecycle_manager=lifecycle_mgr
        )

        # Handler should be registered with lifecycle manager
        assert lifecycle_mgr.register_db_handler.called
