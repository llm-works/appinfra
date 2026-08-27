# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Utility functions for common operations.

This module provides simple utility functions for formatting and type checking.
"""

from typing import Any


def pretty(val: Any) -> Any:
    """
    Format a value for pretty printing.

    Args:
        val: Value to format

    Returns:
        Formatted value: Integer values are formatted with commas, others returned as-is
    """
    if isinstance(val, int):
        return f"{val:,}"
    return val


def is_int(n: Any) -> bool:
    """
    Check if a value can be converted to an integer.

    Args:
        n: Value to check

    Returns:
        bool: True if the value can be converted to an integer
    """
    try:
        int(n)
        return True
    except (ValueError, TypeError, OverflowError):
        pass
    return False
