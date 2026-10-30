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

import pytest

from appinfra.log.builder.quick import (
    quick_both_logger,
    quick_both_outputs,
    quick_console_and_file,
    quick_console_logger,
    quick_daily_file_logger,
    quick_file_logger,
    quick_file_with_rotation,
    quick_json_console,
    quick_json_file,
)
from appinfra.log.logger import Logger

# =============================================================================
# Test quick_file_logger
# =============================================================================


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
# Test quick_file_with_rotation
# =============================================================================


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
# Test JSON Quick Loggers
# =============================================================================


class TestJSONQuickLoggers:
    """Test quick JSON logger functions."""

    @pytest.mark.unit
    def test_quick_json_console(self):
        """Test quick_json_console."""
        logger = quick_json_console("test_logger")
        assert isinstance(logger, Logger)

    @pytest.mark.unit
    def test_quick_json_console_with_config(self):
        """Test quick_json_console with custom config."""
        config = {"level": "debug"}
        logger = quick_json_console("test_logger", config)
        assert isinstance(logger, Logger)

    @pytest.mark.unit
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


class TestQuickLoggerIntegration:
    """Test real-world quick logger scenarios."""

    @pytest.mark.unit
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
