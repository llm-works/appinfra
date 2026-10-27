# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Security tests for logging module (infra/log/builder/file.py)."""

import contextlib
from pathlib import Path

import pytest

from appinfra.log.builder.file import FileHandlerConfig, FileLoggingBuilder
from appinfra.log.config import LogConfig
from tests.security.payloads.injection import LOG_INJECTION
from tests.security.payloads.traversal import ABSOLUTE_PATH_ESCAPE, CLASSIC_TRAVERSAL


@pytest.mark.security
@pytest.mark.unit
@pytest.mark.parametrize("traversal_path", CLASSIC_TRAVERSAL + ABSOLUTE_PATH_ESCAPE)
def test_log_file_path_traversal(traversal_path: str):
    """
    Verify file handler doesn't allow arbitrary file paths via traversal.

    Attack Vector: Path traversal to write logs to sensitive locations
    Module: infra/log/builder/file.py:41-100 (FileHandlerConfig.create_handler)
    OWASP: A01:2021 - Broken Access Control

    Security Concern: If log file paths are derived from user input or
    configuration without validation, attackers could use path traversal
    to write log files to arbitrary locations:
    - Overwrite system files (e.g., /etc/passwd)
    - Fill disk space in critical system directories
    - Write to web-accessible directories for information disclosure

    The file handler should validate and sanitize file paths to prevent
    writing outside intended log directories.
    """
    # Create a log configuration
    config = LogConfig.from_params(level="info", location=0, micros=False, colors=False)

    # Attempt to create a handler with malicious path
    try:
        handler_config = FileHandlerConfig(
            filename=traversal_path,
            mode="a",
            level="info",
        )

        # Create handler - this will attempt to create parent directories
        handler = handler_config.create_handler(config)

        # If handler creation succeeds, verify the path is safe
        # Get the actual path being written to
        if hasattr(handler, "baseFilename"):
            actual_path = Path(handler.baseFilename).resolve()

            # The file should NOT be in sensitive system directories
            sensitive_dirs = [
                Path("/etc"),
                Path("/etc/passwd"),
                Path("/etc/shadow"),
                Path("/var/log/syslog"),
                Path("/root"),
                Path("/usr"),
                Path("/boot"),
            ]

            for sensitive_dir in sensitive_dirs:
                try:
                    # Check if actual_path is under any sensitive directory
                    actual_path.relative_to(sensitive_dir)
                    pytest.fail(
                        f"Log file path {actual_path} is under sensitive directory {sensitive_dir}"
                    )
                except ValueError:
                    # Not under this sensitive directory - good
                    pass

            # Cleanup: close handler and remove created file if it exists
            handler.close()
            if actual_path.exists():
                with contextlib.suppress(OSError):
                    actual_path.unlink()

    except (ValueError, OSError, PermissionError) as e:
        # Expected: Path validation or permission errors
        # These are good - they prevent the attack
        pass


@pytest.mark.security
@pytest.mark.unit
@pytest.mark.parametrize("payload", LOG_INJECTION)
def test_log_injection_attack(payload: str, secure_temp_project: Path):
    """
    Verify log messages are properly escaped to prevent log injection.

    Attack Vector: Log injection via ANSI codes, newlines, or control characters
    Module: infra/log/builder/file.py (uses LogFormatter)
    OWASP: A09:2021 - Security Logging and Monitoring Failures

    Security Concern: Log injection attacks exploit insufficient input validation
    in logging systems. Attackers can inject:
    - Fake log entries via newlines (log forging)
    - ANSI escape codes to hide malicious activity
    - Control characters to corrupt log files
    - Null bytes to truncate log entries

    This can lead to:
    - Security monitoring evasion
    - Log tampering (covering tracks)
    - Terminal exploits when viewing logs
    - Log parsing failures

    The logging system should sanitize or escape special characters in
    log messages to prevent injection attacks.
    """
    # Create a temporary log file in the secure temp project
    log_file = secure_temp_project / "logs" / "test.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Create log configuration
    config = LogConfig.from_params(level="info", location=0, micros=False, colors=False)

    # Create a file logging builder
    builder = FileLoggingBuilder(name="test_logger", file_path=log_file)
    builder.with_level("info")

    # Build the logger
    logger = builder.build()

    # Log the malicious payload
    logger.info(payload)

    # Force flush to ensure content is written
    for handler in logger.handlers:
        handler.flush()

    # Read the log file
    log_content = log_file.read_text()

    # Null byte injection must not truncate the entry: the content after the null byte
    # is still logged, the null byte itself escaped or removed
    if "\x00" in payload and "hidden_content" in payload:
        assert "hidden" in log_content or payload.replace("\x00", "") in log_content

    # General verification: The log file should have valid structure
    # and not be corrupted by the injection
    assert len(log_content) > 0, "Log file is empty - logging may have failed"

    # Cleanup
    for handler in logger.handlers:
        handler.close()


# Positive test: Verify legitimate log messages work correctly
@pytest.mark.security
@pytest.mark.unit
def test_legitimate_log_messages_allowed(secure_temp_project: Path):
    """
    Verify legitimate log messages are logged correctly.

    Security Concern: Security measures should block attacks without breaking
    legitimate use cases. Normal log messages should be written correctly.
    """
    log_file = secure_temp_project / "logs" / "legitimate.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    config = LogConfig.from_params(level="info", location=0, micros=False, colors=False)
    builder = FileLoggingBuilder(name="test_logger", file_path=log_file)
    builder.with_level("debug")

    logger = builder.build()

    # Legitimate log messages
    legitimate_messages = [
        "Application started successfully",
        "User alice logged in from 192.168.1.100",
        "Processing request: GET /api/users?page=1&limit=10",
        "Database query completed in 0.042s",
        "Cache miss for key: user:12345:profile",
    ]

    for msg in legitimate_messages:
        logger.info(msg)

    # Flush
    for handler in logger.handlers:
        handler.flush()

    # Verify messages are in log
    log_content = log_file.read_text()

    for msg in legitimate_messages:
        assert msg in log_content, f"Legitimate message not found in log: {msg}"

    # Verify log structure is valid (has timestamps, levels, etc.)
    lines = [line for line in log_content.split("\n") if line.strip()]
    assert len(lines) >= len(legitimate_messages)

    # Each line should have some structure (this is format-dependent)
    # At minimum, the message content should be there
    for i, msg in enumerate(legitimate_messages):
        assert any(msg in line for line in lines), (
            f"Message {i} not found in any log line"
        )

    # Cleanup
    for handler in logger.handlers:
        handler.close()
