# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Custom assertions and validation helpers for tests.

Provides specialized assertion functions that make tests more readable
and provide better error messages.
"""

import re
from collections.abc import Callable
from typing import Any


def assert_raises_with_message(
    exception_class: type[Exception],
    message_pattern: str,
    callable_func: Callable,
    *args,
    **kwargs,
) -> None:
    """
    Assert that a function raises an exception with a message matching a pattern.

    Args:
        exception_class: Expected exception type
        message_pattern: Regex pattern for exception message
        callable_func: Function to call
        *args: Positional arguments for callable_func
        **kwargs: Keyword arguments for callable_func

    Raises:
        AssertionError: If exception not raised or message doesn't match
    """
    try:
        callable_func(*args, **kwargs)
        raise AssertionError(
            f"Expected {exception_class.__name__} to be raised, but no exception was raised"
        )
    except exception_class as e:
        if not re.search(message_pattern, str(e)):
            raise AssertionError(
                f"Exception message '{str(e)}' does not match pattern '{message_pattern}'"
            )
    except Exception as e:
        raise AssertionError(
            f"Expected {exception_class.__name__}, but got {type(e).__name__}: {e}"
        )


def assert_dict_contains(actual: dict, expected_subset: dict) -> None:
    """
    Assert that a dictionary contains all key-value pairs from expected_subset.

    Args:
        actual: Dictionary to check
        expected_subset: Expected key-value pairs

    Raises:
        AssertionError: If expected key-value pairs not found
    """
    for key, expected_value in expected_subset.items():
        if key not in actual:
            raise AssertionError(f"Key '{key}' not found in actual dict")

        actual_value = actual[key]

        if isinstance(expected_value, dict) and isinstance(actual_value, dict):
            # Recursively check nested dicts
            assert_dict_contains(actual_value, expected_value)
        elif actual_value != expected_value:
            raise AssertionError(
                f"Value for key '{key}': expected {expected_value!r}, got {actual_value!r}"
            )


def assert_almost_equal_time(
    actual: float, expected: float, tolerance_seconds: float = 0.1
) -> None:
    """
    Assert that two time values (in seconds) are approximately equal.

    Args:
        actual: Actual time value
        expected: Expected time value
        tolerance_seconds: Allowed difference in seconds

    Raises:
        AssertionError: If values differ by more than tolerance
    """
    diff = abs(actual - expected)
    if diff > tolerance_seconds:
        raise AssertionError(
            f"Time values differ by {diff:.6f}s (tolerance: {tolerance_seconds}s): "
            f"expected {expected:.6f}, got {actual:.6f}"
        )


def assert_valid_duration_string(duration_str: str) -> None:
    """
    Assert that a string is a valid duration format.

    Args:
        duration_str: Duration string to validate

    Raises:
        AssertionError: If string is not a valid duration
    """
    # Pattern for duration: Xd Xh Xm X.XXXs Xms Xμs
    pattern = r"^(\d+d)?(\d+h)?(\d+m)?(\d+(\.\d+)?s)?(\d+ms)?(\d+μs)?$"
    if not re.match(pattern, duration_str.replace(" ", "")):
        raise AssertionError(f"Invalid duration string: '{duration_str}'")


def assert_type_and_value(
    actual: Any, expected_type: type, expected_value: Any
) -> None:
    """
    Assert both type and value of an object.

    Args:
        actual: Value to check
        expected_type: Expected type
        expected_value: Expected value

    Raises:
        AssertionError: If type or value doesn't match
    """
    if not isinstance(actual, expected_type):
        raise AssertionError(
            f"Expected type {expected_type.__name__}, got {type(actual).__name__}"
        )

    if actual != expected_value:
        raise AssertionError(f"Expected value {expected_value!r}, got {actual!r}")
