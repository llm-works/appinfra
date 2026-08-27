# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Deprecation utilities for marking deprecated APIs.

This module provides decorators for marking functions and methods as deprecated,
emitting warnings when they are used.

Example:
    from .deprecation import deprecated

    @deprecated(version="0.2.0", replacement="new_function")
    def old_function():
        ...
"""

import warnings
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

F = TypeVar("F", bound=Callable[..., object])


def deprecated(version: str, replacement: str | None = None) -> Callable[[F], F]:
    """
    Mark a function or method as deprecated.

    Emits a DeprecationWarning when the decorated function is called.
    The warning message includes the version when deprecation occurred
    and optionally the replacement to use.

    Args:
        version: Version in which the function was deprecated (e.g., "0.2.0")
        replacement: Optional name of the replacement function/method

    Returns:
        Decorator function that wraps the original function

    Example:
        @deprecated(version="0.2.0", replacement="new_function")
        def old_function():
            '''This function is deprecated.'''
            return "old"

        @deprecated(version="0.2.0")
        def another_old_function():
            '''No replacement specified.'''
            return "also old"
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: object, **kwargs: object) -> object:
            msg = f"{func.__qualname__} is deprecated since version {version}"
            if replacement:
                msg += f", use {replacement} instead"
            warnings.warn(msg, DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
