# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Regex utilities with ReDoS (Regular Expression Denial of Service) protection.

This module provides safe regex compilation and matching with timeout mechanisms
to prevent ReDoS attacks from malicious or poorly-written regex patterns.

Key Features:
- Timeout-based regex matching to prevent catastrophic backtracking
- Pattern complexity validation
- Safe defaults for all regex operations

Security Notes:
- All user-provided regex patterns should use safe_compile()
- Internal/trusted patterns can use standard re module
- Timeouts prevent infinite loops from malicious patterns

Example Usage:
    import logging
    from .regex_utils import safe_compile, safe_match

    lg = logging.getLogger(__name__)

    # Compile user-provided pattern with timeout protection
    try:
        pattern = safe_compile(user_pattern, timeout=1.0)
        match = pattern.match(input_string)
    except TimeoutError:
        lg.error("Regex matching timed out - possible ReDoS attack")
    except ValueError as e:
        lg.error(f"Invalid regex pattern: {e}")
"""

import re
import signal
from contextlib import contextmanager
from re import Match, Pattern
from typing import Any


class RegexTimeoutError(TimeoutError):
    """Raised when regex matching exceeds timeout limit."""

    pass


class RegexComplexityError(ValueError):
    """Raised when regex pattern is too complex."""

    pass


# Maximum pattern length to prevent extremely long patterns
MAX_PATTERN_LENGTH = 1000

# Known dangerous patterns that can cause catastrophic backtracking
# These patterns look for nested quantifiers which are the primary cause of ReDoS
DANGEROUS_PATTERNS = [
    r"\([^)]*[*+]\)[*+{]",  # Nested quantifiers: (.+)+ or (.*)*
    r"\([^)]*\{[^}]+\}\)[*+{]",  # Quantified groups followed by quantifiers
]


def _validate_pattern_complexity(pattern: str) -> None:
    """
    Validate regex pattern to detect potentially dangerous constructs.

    Args:
        pattern: Regex pattern string to validate

    Raises:
        RegexComplexityError: If pattern is too complex or dangerous

    Note:
        This validation focuses on detecting nested quantifiers which are
        the primary cause of catastrophic backtracking. Simple quantifiers
        and character classes are safe and allowed.
    """
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise RegexComplexityError(
            f"Pattern too long ({len(pattern)} chars, max {MAX_PATTERN_LENGTH})"
        )

    # Check for known dangerous patterns (nested quantifiers)
    for dangerous in DANGEROUS_PATTERNS:
        if re.search(dangerous, pattern):
            raise RegexComplexityError(
                "Pattern contains nested quantifiers that may cause ReDoS. "
                "Avoid patterns like (.+)+ or (.*)* that can cause catastrophic backtracking."
            )


@contextmanager
def _timeout_context(timeout_seconds: float) -> Any:
    """
    Context manager for timing out operations (Unix-only).

    Args:
        timeout_seconds: Maximum time to allow

    Raises:
        RegexTimeoutError: If operation exceeds timeout
    """

    def timeout_handler(signum: int, frame: Any) -> None:
        raise RegexTimeoutError(f"Regex operation exceeded {timeout_seconds}s timeout")

    # Note: signal.alarm only works on Unix systems
    # On Windows, this is a no-op and timeout protection is disabled
    try:
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(int(timeout_seconds) if timeout_seconds >= 1 else 1)
        yield
    finally:
        signal.alarm(0)
        if old_handler:
            signal.signal(signal.SIGALRM, old_handler)


def safe_compile(pattern: str, flags: int = 0, timeout: float | None = 1.0) -> Pattern:
    """
    Safely compile a regex pattern with complexity validation.

    This function validates the pattern for known ReDoS vulnerabilities
    before compilation. Use this for all user-provided regex patterns.

    Args:
        pattern: Regex pattern string to compile
        flags: Regex flags (re.IGNORECASE, etc.)
        timeout: Maximum compilation time in seconds (None to disable)

    Returns:
        Compiled regex pattern

    Raises:
        RegexComplexityError: If pattern is too complex
        RegexTimeoutError: If compilation exceeds timeout
        re.error: If pattern is invalid

    Example:
        >>> pattern = safe_compile(r"^[a-z]+$")
        >>> pattern.match("hello")
        <re.Match object; span=(0, 5), match='hello'>
    """
    # Validate pattern complexity
    _validate_pattern_complexity(pattern)

    # Compile with optional timeout protection
    if timeout is not None and hasattr(signal, "SIGALRM"):
        with _timeout_context(timeout):
            return re.compile(pattern, flags)
    else:
        # No timeout protection (Windows or timeout disabled)
        return re.compile(pattern, flags)


def safe_match(
    pattern: str | Pattern,
    string: str,
    flags: int = 0,
    timeout: float | None = 1.0,
) -> Match[str] | None:
    """
    Safely match a regex pattern with timeout protection.

    Args:
        pattern: Regex pattern (string or compiled)
        string: String to match against
        flags: Regex flags (only used if pattern is a string)
        timeout: Maximum matching time in seconds (None to disable)

    Returns:
        Match object or None

    Raises:
        RegexTimeoutError: If matching exceeds timeout

    Example:
        >>> import logging
        >>> lg = logging.getLogger(__name__)
        >>> safe_match(r"^test", "test string")
        <re.Match object; span=(0, 4), match='test'>
    """
    # Compile pattern if needed
    if isinstance(pattern, str):
        compiled = safe_compile(pattern, flags, timeout)
    else:
        compiled = pattern

    # Match with optional timeout protection
    if timeout is not None and hasattr(signal, "SIGALRM"):
        with _timeout_context(timeout):
            return compiled.match(string)
    else:
        return compiled.match(string)


def safe_search(
    pattern: str | Pattern,
    string: str,
    flags: int = 0,
    timeout: float | None = 1.0,
) -> Match[str] | None:
    """
    Safely search for a regex pattern with timeout protection.

    Args:
        pattern: Regex pattern (string or compiled)
        string: String to search
        flags: Regex flags (only used if pattern is a string)
        timeout: Maximum search time in seconds (None to disable)

    Returns:
        Match object or None

    Raises:
        RegexTimeoutError: If search exceeds timeout
    """
    # Compile pattern if needed
    if isinstance(pattern, str):
        compiled = safe_compile(pattern, flags, timeout)
    else:
        compiled = pattern

    # Search with optional timeout protection
    if timeout is not None and hasattr(signal, "SIGALRM"):
        with _timeout_context(timeout):
            return compiled.search(string)
    else:
        return compiled.search(string)


def safe_findall(
    pattern: str | Pattern,
    string: str,
    flags: int = 0,
    timeout: float | None = 1.0,
) -> list[Any]:
    """
    Safely find all matches with timeout protection.

    Args:
        pattern: Regex pattern (string or compiled)
        string: String to search
        flags: Regex flags (only used if pattern is a string)
        timeout: Maximum search time in seconds (None to disable)

    Returns:
        List of matches

    Raises:
        RegexTimeoutError: If search exceeds timeout
    """
    # Compile pattern if needed
    if isinstance(pattern, str):
        compiled = safe_compile(pattern, flags, timeout)
    else:
        compiled = pattern

    # Search with optional timeout protection
    if timeout is not None and hasattr(signal, "SIGALRM"):
        with _timeout_context(timeout):
            return compiled.findall(string)
    else:
        return compiled.findall(string)
