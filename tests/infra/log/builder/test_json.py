# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for JSON logging builder and formatter.

Tests JSON logging functionality including:
- JSONFormatter configuration and output
- Field inclusion/exclusion
- Timestamp formats
- Extra field sanitization
- Exception formatting
- JSONLoggingBuilder configuration
- Handler setup and output
"""

import json
import logging
import os
import tempfile
from unittest.mock import patch

import pytest

from appinfra.log.builder.json import (
    JSONFormatter,
    JSONLoggingBuilder,
    _add_basic_fields,
    _add_custom_fields,
    _add_exception_fields,
    _add_extra_fields,
    _add_location_fields,
    _add_module_fields,
    _add_process_fields,
    _add_timestamp,
    create_json_logger,
)
from appinfra.log.logger import Logger

# =============================================================================
# Helper function for creating mock log records
# =============================================================================


def create_mock_record(
    level: str = "INFO",
    msg: str = "Test message",
    name: str = "test.logger",
    module: str = "test_module",
    func_name: str = "test_function",
    lineno: int = 42,
    pathname: str = "/path/to/test.py",
    created: float = 1700000000.123456,
    process: int = 12345,
    thread: int = 67890,
    exc_info=None,
    extra: dict = None,
) -> logging.LogRecord:
    """Create a mock LogRecord for testing."""
    record = logging.LogRecord(
        name=name,
        level=getattr(logging, level),
        pathname=pathname,
        lineno=lineno,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    record.module = module
    record.funcName = func_name
    record.created = created
    record.process = process
    record.thread = thread
    if extra:
        record.__infra__extra = extra
    return record


# =============================================================================
# Test JSONFormatter initialization
# =============================================================================


@pytest.mark.unit
class TestJSONFormatterInit:
    """Test JSONFormatter initialization and configuration."""

    def test_default_initialization(self):
        """Test JSONFormatter with default settings."""
        formatter = JSONFormatter()

        assert formatter.include_extra is True
        assert formatter.include_location is True
        assert formatter.include_process_info is True
        assert formatter.include_exception is True
        assert formatter.include_fields is None
        assert formatter.exclude_fields is None
        assert formatter.pretty_print is False
        assert formatter.timestamp_format == "iso"
        assert formatter.custom_fields == {}

    def test_custom_initialization(self):
        """Test JSONFormatter with custom settings."""
        formatter = JSONFormatter(
            include_extra=False,
            include_location=False,
            include_process_info=False,
            include_exception=False,
            include_fields=["timestamp", "level", "message"],
            exclude_fields=["module"],
            pretty_print=True,
            timestamp_format="unix",
            custom_fields={"app": "test_app"},
        )

        assert formatter.include_extra is False
        assert formatter.include_location is False
        assert formatter.include_process_info is False
        assert formatter.include_exception is False
        assert formatter.include_fields == {"timestamp", "level", "message"}
        assert formatter.exclude_fields == {"module"}
        assert formatter.pretty_print is True
        assert formatter.timestamp_format == "unix"
        assert formatter.custom_fields == {"app": "test_app"}

    def test_standard_fields_defined(self):
        """Test that standard fields are properly defined."""
        formatter = JSONFormatter()
        expected_fields = {
            "timestamp",
            "level",
            "logger",
            "message",
            "module",
            "function",
            "line",
            "process_id",
            "thread_id",
            "extra",
            "exception",
            "location",
        }
        assert formatter._standard_fields == expected_fields


# =============================================================================
# Test should_include_field
# =============================================================================


@pytest.mark.unit
class TestShouldIncludeField:
    """Test field inclusion/exclusion logic."""

    def test_include_field_no_filters(self):
        """Test field inclusion when no filters are set."""
        formatter = JSONFormatter()
        assert formatter.should_include_field("timestamp") is True
        assert formatter.should_include_field("custom_field") is True

    def test_exclude_fields_filter(self):
        """Test field exclusion with exclude_fields."""
        formatter = JSONFormatter(exclude_fields=["module", "function"])

        assert formatter.should_include_field("module") is False
        assert formatter.should_include_field("function") is False
        assert formatter.should_include_field("timestamp") is True
        assert formatter.should_include_field("level") is True

    def test_include_fields_filter(self):
        """Test field inclusion with include_fields whitelist."""
        formatter = JSONFormatter(include_fields=["timestamp", "level", "message"])

        assert formatter.should_include_field("timestamp") is True
        assert formatter.should_include_field("level") is True
        assert formatter.should_include_field("message") is True
        assert formatter.should_include_field("module") is False
        assert formatter.should_include_field("function") is False

    def test_exclude_takes_precedence(self):
        """Test that exclude_fields takes precedence over include_fields."""
        formatter = JSONFormatter(
            include_fields=["timestamp", "level", "message"],
            exclude_fields=["level"],
        )

        assert formatter.should_include_field("timestamp") is True
        assert formatter.should_include_field("level") is False
        assert formatter.should_include_field("message") is True


# =============================================================================
# Test timestamp formatting
# =============================================================================


@pytest.mark.unit
class TestTimestampFormatting:
    """Test timestamp format options."""

    def test_iso_format(self):
        """Test ISO timestamp format."""
        formatter = JSONFormatter(timestamp_format="iso")
        record = create_mock_record(created=1700000000.123456)

        timestamp = formatter._format_timestamp(record)
        # ISO format should contain date separator and time
        assert "T" in timestamp
        assert "-" in timestamp
        assert ":" in timestamp

    def test_unix_format(self):
        """Test Unix timestamp format."""
        formatter = JSONFormatter(timestamp_format="unix")
        record = create_mock_record(created=1700000000.123456)

        timestamp = formatter._format_timestamp(record)
        assert timestamp == "1700000000.123456"

    def test_epoch_format(self):
        """Test epoch (integer) timestamp format."""
        formatter = JSONFormatter(timestamp_format="epoch")
        record = create_mock_record(created=1700000000.123456)

        timestamp = formatter._format_timestamp(record)
        assert timestamp == "1700000000"

    def test_unknown_format_defaults_to_iso(self):
        """Test that unknown timestamp format defaults to ISO."""
        formatter = JSONFormatter(timestamp_format="invalid_format")
        record = create_mock_record(created=1700000000.123456)

        timestamp = formatter._format_timestamp(record)
        # Should default to ISO format
        assert "T" in timestamp


# =============================================================================
# Test extra field sanitization
# =============================================================================


@pytest.mark.unit
class TestSanitizeExtraFields:
    """Test extra field sanitization for JSON serialization."""

    def test_sanitize_serializable_fields(self):
        """Test that serializable fields pass through unchanged."""
        formatter = JSONFormatter()
        extra = {
            "string": "value",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
        }

        sanitized = formatter._sanitize_extra_fields(extra)

        assert sanitized["string"] == "value"
        assert sanitized["number"] == 42
        assert sanitized["float"] == 3.14
        assert sanitized["bool"] is True
        assert sanitized["list"] == [1, 2, 3]
        assert sanitized["dict"] == {"nested": "value"}

    def test_sanitize_non_serializable_fields(self):
        """Test that non-serializable fields are converted to strings."""
        formatter = JSONFormatter()

        class CustomObject:
            def __str__(self):
                return "CustomObject()"

        extra = {
            "custom": CustomObject(),
            "set": {1, 2, 3},
        }

        sanitized = formatter._sanitize_extra_fields(extra)

        assert sanitized["custom"] == "CustomObject()"
        # Sets are converted to string representation
        assert isinstance(sanitized["set"], str)


# =============================================================================
# Test location extraction
# =============================================================================


@pytest.mark.unit
class TestExtractLocation:
    """Test location extraction from log records."""

    def test_extract_single_location(self):
        """Test extracting location from standard record."""
        formatter = JSONFormatter()
        record = create_mock_record(pathname="/path/to/file.py", lineno=42)

        locations = formatter._extract_location(record)

        assert locations == ["/path/to/file.py:42"]

    def test_extract_multiple_locations(self):
        """Test extracting multiple locations from __infra__ attributes."""
        formatter = JSONFormatter()
        record = create_mock_record()
        # Standard attributes stay as single values
        record.pathname = "/path/to/file1.py"
        record.lineno = 10
        # Multi-location trace in __infra__ prefixed attributes (use setattr to avoid mangling)
        setattr(
            record, "__infra__pathnames", ["/path/to/file1.py", "/path/to/file2.py"]
        )
        setattr(record, "__infra__linenos", [10, 20])

        locations = formatter._extract_location(record)

        assert locations == ["/path/to/file1.py:10", "/path/to/file2.py:20"]

    def test_extract_multiple_locations_fallback(self):
        """Test fallback to standard attributes when __infra__ not present."""
        formatter = JSONFormatter()
        record = create_mock_record(pathname="/path/to/file.py", lineno=42)

        locations = formatter._extract_location(record)

        assert locations == ["/path/to/file.py:42"]

    def test_extract_no_location(self):
        """Test extraction when no pathname."""
        formatter = JSONFormatter()
        record = create_mock_record()
        record.pathname = None

        locations = formatter._extract_location(record)

        assert locations is None


# =============================================================================
# Test exception formatting
# =============================================================================


@pytest.mark.unit
class TestFormatException:
    """Test exception traceback formatting."""

    def test_format_exception_none(self):
        """Test formatting None exception info."""
        formatter = JSONFormatter()
        result = formatter._format_exception(None)
        assert result is None

    def test_format_exception_with_traceback(self):
        """Test formatting actual exception info."""
        formatter = JSONFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        result = formatter._format_exception(exc_info)

        assert "ValueError" in result
        assert "Test error" in result
        assert "Traceback" in result

    def test_format_exception_error_handling(self):
        """Test fallback when traceback formatting fails."""
        formatter = JSONFormatter()

        # Create invalid exc_info that will cause format_exception to fail
        exc_info = (ValueError, ValueError("Test"), None)

        # Even with minimal exc_info, should not raise
        result = formatter._format_exception(exc_info)
        # Should contain some error info
        assert result is not None


# =============================================================================
# Test dict to JSON conversion
# =============================================================================


@pytest.mark.unit
class TestDictToJson:
    """Test dictionary to JSON string conversion."""

    def test_compact_json(self):
        """Test compact JSON output."""
        formatter = JSONFormatter(pretty_print=False)
        data = {"key": "value", "number": 42}

        result = formatter._dict_to_json(data)

        # Should be compact (no newlines or extra spaces)
        assert "\n" not in result
        assert json.loads(result) == data

    def test_pretty_print_json(self):
        """Test pretty-printed JSON output."""
        formatter = JSONFormatter(pretty_print=True)
        data = {"key": "value", "number": 42}

        result = formatter._dict_to_json(data)

        # Should have indentation
        assert "\n" in result
        assert "  " in result  # 2-space indent
        assert json.loads(result) == data

    def test_unicode_handling(self):
        """Test that Unicode is preserved."""
        formatter = JSONFormatter()
        data = {"message": "Hello \u4e16\u754c"}  # Chinese characters

        result = formatter._dict_to_json(data)

        assert "\u4e16\u754c" in result or "\\u" not in result
        assert json.loads(result)["message"] == "Hello \u4e16\u754c"


# =============================================================================
# Test format method (full formatting)
# =============================================================================


@pytest.mark.unit
class TestFormat:
    """Test complete record formatting."""

    def test_format_basic_record(self):
        """Test formatting a basic log record."""
        formatter = JSONFormatter()
        record = create_mock_record()

        result = formatter.format(record)
        data = json.loads(result)

        assert "timestamp" in data
        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "Test message"

    def test_format_with_extra_fields(self):
        """Test formatting record with extra fields."""
        formatter = JSONFormatter(include_extra=True)
        record = create_mock_record(extra={"user_id": 123, "request_id": "abc"})

        result = formatter.format(record)
        data = json.loads(result)

        assert "extra" in data
        assert data["extra"]["user_id"] == 123
        assert data["extra"]["request_id"] == "abc"

    def test_format_with_custom_fields(self):
        """Test formatting with custom fields."""
        formatter = JSONFormatter(custom_fields={"app": "myapp", "version": "1.0"})
        record = create_mock_record()

        result = formatter.format(record)
        data = json.loads(result)

        assert data["app"] == "myapp"
        assert data["version"] == "1.0"

    def test_format_with_field_exclusion(self):
        """Test formatting with excluded fields."""
        formatter = JSONFormatter(exclude_fields=["module", "function", "line"])
        record = create_mock_record()

        result = formatter.format(record)
        data = json.loads(result)

        assert "module" not in data
        assert "function" not in data
        assert "line" not in data
        assert "timestamp" in data
        assert "level" in data

    def test_format_fallback_on_error(self):
        """Test fallback formatting when main formatting fails."""
        formatter = JSONFormatter()

        # Create a record that will cause _record_to_dict to fail
        record = create_mock_record()

        # Mock _record_to_dict to raise an exception
        with patch.object(
            formatter, "_record_to_dict", side_effect=Exception("Test error")
        ):
            result = formatter.format(record)
            data = json.loads(result)

            # Should have fallback fields
            assert "timestamp" in data
            assert "level" in data
            assert "logger" in data
            assert "message" in data
            assert "error" in data
            assert "JSON formatting failed" in data["error"]


# =============================================================================
# Test helper functions
# =============================================================================


@pytest.mark.unit
class TestHelperFunctions:
    """Test helper functions for record conversion."""

    def test_add_timestamp(self):
        """Test _add_timestamp helper."""
        formatter = JSONFormatter()
        record = create_mock_record()
        data = {}

        _add_timestamp(data, formatter, record)

        assert "timestamp" in data

    def test_add_basic_fields(self):
        """Test _add_basic_fields helper."""
        formatter = JSONFormatter()
        record = create_mock_record()
        data = {}

        _add_basic_fields(data, formatter, record)

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "Test message"

    def test_add_module_fields(self):
        """Test _add_module_fields helper."""
        formatter = JSONFormatter()
        record = create_mock_record()
        data = {}

        _add_module_fields(data, formatter, record)

        assert data["module"] == "test_module"
        assert data["function"] == "test_function"
        assert data["line"] == 42

    def test_add_process_fields(self):
        """Test _add_process_fields helper."""
        formatter = JSONFormatter(include_process_info=True)
        record = create_mock_record()
        data = {}

        _add_process_fields(data, formatter, record)

        assert data["process_id"] == 12345
        assert data["thread_id"] == 67890

    def test_add_process_fields_disabled(self):
        """Test _add_process_fields when disabled."""
        formatter = JSONFormatter(include_process_info=False)
        record = create_mock_record()
        data = {}

        _add_process_fields(data, formatter, record)

        assert "process_id" not in data
        assert "thread_id" not in data

    def test_add_extra_fields(self):
        """Test _add_extra_fields helper."""
        formatter = JSONFormatter(include_extra=True)
        record = create_mock_record(extra={"key": "value"})
        data = {}

        _add_extra_fields(data, formatter, record)

        assert "extra" in data
        assert data["extra"]["key"] == "value"

    def test_add_extra_fields_no_extra(self):
        """Test _add_extra_fields when record has no extra."""
        formatter = JSONFormatter(include_extra=True)
        record = create_mock_record()  # No extra
        data = {}

        _add_extra_fields(data, formatter, record)

        assert "extra" not in data

    def test_add_location_fields(self):
        """Test _add_location_fields helper."""
        formatter = JSONFormatter(include_location=True)
        record = create_mock_record()
        data = {}

        _add_location_fields(data, formatter, record)

        assert "location" in data
        assert data["location"] == ["/path/to/test.py:42"]

    def test_add_exception_fields(self):
        """Test _add_exception_fields helper."""
        formatter = JSONFormatter(include_exception=True)
        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            record = create_mock_record(exc_info=sys.exc_info())

        data = {}
        _add_exception_fields(data, formatter, record)

        assert "exception" in data
        assert "ValueError" in data["exception"]

    def test_add_exception_fields_no_exception(self):
        """Test _add_exception_fields when no exception."""
        formatter = JSONFormatter(include_exception=True)
        record = create_mock_record()
        data = {}

        _add_exception_fields(data, formatter, record)

        assert "exception" not in data

    def test_add_custom_fields(self):
        """Test _add_custom_fields helper."""
        formatter = JSONFormatter(custom_fields={"app": "test", "env": "dev"})
        data = {}

        _add_custom_fields(data, formatter)

        assert data["app"] == "test"
        assert data["env"] == "dev"

    def test_add_custom_fields_with_exclusion(self):
        """Test _add_custom_fields respects field exclusion."""
        formatter = JSONFormatter(
            custom_fields={"app": "test", "env": "dev"},
            exclude_fields=["env"],
        )
        data = {}

        _add_custom_fields(data, formatter)

        assert data["app"] == "test"
        assert "env" not in data


# =============================================================================
# Test JSONLoggingBuilder
# =============================================================================


@pytest.mark.unit
class TestJSONLoggingBuilder:
    """Test JSONLoggingBuilder configuration."""

    def test_builder_default_initialization(self):
        """Test builder default configuration."""
        builder = JSONLoggingBuilder("test.logger")

        assert builder._name == "test.logger"
        assert builder._json_console is False
        assert builder._json_file is None
        assert builder._console_output is True

    def test_with_json_console(self):
        """Test enabling JSON console output."""
        builder = JSONLoggingBuilder("test").with_json_console(True)
        assert builder._json_console is True

        builder = JSONLoggingBuilder("test").with_json_console(False)
        assert builder._json_console is False

    def test_with_json_file(self):
        """Test setting JSON file output."""
        builder = JSONLoggingBuilder("test").with_json_file(
            "/path/to/log.json", mode="a", encoding="utf-8"
        )

        assert builder._json_file == "/path/to/log.json"
        assert builder._file_kwargs == {"mode": "a", "encoding": "utf-8"}

    def test_with_json_fields(self):
        """Test field inclusion/exclusion configuration."""
        builder = JSONLoggingBuilder("test").with_json_fields(
            include=["timestamp", "level", "message"],
            exclude=["module"],
        )

        assert builder._json_config["include_fields"] == [
            "timestamp",
            "level",
            "message",
        ]
        assert builder._json_config["exclude_fields"] == ["module"]

    def test_with_pretty_print(self):
        """Test pretty print configuration."""
        builder = JSONLoggingBuilder("test").with_pretty_print(True)
        assert builder._json_config["pretty_print"] is True

        builder = JSONLoggingBuilder("test").with_pretty_print(False)
        assert builder._json_config["pretty_print"] is False

    def test_with_timestamp_format(self):
        """Test timestamp format configuration."""
        builder = JSONLoggingBuilder("test").with_timestamp_format("unix")
        assert builder._json_config["timestamp_format"] == "unix"

        builder = JSONLoggingBuilder("test").with_timestamp_format("epoch")
        assert builder._json_config["timestamp_format"] == "epoch"

    def test_with_custom_fields(self):
        """Test custom fields configuration."""
        builder = JSONLoggingBuilder("test").with_custom_fields(
            {"app": "myapp", "version": "1.0"}
        )

        assert builder._json_config["custom_fields"]["app"] == "myapp"
        assert builder._json_config["custom_fields"]["version"] == "1.0"

    def test_with_custom_fields_merges(self):
        """Test that custom fields merge with existing."""
        builder = (
            JSONLoggingBuilder("test")
            .with_custom_fields({"app": "myapp"})
            .with_custom_fields({"version": "1.0"})
        )

        assert builder._json_config["custom_fields"]["app"] == "myapp"
        assert builder._json_config["custom_fields"]["version"] == "1.0"

    def test_console_only(self):
        """Test console_only configuration."""
        builder = (
            JSONLoggingBuilder("test")
            .with_json_console(True)
            .with_json_file("/path/to/log.json")
            .console_only()
        )

        assert builder._console_output is True
        assert builder._json_console is False
        assert builder._json_file is None

    def test_json_only(self):
        """Test json_only configuration."""
        builder = JSONLoggingBuilder("test").json_only()

        assert builder._console_output is False
        assert builder._json_console is False

    def test_both_outputs(self):
        """Test both_outputs configuration."""
        builder = JSONLoggingBuilder("test").both_outputs()

        assert builder._console_output is True
        assert builder._json_console is True

    def test_method_chaining(self):
        """Test that all methods return self for chaining."""
        builder = (
            JSONLoggingBuilder("test")
            .with_json_console(True)
            .with_json_file("/path/to/log.json")
            .with_json_fields(include=["timestamp"])
            .with_pretty_print(True)
            .with_timestamp_format("unix")
            .with_custom_fields({"key": "value"})
        )

        assert isinstance(builder, JSONLoggingBuilder)


# =============================================================================
# Test JSONLoggingBuilder.build()
# =============================================================================


@pytest.mark.unit
class TestJSONLoggingBuilderBuild:
    """Test JSONLoggingBuilder build method."""

    def test_build_basic_logger(self):
        """Test building a basic logger."""
        logger = JSONLoggingBuilder("test.logger").build()

        assert isinstance(logger, Logger)
        assert logger.name == "test.logger"

    def test_build_with_json_console(self):
        """Test building logger with JSON console handler."""
        logger = JSONLoggingBuilder("test.logger").with_json_console(True).build()

        assert isinstance(logger, Logger)
        # Should have a handler with JSONFormatter
        assert len(logger.handlers) > 0

    def test_build_with_json_file(self):
        """Test building logger with JSON file handler."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            logger = (
                JSONLoggingBuilder("test.logger")
                .json_only()
                .with_json_file(log_file)
                .build()
            )

            assert isinstance(logger, Logger)

            # Log a message
            logger.info("Test message")

            # Verify file was created and contains JSON
            with open(log_file) as f:
                content = f.read()
                data = json.loads(content.strip())
                assert data["message"] == "Test message"
        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_build_creates_directory(self):
        """Test that build creates parent directories for file output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "subdir", "nested", "app.json")

            logger = (
                JSONLoggingBuilder("test.logger")
                .json_only()
                .with_json_file(log_file)
                .build()
            )

            logger.info("Test")

            assert os.path.exists(log_file)

    def test_build_with_regular_console(self):
        """Test building with regular (non-JSON) console output."""
        logger = JSONLoggingBuilder("test.logger").console_only().build()

        assert isinstance(logger, Logger)
        assert len(logger.handlers) > 0

    def test_build_with_both_outputs(self):
        """Test building with both console outputs."""
        logger = JSONLoggingBuilder("test.logger").both_outputs().build()

        assert isinstance(logger, Logger)
        # Should have JSON console handler
        assert len(logger.handlers) > 0


# =============================================================================
# Test create_json_logger factory function
# =============================================================================


@pytest.mark.unit
class TestCreateJsonLogger:
    """Test create_json_logger factory function."""

    def test_create_json_logger_returns_builder(self):
        """Test that create_json_logger returns a JSONLoggingBuilder."""
        builder = create_json_logger("test.logger")

        assert isinstance(builder, JSONLoggingBuilder)
        assert builder._name == "test.logger"

    def test_create_json_logger_chainable(self):
        """Test that returned builder supports chaining."""
        logger = (
            create_json_logger("test.logger")
            .with_json_console(True)
            .with_pretty_print(True)
            .build()
        )

        assert isinstance(logger, Logger)


# =============================================================================
# Integration tests
# =============================================================================


@pytest.mark.integration
class TestJSONLoggingIntegration:
    """Integration tests for JSON logging."""

    def test_full_json_logging_workflow(self):
        """Test complete JSON logging workflow."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            logger = (
                create_json_logger("integration.test")
                .with_json_file(log_file)
                .with_pretty_print(False)
                .with_timestamp_format("unix")
                .with_custom_fields({"app": "test_app", "env": "test"})
                .json_only()
                .build()
            )

            logger.info("Test message")
            logger.warning("Warning message")

            with open(log_file) as f:
                lines = f.readlines()

            assert len(lines) == 2

            data1 = json.loads(lines[0])
            assert data1["level"] == "INFO"
            assert data1["message"] == "Test message"
            assert data1["app"] == "test_app"
            assert data1["env"] == "test"

            data2 = json.loads(lines[1])
            assert data2["level"] == "WARNING"
            assert data2["message"] == "Warning message"

        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_json_logging_with_exception(self):
        """Test JSON logging with exception information."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            logger = (
                create_json_logger("exception.test")
                .with_json_file(log_file)
                .json_only()
                .build()
            )

            try:
                raise ValueError("Test exception")
            except ValueError:
                logger.exception("An error occurred")

            with open(log_file) as f:
                content = f.read().strip()
                data = json.loads(content)

            assert data["level"] == "ERROR"
            assert "exception" in data
            assert "ValueError" in data["exception"]
            assert "Test exception" in data["exception"]

        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)

    def test_json_logging_field_filtering(self):
        """Test JSON logging with field filtering."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            logger = (
                create_json_logger("filter.test")
                .with_json_file(log_file)
                .with_json_fields(
                    include=["timestamp", "level", "message"],
                    exclude=None,
                )
                .json_only()
                .build()
            )

            logger.info("Filtered message")

            with open(log_file) as f:
                content = f.read().strip()
                data = json.loads(content)

            # Only included fields should be present
            assert "timestamp" in data
            assert "level" in data
            assert "message" in data
            # Others should be excluded
            assert "module" not in data
            assert "function" not in data

        finally:
            if os.path.exists(log_file):
                os.unlink(log_file)
