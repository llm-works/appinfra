# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Security-specific assertion helpers for tests."""

import re
import time
from collections.abc import Callable
from pathlib import Path
from re import Pattern
from typing import Any


def assert_no_path_escape(resolved_path: Path, project_root: Path) -> None:
    """
    Assert that resolved path stays within project root boundary.

    Args:
        resolved_path: The path that was resolved
        project_root: The project root that should contain the path

    Raises:
        AssertionError: If resolved_path escapes project_root
    """
    try:
        resolved_path.resolve().relative_to(project_root.resolve())
    except ValueError as e:
        raise AssertionError(
            f"Path {resolved_path} escapes project root {project_root}"
        ) from e


def assert_timeout_enforced(
    func: Callable,
    timeout_sec: float,
    tolerance_sec: float = 0.5,
    *args: Any,
    **kwargs: Any,
) -> None:
    """
    Assert that function times out within specified window.

    Args:
        func: Function to test
        timeout_sec: Expected timeout in seconds
        tolerance_sec: Acceptable tolerance in seconds
        *args: Arguments to pass to func
        **kwargs: Keyword arguments to pass to func

    Raises:
        AssertionError: If function doesn't timeout or times out outside tolerance
    """
    start_time = time.time()

    try:
        func(*args, **kwargs)
        elapsed = time.time() - start_time
        raise AssertionError(
            f"Function did not timeout (ran for {elapsed:.2f}s, expected {timeout_sec}s)"
        )
    except TimeoutError:
        elapsed = time.time() - start_time
        min_time = timeout_sec - tolerance_sec
        max_time = timeout_sec + tolerance_sec

        if not (min_time <= elapsed <= max_time):
            raise AssertionError(
                f"Timeout occurred at {elapsed:.2f}s, expected {timeout_sec}±{tolerance_sec}s"
            )


def assert_no_credential_in_string(text: str) -> None:
    """
    Assert that string doesn't contain credentials or secrets.

    Checks for common patterns like password=, token=, secret=, etc.

    Args:
        text: String to check for credentials

    Raises:
        AssertionError: If credentials found in text
    """
    # Patterns that indicate credentials
    credential_patterns = [
        r"password\s*[=:]\s*['\"]?[\w\-\._]+",
        r"passwd\s*[=:]\s*['\"]?[\w\-\._]+",
        r"secret\s*[=:]\s*['\"]?[\w\-\._]+",
        r"token\s*[=:]\s*['\"]?[\w\-\._]+",
        r"api[_\-]?key\s*[=:]\s*['\"]?[\w\-\._]+",
        r"auth[_\-]?token\s*[=:]\s*['\"]?[\w\-\._]+",
        r"private[_\-]?key\s*[=:]\s*['\"]?[\w\-\._]+",
    ]

    for pattern in credential_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Mask the actual credential value in error message
            masked_match = re.sub(r"['\"]?[\w\-\._]+$", "***REDACTED***", match.group())
            raise AssertionError(
                f"Potential credential found in string: {masked_match}"
            )


def assert_raises_with_security_message(
    exception_class: type[Exception],
    message_pattern: str | Pattern[str],
    callable_func: Callable,
    *args: Any,
    **kwargs: Any,
) -> None:
    """
    Assert that function raises specific exception with security-related message.

    Args:
        exception_class: Expected exception class
        message_pattern: Regex pattern the exception message should match
        callable_func: Function to call
        *args: Arguments to pass to callable_func
        **kwargs: Keyword arguments to pass to callable_func

    Raises:
        AssertionError: If exception not raised or message doesn't match
    """
    try:
        callable_func(*args, **kwargs)
        raise AssertionError(
            f"Expected {exception_class.__name__} to be raised, but no exception was raised"
        )
    except exception_class as e:
        error_message = str(e)
        if isinstance(message_pattern, str):
            pattern = re.compile(message_pattern)
        else:
            pattern = message_pattern

        if not pattern.search(error_message):
            raise AssertionError(
                f"Exception message '{error_message}' doesn't match pattern '{pattern.pattern}'"
            )
    except Exception as e:
        raise AssertionError(
            f"Expected {exception_class.__name__}, but got {type(e).__name__}: {e}"
        )
