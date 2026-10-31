# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for base logging builder that add file handlers and build loggers.
"""

import logging
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from appinfra.log.builder.builder import LoggingBuilder, create_logger
from appinfra.log.builder.interface import HandlerConfig

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_log_dir():
    """Create temporary directory for log files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# =============================================================================
# Test Handler Methods
# =============================================================================


class TestHandlerMethods:
    """Test handler configuration methods."""

    @pytest.mark.unit
    def test_with_handler(self):
        """Test with_handler adds handler config."""
        builder = LoggingBuilder("test")
        mock_handler = Mock(spec=HandlerConfig)

        result = builder.with_handler(mock_handler)

        assert result is builder
        assert len(builder._handlers) == 1
        assert builder._handlers[0] is mock_handler

    @pytest.mark.unit
    def test_with_console_handler(self):
        """Test with_console_handler."""
        builder = LoggingBuilder("test")
        result = builder.with_console_handler()

        assert result is builder
        assert len(builder._handlers) == 1

    def test_with_file_handler(self, temp_log_dir):
        """Test with_file_handler."""
        log_file = temp_log_dir / "test.log"
        builder = LoggingBuilder("test")
        result = builder.with_file_handler(log_file)

        assert result is builder
        assert len(builder._handlers) == 1

    def test_with_rotating_file_handler(self, temp_log_dir):
        """Test with_rotating_file_handler."""
        log_file = temp_log_dir / "test.log"
        builder = LoggingBuilder("test")
        result = builder.with_rotating_file_handler(
            log_file, max_bytes=1024, backup_count=3
        )

        assert result is builder
        assert len(builder._handlers) == 1

    def test_with_timed_rotating_file_handler(self, temp_log_dir):
        """Test with_timed_rotating_file_handler."""
        log_file = temp_log_dir / "test.log"
        builder = LoggingBuilder("test")
        result = builder.with_timed_rotating_file_handler(
            log_file, when="midnight", backup_count=7
        )

        assert result is builder
        assert len(builder._handlers) == 1


# =============================================================================
# Test Integration Scenarios
# =============================================================================


class TestIntegrationScenarios:
    """Test real-world builder usage scenarios."""

    def test_full_builder_chain(self, temp_log_dir):
        """Test complete builder configuration chain."""
        log_file = temp_log_dir / "app.log"
        builder = (
            create_logger("app")
            .with_level("debug")
            .with_location(1)
            .with_micros()
            .with_colors(False)
            .with_extra(service="test", version="1.0")
            .with_file_handler(log_file)
        )

        assert builder._level == "debug"
        assert builder._location == 1
        assert builder._micros is True
        assert builder._colors is False
        assert builder._extra == {"service": "test", "version": "1.0"}
        assert len(builder._handlers) == 1

    def test_build_logger_with_file_handler(self, temp_log_dir):
        """Test building complete logger with file handler."""
        log_file = temp_log_dir / "app.log"
        builder = (
            LoggingBuilder("test_app")
            .with_level(logging.INFO)
            .with_file_handler(log_file)
        )

        logger = builder.build()

        assert logger is not None
        assert len(logger.handlers) == 1

        # Clean up
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    @pytest.mark.unit
    def test_build_with_extra_fields(self):
        """Test that extra fields are passed to logger."""
        builder = (
            LoggingBuilder("extra_test")
            .with_level("debug")
            .with_extra(service="api", version="2.0")
            .with_console_handler()
        )

        logger = builder.build()
        assert logger is not None

        # Clean up
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    def test_multiple_handlers(self, temp_log_dir):
        """Test builder with multiple handlers."""
        log_file = temp_log_dir / "multi.log"
        builder = (
            LoggingBuilder("multi")
            .with_level("info")
            .with_console_handler()
            .with_file_handler(log_file)
        )

        assert len(builder._handlers) == 2

        logger = builder.build()
        assert len(logger.handlers) == 2

        # Clean up
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
