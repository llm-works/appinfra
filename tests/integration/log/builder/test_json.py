# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for JSON logging that write log files and read them back.
"""

import json
import os
import tempfile

from appinfra.log.builder.json import create_json_logger


class TestJSONLoggingIntegration:
    """Integration tests for JSON logging."""

    def test_full_json_logging_workflow(self):
        """Test complete JSON logging workflow."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            log_file = f.name

        try:
            # A name no other test builds: build() on an existing name keeps its old level.
            logger = (
                create_json_logger("integration.json")
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
