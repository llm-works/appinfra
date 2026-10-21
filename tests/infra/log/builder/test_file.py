# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for file logging builder.

Tests key functionality including:
- FileHandlerConfig with string level conversion
- RotatingFileHandlerConfig with string level conversion
- TimedRotatingFileHandlerConfig with string level conversion
- FileLoggingBuilder rotation methods (hourly, weekly)
- create_file_logger convenience function
"""

import logging
import tempfile
from pathlib import Path

import pytest

from appinfra.log.builder.file import (
    FileHandlerConfig,
    FileLoggingBuilder,
    RotatingFileHandlerConfig,
    TimedRotatingFileHandlerConfig,
    create_file_logger,
)
from appinfra.log.config import LogConfig

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_log_dir():
    """Create temporary directory for log files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def log_config():
    """Create basic log configuration."""
    return LogConfig(level=logging.DEBUG, location=0, micros=False, colors=False)


@pytest.fixture
def log_config_with_string_level():
    """Create log configuration with string level."""
    return LogConfig.from_params(level="INFO", location=0, micros=False, colors=False)


# =============================================================================
# Test FileHandlerConfig
# =============================================================================


@pytest.mark.unit
class TestFileHandlerConfig:
    """Test FileHandlerConfig class."""

    def test_init_basic(self):
        """Test basic initialization."""
        config = FileHandlerConfig("test.log")
        assert config.filename == "test.log"
        assert config.mode == "a"
        assert config.encoding is None
        assert config.delay is False
        assert config.level is None

    def test_init_all_params(self):
        """Test initialization with all parameters."""
        config = FileHandlerConfig(
            filename="test.log",
            mode="w",
            encoding="utf-8",
            delay=True,
            level=logging.WARNING,
        )
        assert config.filename == "test.log"
        assert config.mode == "w"
        assert config.encoding == "utf-8"
        assert config.delay is True
        assert config.level == logging.WARNING

    def test_create_handler_with_int_level(self, temp_log_dir, log_config):
        """Test create_handler with integer level."""
        log_file = temp_log_dir / "test.log"
        config = FileHandlerConfig(log_file, level=logging.WARNING)
        handler = config.create_handler(log_config)

        assert isinstance(handler, logging.FileHandler)
        assert handler.level == logging.WARNING
        handler.close()

    def test_create_handler_with_string_level(self, temp_log_dir, log_config):
        """Test create_handler with string level (line 50)."""
        log_file = temp_log_dir / "test.log"
        config = FileHandlerConfig(log_file, level="ERROR")
        handler = config.create_handler(log_config)

        assert isinstance(handler, logging.FileHandler)
        assert handler.level == logging.ERROR
        handler.close()

    def test_create_handler_with_lowercase_string_level(self, temp_log_dir, log_config):
        """Test create_handler with lowercase string level."""
        log_file = temp_log_dir / "test.log"
        config = FileHandlerConfig(log_file, level="warning")
        handler = config.create_handler(log_config)

        assert handler.level == logging.WARNING
        handler.close()

    def test_create_handler_uses_config_level_when_none(self, temp_log_dir, log_config):
        """Test create_handler uses LogConfig level when handler level is None."""
        log_file = temp_log_dir / "test.log"
        config = FileHandlerConfig(log_file, level=None)
        handler = config.create_handler(log_config)

        assert handler.level == logging.DEBUG
        handler.close()

    def test_create_handler_creates_parent_directory(self, temp_log_dir, log_config):
        """Test create_handler creates parent directories."""
        log_file = temp_log_dir / "subdir" / "nested" / "test.log"
        config = FileHandlerConfig(log_file)
        handler = config.create_handler(log_config)

        assert log_file.parent.exists()
        handler.close()


# =============================================================================
# Test RotatingFileHandlerConfig
# =============================================================================


@pytest.mark.unit
class TestRotatingFileHandlerConfig:
    """Test RotatingFileHandlerConfig class."""

    def test_init_basic(self):
        """Test basic initialization."""
        config = RotatingFileHandlerConfig("test.log")
        assert config.filename == "test.log"
        assert config.max_bytes == 0
        assert config.backup_count == 0
        assert config.encoding is None
        assert config.delay is False
        assert config.level is None

    def test_init_all_params(self):
        """Test initialization with all parameters."""
        config = RotatingFileHandlerConfig(
            filename="test.log",
            max_bytes=1024 * 1024,
            backup_count=5,
            encoding="utf-8",
            delay=True,
            level=logging.ERROR,
        )
        assert config.max_bytes == 1024 * 1024
        assert config.backup_count == 5
        assert config.level == logging.ERROR

    def test_create_handler_with_int_level(self, temp_log_dir, log_config):
        """Test create_handler with integer level."""
        log_file = temp_log_dir / "test.log"
        config = RotatingFileHandlerConfig(log_file, level=logging.ERROR)
        handler = config.create_handler(log_config)

        assert isinstance(handler, logging.handlers.RotatingFileHandler)
        assert handler.level == logging.ERROR
        handler.close()

    def test_create_handler_with_string_level(self, temp_log_dir, log_config):
        """Test create_handler with string level (line 94)."""
        log_file = temp_log_dir / "test.log"
        config = RotatingFileHandlerConfig(log_file, level="WARNING")
        handler = config.create_handler(log_config)

        assert handler.level == logging.WARNING
        handler.close()

    def test_create_handler_with_lowercase_string_level(self, temp_log_dir, log_config):
        """Test create_handler with lowercase string level."""
        log_file = temp_log_dir / "test.log"
        config = RotatingFileHandlerConfig(log_file, level="info")
        handler = config.create_handler(log_config)

        assert handler.level == logging.INFO
        handler.close()

    def test_create_handler_uses_config_level_when_none(self, temp_log_dir, log_config):
        """Test create_handler uses LogConfig level when handler level is None."""
        log_file = temp_log_dir / "test.log"
        config = RotatingFileHandlerConfig(log_file, level=None)
        handler = config.create_handler(log_config)

        assert handler.level == logging.DEBUG
        handler.close()

    def test_create_handler_with_rotation_params(self, temp_log_dir, log_config):
        """Test create_handler with rotation parameters."""
        log_file = temp_log_dir / "test.log"
        config = RotatingFileHandlerConfig(log_file, max_bytes=1024, backup_count=3)
        handler = config.create_handler(log_config)

        assert handler.maxBytes == 1024
        assert handler.backupCount == 3
        handler.close()


# =============================================================================
# Test TimedRotatingFileHandlerConfig
# =============================================================================


@pytest.mark.unit
class TestTimedRotatingFileHandlerConfig:
    """Test TimedRotatingFileHandlerConfig class."""

    def test_init_basic(self):
        """Test basic initialization."""
        config = TimedRotatingFileHandlerConfig("test.log")
        assert config.filename == "test.log"
        assert config.when == "h"
        assert config.interval == 1
        assert config.backup_count == 0
        assert config.utc is False
        assert config.level is None

    def test_init_all_params(self):
        """Test initialization with all parameters."""
        config = TimedRotatingFileHandlerConfig(
            filename="test.log",
            when="midnight",
            interval=1,
            backup_count=7,
            encoding="utf-8",
            delay=True,
            utc=True,
            level=logging.WARNING,
        )
        assert config.when == "midnight"
        assert config.backup_count == 7
        assert config.utc is True
        assert config.level == logging.WARNING

    def test_create_handler_with_int_level(self, temp_log_dir, log_config):
        """Test create_handler with integer level."""
        log_file = temp_log_dir / "test.log"
        config = TimedRotatingFileHandlerConfig(log_file, level=logging.WARNING)
        handler = config.create_handler(log_config)

        assert isinstance(handler, logging.handlers.TimedRotatingFileHandler)
        assert handler.level == logging.WARNING
        handler.close()

    def test_create_handler_with_string_level(self, temp_log_dir, log_config):
        """Test create_handler with string level (line 144)."""
        log_file = temp_log_dir / "test.log"
        config = TimedRotatingFileHandlerConfig(log_file, level="CRITICAL")
        handler = config.create_handler(log_config)

        assert handler.level == logging.CRITICAL
        handler.close()

    def test_create_handler_with_lowercase_string_level(self, temp_log_dir, log_config):
        """Test create_handler with lowercase string level."""
        log_file = temp_log_dir / "test.log"
        config = TimedRotatingFileHandlerConfig(log_file, level="debug")
        handler = config.create_handler(log_config)

        assert handler.level == logging.DEBUG
        handler.close()

    def test_create_handler_uses_config_level_when_none(self, temp_log_dir, log_config):
        """Test create_handler uses LogConfig level when handler level is None."""
        log_file = temp_log_dir / "test.log"
        config = TimedRotatingFileHandlerConfig(log_file, level=None)
        handler = config.create_handler(log_config)

        assert handler.level == logging.DEBUG
        handler.close()

    def test_create_handler_with_timed_params(self, temp_log_dir, log_config):
        """Test create_handler with timed rotation parameters."""
        log_file = temp_log_dir / "test.log"
        config = TimedRotatingFileHandlerConfig(
            log_file, when="midnight", interval=1, backup_count=7, utc=True
        )
        handler = config.create_handler(log_config)

        assert handler.when == "MIDNIGHT"  # Normalized to uppercase
        assert handler.backupCount == 7
        assert handler.utc is True
        handler.close()


# =============================================================================
# Test FileLoggingBuilder
# =============================================================================


@pytest.mark.unit
class TestFileLoggingBuilder:
    """Test FileLoggingBuilder class."""

    def test_init(self, temp_log_dir):
        """Test basic initialization."""
        log_file = temp_log_dir / "test.log"
        builder = FileLoggingBuilder("test_logger", log_file)

        assert builder._file_path == log_file
        assert len(builder._handlers) == 1

    def test_with_rotation(self, temp_log_dir):
        """Test with_rotation method."""
        log_file = temp_log_dir / "test.log"
        builder = FileLoggingBuilder("test_logger", log_file)
        result = builder.with_rotation(max_bytes=1024, backup_count=3)

        assert result is builder  # Method chaining
        assert len(builder._handlers) == 1
        assert isinstance(builder._handlers[0], RotatingFileHandlerConfig)

    def test_with_timed_rotation(self, temp_log_dir):
        """Test with_timed_rotation method."""
        log_file = temp_log_dir / "test.log"
        builder = FileLoggingBuilder("test_logger", log_file)
        result = builder.with_timed_rotation(when="D", interval=1, backup_count=7)

        assert result is builder  # Method chaining
        assert len(builder._handlers) == 1
        assert isinstance(builder._handlers[0], TimedRotatingFileHandlerConfig)

    def test_daily_rotation(self, temp_log_dir):
        """Test daily_rotation method."""
        log_file = temp_log_dir / "test.log"
        builder = FileLoggingBuilder("test_logger", log_file)
        result = builder.daily_rotation(backup_count=14)

        assert result is builder
        assert len(builder._handlers) == 1
        handler_config = builder._handlers[0]
        assert isinstance(handler_config, TimedRotatingFileHandlerConfig)
        assert handler_config.when == "midnight"
        assert handler_config.backup_count == 14

    def test_hourly_rotation(self, temp_log_dir):
        """Test hourly_rotation method (line 258)."""
        log_file = temp_log_dir / "test.log"
        builder = FileLoggingBuilder("test_logger", log_file)
        result = builder.hourly_rotation(backup_count=48)

        assert result is builder
        assert len(builder._handlers) == 1
        handler_config = builder._handlers[0]
        assert isinstance(handler_config, TimedRotatingFileHandlerConfig)
        assert handler_config.when == "H"
        assert handler_config.backup_count == 48

    def test_hourly_rotation_default_backup_count(self, temp_log_dir):
        """Test hourly_rotation with default backup_count."""
        log_file = temp_log_dir / "test.log"
        builder = FileLoggingBuilder("test_logger", log_file)
        builder.hourly_rotation()

        handler_config = builder._handlers[0]
        assert handler_config.backup_count == 24  # Default

    def test_weekly_rotation(self, temp_log_dir):
        """Test weekly_rotation method (line 270)."""
        log_file = temp_log_dir / "test.log"
        builder = FileLoggingBuilder("test_logger", log_file)
        result = builder.weekly_rotation(backup_count=8)

        assert result is builder
        assert len(builder._handlers) == 1
        handler_config = builder._handlers[0]
        assert isinstance(handler_config, TimedRotatingFileHandlerConfig)
        assert handler_config.when == "W0"
        assert handler_config.backup_count == 8

    def test_weekly_rotation_default_backup_count(self, temp_log_dir):
        """Test weekly_rotation with default backup_count."""
        log_file = temp_log_dir / "test.log"
        builder = FileLoggingBuilder("test_logger", log_file)
        builder.weekly_rotation()

        handler_config = builder._handlers[0]
        assert handler_config.backup_count == 4  # Default

    def test_rotation_replaces_existing_handler(self, temp_log_dir):
        """Test that rotation methods replace existing file handler."""
        log_file = temp_log_dir / "test.log"
        builder = FileLoggingBuilder("test_logger", log_file)

        # Initially has FileHandlerConfig
        assert isinstance(builder._handlers[0], FileHandlerConfig)

        # Switch to rotation
        builder.with_rotation(max_bytes=1024, backup_count=3)
        assert len(builder._handlers) == 1
        assert isinstance(builder._handlers[0], RotatingFileHandlerConfig)

        # Switch to timed rotation
        builder.with_timed_rotation(when="H")
        assert len(builder._handlers) == 1
        assert isinstance(builder._handlers[0], TimedRotatingFileHandlerConfig)


# =============================================================================
# Test create_file_logger function
# =============================================================================


@pytest.mark.unit
class TestCreateFileLogger:
    """Test create_file_logger convenience function."""

    def test_create_file_logger_basic(self, temp_log_dir):
        """Test create_file_logger function (line 287)."""
        log_file = temp_log_dir / "test.log"
        builder = create_file_logger("my_logger", log_file)

        assert isinstance(builder, FileLoggingBuilder)
        assert builder._file_path == log_file

    def test_create_file_logger_with_string_path(self, temp_log_dir):
        """Test create_file_logger with string path."""
        log_file = str(temp_log_dir / "test.log")
        builder = create_file_logger("my_logger", log_file)

        assert isinstance(builder, FileLoggingBuilder)
        assert builder._file_path == log_file

    def test_create_file_logger_returns_builder_for_chaining(self, temp_log_dir):
        """Test create_file_logger returns builder for method chaining."""
        log_file = temp_log_dir / "test.log"
        builder = create_file_logger("my_logger", log_file)

        # Should be able to chain methods
        result = builder.with_level(logging.WARNING).with_rotation(1024, 3)
        assert result is builder


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestIntegrationScenarios:
    """Test real-world file logging scenarios."""

    def test_file_builder_build_logger(self, temp_log_dir):
        """Test building a complete file logger."""
        log_file = temp_log_dir / "app.log"
        builder = FileLoggingBuilder("app_logger", log_file)
        builder.with_level(logging.DEBUG)

        logger = builder.build()

        assert logger is not None
        # Clean up handlers
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    def test_file_builder_with_rotation_build(self, temp_log_dir):
        """Test building a rotating file logger."""
        log_file = temp_log_dir / "app.log"
        builder = (
            FileLoggingBuilder("app_logger", log_file)
            .with_level(logging.INFO)
            .with_rotation(max_bytes=10240, backup_count=5)
        )

        logger = builder.build()

        assert logger is not None
        # Clean up handlers
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    def test_daily_rotation_full_workflow(self, temp_log_dir):
        """Test daily rotation configuration workflow."""
        log_file = temp_log_dir / "daily.log"
        builder = (
            create_file_logger("daily_logger", log_file)
            .daily_rotation(backup_count=30)
            .with_level(logging.INFO)
        )

        # Verify configuration
        handler_config = builder._handlers[0]
        assert isinstance(handler_config, TimedRotatingFileHandlerConfig)
        assert handler_config.when == "midnight"
        assert handler_config.backup_count == 30

    def test_hourly_rotation_full_workflow(self, temp_log_dir):
        """Test hourly rotation configuration workflow."""
        log_file = temp_log_dir / "hourly.log"
        builder = (
            create_file_logger("hourly_logger", log_file)
            .hourly_rotation(backup_count=72)
            .with_level(logging.DEBUG)
        )

        handler_config = builder._handlers[0]
        assert handler_config.when == "H"
        assert handler_config.backup_count == 72
