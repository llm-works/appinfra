# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for console logging builder.

Tests console logging functionality including:
- ConsoleHandlerConfig configuration
- Handler creation with different formats
- Stream configuration
- ConsoleLoggingBuilder methods
"""

import logging
import sys
from io import StringIO

import pytest

from appinfra.log.builder.console import (
    ConsoleHandlerConfig,
    ConsoleLoggingBuilder,
    create_console_logger,
)
from appinfra.log.builder.json import JSONFormatter
from appinfra.log.config import LogConfig
from appinfra.log.logger import Logger

# =============================================================================
# Test ConsoleHandlerConfig
# =============================================================================


@pytest.mark.unit
class TestConsoleHandlerConfig:
    """Test ConsoleHandlerConfig initialization and handler creation."""

    def test_default_initialization(self):
        """Test ConsoleHandlerConfig with default settings."""
        import sys

        config = ConsoleHandlerConfig()

        assert config.stream is sys.stdout
        assert config.level is None
        assert config.format == "text"
        assert config.format_options == {}

    def test_custom_initialization(self):
        """Test ConsoleHandlerConfig with custom settings."""
        stream = StringIO()
        config = ConsoleHandlerConfig(
            stream=stream,
            level="DEBUG",
            format="json",
        )

        assert config.stream is stream
        assert config.level == "DEBUG"
        assert config.format == "json"

    def test_format_options_extraction(self):
        """Test that format_ prefixed kwargs are extracted."""
        config = ConsoleHandlerConfig(
            format="json",
            format_timestamp_format="unix",
            format_pretty_print=True,
            format_custom_fields={"app": "test"},
        )

        assert config.format_options["timestamp_format"] == "unix"
        assert config.format_options["pretty_print"] is True
        assert config.format_options["custom_fields"] == {"app": "test"}

    def test_create_handler_text_format(self):
        """Test creating handler with text format."""
        stream = StringIO()
        handler_config = ConsoleHandlerConfig(stream=stream, format="text")
        log_config = LogConfig.from_params("info")

        handler = handler_config.create_handler(log_config)

        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is stream
        assert handler.level == logging.INFO

    def test_create_handler_json_format(self):
        """Test creating handler with JSON format."""
        stream = StringIO()
        handler_config = ConsoleHandlerConfig(
            stream=stream,
            format="json",
            format_timestamp_format="unix",
            format_pretty_print=True,
        )
        log_config = LogConfig.from_params("debug")

        handler = handler_config.create_handler(log_config)

        assert isinstance(handler, logging.StreamHandler)
        assert isinstance(handler.formatter, JSONFormatter)
        assert handler.formatter.timestamp_format == "unix"
        assert handler.formatter.pretty_print is True

    def test_create_handler_json_with_custom_fields(self):
        """Test JSON handler with custom fields and exclude_fields."""
        stream = StringIO()
        handler_config = ConsoleHandlerConfig(
            stream=stream,
            format="json",
            format_custom_fields={"service": "api"},
            format_exclude_fields=["module", "function"],
        )
        log_config = LogConfig.from_params("info")

        handler = handler_config.create_handler(log_config)

        assert isinstance(handler.formatter, JSONFormatter)
        assert handler.formatter.custom_fields == {"service": "api"}
        assert handler.formatter.exclude_fields == {"module", "function"}

    def test_create_handler_with_string_level(self):
        """Test handler creation with string level."""
        handler_config = ConsoleHandlerConfig(level="WARNING")
        log_config = LogConfig.from_params("debug")

        handler = handler_config.create_handler(log_config)

        assert handler.level == logging.WARNING

    def test_create_handler_with_int_level(self):
        """Test handler creation with integer level."""
        handler_config = ConsoleHandlerConfig(level=logging.ERROR)
        log_config = LogConfig.from_params("debug")

        handler = handler_config.create_handler(log_config)

        assert handler.level == logging.ERROR

    def test_create_handler_uses_config_level_when_none(self):
        """Test handler uses log config level when handler level is None."""
        handler_config = ConsoleHandlerConfig(level=None)
        log_config = LogConfig.from_params("warning")

        handler = handler_config.create_handler(log_config)

        assert handler.level == logging.WARNING

    def test_create_handler_json_case_insensitive(self):
        """Test that format='JSON' (uppercase) works."""
        handler_config = ConsoleHandlerConfig(format="JSON")
        log_config = LogConfig.from_params("info")

        handler = handler_config.create_handler(log_config)

        assert isinstance(handler.formatter, JSONFormatter)


# =============================================================================
# Test ConsoleLoggingBuilder
# =============================================================================


@pytest.mark.unit
class TestConsoleLoggingBuilder:
    """Test ConsoleLoggingBuilder configuration and building."""

    def test_default_initialization(self):
        """Test ConsoleLoggingBuilder default initialization."""
        builder = ConsoleLoggingBuilder("test.logger")

        assert builder._name == "test.logger"
        # Should have a console handler by default
        assert len(builder._handlers) >= 1

    def test_with_colors_enabled(self):
        """Test enabling colors."""
        builder = ConsoleLoggingBuilder("test").with_colors(True)
        assert builder._colors is True

    def test_with_colors_disabled(self):
        """Test disabling colors."""
        builder = ConsoleLoggingBuilder("test").with_colors(False)
        assert builder._colors is False

    def test_with_stream(self):
        """Test setting custom stream."""
        stream = StringIO()
        builder = ConsoleLoggingBuilder("test").with_stream(stream)

        # Should have replaced the console handler
        console_handlers = [
            h for h in builder._handlers if isinstance(h, ConsoleHandlerConfig)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].stream is stream

    def test_stdout_method(self):
        """Test stdout() convenience method."""
        builder = ConsoleLoggingBuilder("test").stdout()

        console_handlers = [
            h for h in builder._handlers if isinstance(h, ConsoleHandlerConfig)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].stream is sys.stdout

    def test_stderr_method(self):
        """Test stderr() convenience method."""
        builder = ConsoleLoggingBuilder("test").stderr()

        console_handlers = [
            h for h in builder._handlers if isinstance(h, ConsoleHandlerConfig)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].stream is sys.stderr

    def test_method_chaining(self):
        """Test that methods return self for chaining."""
        stream = StringIO()
        builder = (
            ConsoleLoggingBuilder("test")
            .with_colors(True)
            .with_stream(stream)
            .with_level("DEBUG")
        )

        assert isinstance(builder, ConsoleLoggingBuilder)
        assert builder._colors is True

    def test_build_returns_logger(self):
        """Test that build() returns a Logger instance."""
        logger = ConsoleLoggingBuilder("test.logger").build()

        assert isinstance(logger, Logger)
        assert logger.name == "test.logger"

    def test_build_with_custom_stream(self):
        """Test building logger with custom stream."""
        stream = StringIO()
        logger = ConsoleLoggingBuilder("test").with_stream(stream).build()

        assert isinstance(logger, Logger)
        logger.info("Test message")
        # Message should be in the stream
        output = stream.getvalue()
        assert "Test message" in output


# =============================================================================
# Test create_console_logger factory
# =============================================================================


@pytest.mark.unit
class TestCreateConsoleLogger:
    """Test create_console_logger factory function."""

    def test_returns_builder(self):
        """Test that create_console_logger returns a ConsoleLoggingBuilder."""
        builder = create_console_logger("test.logger")

        assert isinstance(builder, ConsoleLoggingBuilder)
        assert builder._name == "test.logger"

    def test_chainable(self):
        """Test that returned builder supports chaining."""
        logger = (
            create_console_logger("test.logger")
            .with_colors(False)
            .with_level("debug")
            .build()
        )

        assert isinstance(logger, Logger)


# =============================================================================
# Integration tests
# =============================================================================


@pytest.mark.integration
class TestConsoleLoggingIntegration:
    """Integration tests for console logging."""

    def test_full_console_logging_workflow(self):
        """Test complete console logging workflow."""
        stream = StringIO()

        logger = (
            create_console_logger("integration.test")
            .with_stream(stream)
            .with_colors(False)
            .with_level("debug")
            .build()
        )

        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")

        output = stream.getvalue()
        assert "Debug message" in output
        assert "Info message" in output
        assert "Warning message" in output

    def test_console_logging_with_stderr(self):
        """Test console logging to stderr."""
        # Just verify it doesn't crash
        logger = (
            create_console_logger("stderr.test").stderr().with_level("error").build()
        )

        assert isinstance(logger, Logger)

    def test_json_console_output(self):
        """Test JSON formatted console output via ConsoleHandlerConfig."""
        stream = StringIO()

        # Create JSON handler config directly
        handler_config = ConsoleHandlerConfig(
            stream=stream,
            format="json",
            format_pretty_print=False,
        )
        log_config = LogConfig.from_params("info")

        handler = handler_config.create_handler(log_config)

        # Create a basic logger and add the handler
        import logging

        logger = logging.getLogger("json.console.test")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        logger.addHandler(handler)

        logger.info("JSON test message")

        output = stream.getvalue()
        # Should be valid JSON
        import json as json_module

        data = json_module.loads(output.strip())
        assert data["message"] == "JSON test message"
        assert data["level"] == "INFO"
