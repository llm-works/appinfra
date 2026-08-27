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

import os
import tempfile
from unittest.mock import Mock

import pytest

from appinfra.log.builder.quick import (
    _create_data_mapper_from_columns,
    quick_audit_logger,
    quick_both_logger,
    quick_both_outputs,
    quick_console_and_file,
    quick_console_logger,
    quick_console_with_colors,
    quick_custom_database_logger,
    quick_daily_file_logger,
    quick_error_logger,
    quick_file_logger,
    quick_file_with_rotation,
    quick_json_console,
    quick_json_file,
)
from appinfra.log.logger import Logger

# =============================================================================
# Test quick_console_logger
# =============================================================================


@pytest.mark.unit
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
# Test quick_file_logger
# =============================================================================


@pytest.mark.unit
class TestQuickFileLogger:
    """Test quick file logger creation."""

    def test_quick_file_logger_default_config(self):
        """Test quick_file_logger with default configuration."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            logger = quick_file_logger("test_logger", log_file)
            assert isinstance(logger, Logger)
            assert logger.name == "test_logger"

            logger.info("Test message")
            assert os.path.exists(log_file)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_file_logger_with_config(self):
        """Test quick_file_logger with custom configuration."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            config = {"level": "debug"}
            logger = quick_file_logger("test_logger", log_file, config)
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_file_logger_none_config(self):
        """Test quick_file_logger with None config."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            logger = quick_file_logger("test_logger", log_file, None)
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)


# =============================================================================
# Test quick_both_logger
# =============================================================================


@pytest.mark.unit
class TestQuickBothLogger:
    """Test quick logger with both console and file output."""

    def test_quick_both_logger_default_config(self):
        """Test quick_both_logger with default configuration."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            logger = quick_both_logger("test_logger", log_file)
            assert isinstance(logger, Logger)
            assert logger.name == "test_logger"

            logger.info("Test message")
            assert os.path.exists(log_file)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_both_logger_with_config(self):
        """Test quick_both_logger with custom configuration."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            config = {"level": "warning", "colors": False}
            logger = quick_both_logger("test_logger", log_file, config)
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)


# =============================================================================
# Test _create_data_mapper_from_columns
# =============================================================================


@pytest.mark.unit
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


@pytest.mark.unit
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
# Test quick_file_with_rotation
# =============================================================================


@pytest.mark.unit
class TestQuickFileWithRotation:
    """Test quick file logger with rotation."""

    def test_quick_file_with_rotation_default(self):
        """Test quick_file_with_rotation with default parameters."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            logger = quick_file_with_rotation("test_logger", log_file)
            assert isinstance(logger, Logger)
            logger.info("Test message")
            assert os.path.exists(log_file)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_file_with_rotation_custom_params(self):
        """Test quick_file_with_rotation with custom rotation parameters."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            config = {"level": "warning"}
            logger = quick_file_with_rotation(
                "test_logger", log_file, config, max_bytes=2048, backup_count=3
            )
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_file_with_rotation_none_config(self):
        """Test quick_file_with_rotation with None config."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            logger = quick_file_with_rotation("test_logger", log_file, None)
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)


# =============================================================================
# Test quick_daily_file_logger
# =============================================================================


@pytest.mark.unit
class TestQuickDailyFileLogger:
    """Test quick daily file logger."""

    def test_quick_daily_file_logger_default(self):
        """Test quick_daily_file_logger with default parameters."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            logger = quick_daily_file_logger("test_logger", log_file)
            assert isinstance(logger, Logger)
            logger.info("Test message")
            assert os.path.exists(log_file)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_daily_file_logger_custom_backup(self):
        """Test quick_daily_file_logger with custom backup count."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            config = {"level": "info"}
            logger = quick_daily_file_logger(
                "test_logger", log_file, config, backup_count=14
            )
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_daily_file_logger_none_config(self):
        """Test quick_daily_file_logger with None config."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            logger = quick_daily_file_logger("test_logger", log_file, None)
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)


# =============================================================================
# Test quick_console_and_file
# =============================================================================


@pytest.mark.unit
class TestQuickConsoleAndFile:
    """Test quick logger with console and file output."""

    def test_quick_console_and_file_default(self):
        """Test quick_console_and_file with default configuration."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            logger = quick_console_and_file("test_logger", log_file)
            assert isinstance(logger, Logger)
            logger.info("Test message")
            assert os.path.exists(log_file)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_console_and_file_custom_config(self):
        """Test quick_console_and_file with custom configuration."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".log") as f:
            log_file = f.name

        try:
            config = {"level": "debug", "colors": False}
            logger = quick_console_and_file("test_logger", log_file, config)
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)


# =============================================================================
# Test Database Quick Loggers
# =============================================================================


@pytest.mark.unit
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


# =============================================================================
# Test JSON Quick Loggers
# =============================================================================


@pytest.mark.unit
class TestJSONQuickLoggers:
    """Test quick JSON logger functions."""

    def test_quick_json_console(self):
        """Test quick_json_console."""
        logger = quick_json_console("test_logger")
        assert isinstance(logger, Logger)

    def test_quick_json_console_with_config(self):
        """Test quick_json_console with custom config."""
        config = {"level": "debug"}
        logger = quick_json_console("test_logger", config)
        assert isinstance(logger, Logger)

    def test_quick_json_console_none_config(self):
        """Test quick_json_console with None config."""
        logger = quick_json_console("test_logger", None)
        assert isinstance(logger, Logger)

    def test_quick_json_file(self):
        """Test quick_json_file."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            logger = quick_json_file("test_logger", log_file)
            assert isinstance(logger, Logger)
            logger.info("Test message")
            assert os.path.exists(log_file)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_json_file_with_pretty_print(self):
        """Test quick_json_file with pretty print."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            logger = quick_json_file("test_logger", log_file, pretty_print=True)
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_json_file_with_config(self):
        """Test quick_json_file with config."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            config = {"level": "warning"}
            logger = quick_json_file("test_logger", log_file, config)
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_json_file_none_config(self):
        """Test quick_json_file with None config."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            logger = quick_json_file("test_logger", log_file, None)
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_both_outputs(self):
        """Test quick_both_outputs."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            logger = quick_both_outputs("test_logger", log_file)
            assert isinstance(logger, Logger)
            logger.info("Test message")
            assert os.path.exists(log_file)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_both_outputs_with_pretty_print(self):
        """Test quick_both_outputs with pretty print."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            logger = quick_both_outputs("test_logger", log_file, pretty_print=True)
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_both_outputs_with_config(self):
        """Test quick_both_outputs with config."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            config = {"level": "error"}
            logger = quick_both_outputs("test_logger", log_file, config)
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_quick_both_outputs_none_config(self):
        """Test quick_both_outputs with None config."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            logger = quick_both_outputs("test_logger", log_file, None)
            assert isinstance(logger, Logger)
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestQuickLoggerIntegration:
    """Test real-world quick logger scenarios."""

    def test_console_logger_logs_message(self):
        """Test console logger actually logs messages."""
        logger = quick_console_logger("test", {"level": "info"})
        logger.info("Test message")
        logger.debug("Debug message")
        # If no exception, integration works

    def test_file_logger_creates_file(self):
        """Test file logger creates log file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")
            logger = quick_file_logger("test", log_file)
            logger.info("Test message")

            assert os.path.exists(log_file)
            with open(log_file) as f:
                content = f.read()
                assert "Test message" in content

    def test_both_logger_writes_to_both(self):
        """Test both logger writes to console and file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "test.log")
            logger = quick_both_logger("test", log_file)
            logger.warning("Warning message")

            assert os.path.exists(log_file)
            with open(log_file) as f:
                content = f.read()
                assert "Warning message" in content
