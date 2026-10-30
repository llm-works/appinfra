# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for quick logging setup functions.

Tests quick logger creation functions including:
- Console loggers
- File loggers
- Combined loggers
- Custom configurations
"""

from unittest.mock import Mock

from appinfra.log.builder.quick import (
    _create_data_mapper_from_columns,
    quick_audit_logger,
    quick_console_logger,
    quick_console_with_colors,
    quick_custom_database_logger,
    quick_error_logger,
)
from appinfra.log.logger import Logger

# =============================================================================
# Test quick_console_logger
# =============================================================================


class TestQuickConsoleLogger:
    """Test quick console logger creation."""

    def test_quick_console_logger_default_config(self):
        """Test quick_console_logger with default configuration."""
        logger = quick_console_logger("test_logger")

        assert isinstance(logger, Logger)
        assert logger.name == "test_logger"

    def test_quick_console_logger_with_config(self):
        """Test quick_console_logger with custom configuration."""
        config = {"level": "debug", "location": 1, "micros": True}
        logger = quick_console_logger("test_logger", config)

        assert isinstance(logger, Logger)
        assert logger.name == "test_logger"

    def test_quick_console_logger_info_level(self):
        """Test quick_console_logger logs at info level."""
        logger = quick_console_logger("test_logger")
        logger.info("Test message")
        # If no exception, logger works

    def test_quick_console_logger_none_config(self):
        """Test quick_console_logger with None config uses defaults."""
        logger = quick_console_logger("test_logger", None)
        assert isinstance(logger, Logger)


# =============================================================================
# Test _create_data_mapper_from_columns
# =============================================================================


class TestCreateDataMapper:
    """Test data mapper creation helper."""

    def test_create_data_mapper_timestamp(self):
        """Test data mapper with timestamp field."""
        columns = {"timestamp": "ts"}
        mapper = _create_data_mapper_from_columns(columns)

        # Create mock record
        from unittest.mock import Mock

        record = Mock()
        record.created = 1234567890.0

        data = mapper(record)
        assert "ts" in data

    def test_create_data_mapper_level(self):
        """Test data mapper with level field."""
        columns = {"level": "log_level"}
        mapper = _create_data_mapper_from_columns(columns)

        from unittest.mock import Mock

        record = Mock()
        record.levelname = "INFO"

        data = mapper(record)
        assert data["log_level"] == "INFO"

    def test_create_data_mapper_logger(self):
        """Test data mapper with logger field."""
        columns = {"logger": "logger_name"}
        mapper = _create_data_mapper_from_columns(columns)

        from unittest.mock import Mock

        record = Mock()
        record.name = "test.logger"

        data = mapper(record)
        assert data["logger_name"] == "test.logger"

    def test_create_data_mapper_message(self):
        """Test data mapper with message field."""
        columns = {"message": "msg"}
        mapper = _create_data_mapper_from_columns(columns)

        from unittest.mock import Mock

        record = Mock()
        record.getMessage.return_value = "Test message"

        data = mapper(record)
        assert data["msg"] == "Test message"

    def test_create_data_mapper_module(self):
        """Test data mapper with module field."""
        columns = {"module": "mod"}
        mapper = _create_data_mapper_from_columns(columns)

        from unittest.mock import Mock

        record = Mock()
        record.module = "test_module"

        data = mapper(record)
        assert data["mod"] == "test_module"

    def test_create_data_mapper_function(self):
        """Test data mapper with function field."""
        columns = {"function": "func"}
        mapper = _create_data_mapper_from_columns(columns)

        from unittest.mock import Mock

        record = Mock()
        record.funcName = "test_function"

        data = mapper(record)
        assert data["func"] == "test_function"

    def test_create_data_mapper_line(self):
        """Test data mapper with line field."""
        columns = {"line": "line_no"}
        mapper = _create_data_mapper_from_columns(columns)

        from unittest.mock import Mock

        record = Mock()
        record.lineno = 42

        data = mapper(record)
        assert data["line_no"] == 42

    def test_create_data_mapper_multiple_fields(self):
        """Test data mapper with multiple fields."""
        columns = {"level": "log_level", "message": "msg", "logger": "name"}
        mapper = _create_data_mapper_from_columns(columns)

        from unittest.mock import Mock

        record = Mock()
        record.levelname = "INFO"
        record.getMessage.return_value = "Test"
        record.name = "test"

        data = mapper(record)
        assert len(data) == 3
        assert data["log_level"] == "INFO"


# =============================================================================
# Test quick_console_with_colors
# =============================================================================


class TestQuickConsoleWithColors:
    """Test quick console logger with colors."""

    def test_quick_console_with_colors_default(self):
        """Test quick_console_with_colors with default configuration."""
        logger = quick_console_with_colors("test_logger")
        assert isinstance(logger, Logger)
        assert logger.name == "test_logger"

    def test_quick_console_with_colors_custom_config(self):
        """Test quick_console_with_colors with custom config."""
        config = {"level": "debug", "colors": True}
        logger = quick_console_with_colors("test_logger", config)
        assert isinstance(logger, Logger)

    def test_quick_console_with_colors_none_config(self):
        """Test quick_console_with_colors with None config."""
        logger = quick_console_with_colors("test_logger", None)
        assert isinstance(logger, Logger)


# =============================================================================
# Test Database Quick Loggers
# =============================================================================


class TestDatabaseQuickLoggers:
    """Test quick database logger functions."""

    def test_quick_audit_logger(self):
        """Test quick_audit_logger."""
        mock_db = Mock()
        logger = quick_audit_logger("test_logger", mock_db)
        assert isinstance(logger, Logger)

    def test_quick_audit_logger_with_config(self):
        """Test quick_audit_logger with custom config."""
        mock_db = Mock()
        config = {"level": "warning"}
        logger = quick_audit_logger("test_logger", mock_db, config)
        assert isinstance(logger, Logger)

    def test_quick_audit_logger_none_config(self):
        """Test quick_audit_logger with None config."""
        mock_db = Mock()
        logger = quick_audit_logger("test_logger", mock_db, None)
        assert isinstance(logger, Logger)

    def test_quick_error_logger(self):
        """Test quick_error_logger."""
        mock_db = Mock()
        logger = quick_error_logger("test_logger", mock_db)
        assert isinstance(logger, Logger)

    def test_quick_error_logger_with_config(self):
        """Test quick_error_logger with custom config."""
        mock_db = Mock()
        config = {"level": "error"}
        logger = quick_error_logger("test_logger", mock_db, config)
        assert isinstance(logger, Logger)

    def test_quick_error_logger_none_config(self):
        """Test quick_error_logger with None config."""
        mock_db = Mock()
        logger = quick_error_logger("test_logger", mock_db, None)
        assert isinstance(logger, Logger)

    def test_quick_custom_database_logger(self):
        """Test quick_custom_database_logger."""
        mock_db = Mock()
        logger = quick_custom_database_logger("test_logger", mock_db, "custom_table")
        assert isinstance(logger, Logger)

    def test_quick_custom_database_logger_with_columns(self):
        """Test quick_custom_database_logger with custom columns."""
        mock_db = Mock()
        columns = {"timestamp": "ts", "level": "log_level", "message": "msg"}
        logger = quick_custom_database_logger(
            "test_logger", mock_db, "custom_table", columns=columns
        )
        assert isinstance(logger, Logger)

    def test_quick_custom_database_logger_with_config(self):
        """Test quick_custom_database_logger with config."""
        mock_db = Mock()
        config = {"level": "debug"}
        columns = {"message": "msg"}
        logger = quick_custom_database_logger(
            "test_logger", mock_db, "custom_table", config, columns
        )
        assert isinstance(logger, Logger)

    def test_quick_custom_database_logger_none_config(self):
        """Test quick_custom_database_logger with None config."""
        mock_db = Mock()
        logger = quick_custom_database_logger(
            "test_logger", mock_db, "custom_table", None
        )
        assert isinstance(logger, Logger)
