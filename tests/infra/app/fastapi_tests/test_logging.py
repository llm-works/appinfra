"""Tests for subprocess logging setup."""

import logging
from pathlib import Path

import pytest

from appinfra.app.fastapi.runtime.logging import setup_subprocess_logging


@pytest.mark.unit
class TestSetupSubprocessLogging:
    """Tests for setup_subprocess_logging function."""

    def test_returns_logger_with_log_file(self, temp_dir: Path):
        """Test that function returns a logger."""
        log_file = temp_dir / "test.log"

        # Save and restore state
        original_level = logging.root.level
        original_handlers = logging.root.handlers[:]

        try:
            logger = setup_subprocess_logging(
                str(log_file), log_level="INFO", redirect_stdio=False
            )

            assert logger is not None
            assert logger.name == "fastapi.subprocess"
        finally:
            # Restore
            logging.root.handlers = original_handlers
            logging.root.level = original_level

    def test_returns_logger_without_log_file(self):
        """Test that function returns logger even without log file."""
        logger = setup_subprocess_logging(None, log_level="WARNING")

        assert logger is not None
        assert logger.name == "fastapi.subprocess"

    def test_creates_log_file_directory(self, temp_dir: Path):
        """Test that function creates parent directories."""
        log_file = temp_dir / "subdir" / "test.log"

        original_level = logging.root.level
        original_handlers = logging.root.handlers[:]

        try:
            setup_subprocess_logging(
                str(log_file), log_level="INFO", redirect_stdio=False
            )

            assert log_file.parent.exists()
        finally:
            logging.root.handlers = original_handlers
            logging.root.level = original_level
