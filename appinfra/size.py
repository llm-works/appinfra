# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Size formatting utilities.

Simple, focused module for converting byte sizes to/from human-readable strings.

Example Usage:
    # Format size
    >>> size_str(1024)
    '1KB'

    >>> size_str(1536)
    '1.5KB'

    >>> size_str(1048576)
    '1MB'

    # Parse size string back to bytes
    >>> size_to_bytes('1.5MB')
    1572864

    >>> size_to_bytes('500B')
    500
"""

import math
import re

# Size conversion constants (binary, 1024-based)
BYTES_PER_KB = 1024
BYTES_PER_MB = 1024**2
BYTES_PER_GB = 1024**3
BYTES_PER_TB = 1024**4
BYTES_PER_PB = 1024**5

# SI conversion constants (1000-based)
BYTES_PER_KB_SI = 1000
BYTES_PER_MB_SI = 1000**2
BYTES_PER_GB_SI = 1000**3
BYTES_PER_TB_SI = 1000**4
BYTES_PER_PB_SI = 1000**5

# Unit thresholds and labels (binary)
_BINARY_UNITS = [
    (BYTES_PER_PB, "PB"),
    (BYTES_PER_TB, "TB"),
    (BYTES_PER_GB, "GB"),
    (BYTES_PER_MB, "MB"),
    (BYTES_PER_KB, "KB"),
    (1, "B"),
]

# Unit thresholds and labels (SI)
_SI_UNITS = [
    (BYTES_PER_PB_SI, "PB"),
    (BYTES_PER_TB_SI, "TB"),
    (BYTES_PER_GB_SI, "GB"),
    (BYTES_PER_MB_SI, "MB"),
    (BYTES_PER_KB_SI, "KB"),
    (1, "B"),
]


class InvalidSizeError(Exception):
    """Raised when an invalid size value or string is provided."""

    pass


def _validate_size_input(size: float | int | None) -> None:
    """
    Validate size input for formatting.

    Raises:
        InvalidSizeError: If input is invalid
    """
    if not isinstance(size, (int, float)):
        raise InvalidSizeError(f"Size must be a number, got {type(size).__name__}")
    if math.isnan(size):
        raise InvalidSizeError("Size cannot be NaN")
    if math.isinf(size):
        raise InvalidSizeError("Size cannot be infinite")
    if size < 0:
        raise InvalidSizeError(f"Size cannot be negative, got {size}")


def _format_value(value: float, precise: bool) -> str:
    """
    Format the numeric value with appropriate precision.

    Args:
        value: The numeric value to format
        precise: Whether to show fixed 3 decimal places

    Returns:
        Formatted string representation
    """
    if precise:
        return f"{value:.3f}"

    # For non-precise: show decimals only if needed, strip trailing zeros
    if value == int(value):
        return str(int(value))

    # Show up to 1 decimal place, strip trailing zeros
    formatted = f"{value:.1f}".rstrip("0").rstrip(".")
    return formatted


def size_str(
    size: float | int | None, precise: bool = False, binary: bool = True
) -> str:
    """
    Format a size in bytes as a compact human-readable string.

    Args:
        size: Size in bytes (can be None)
        precise: Whether to show fixed 3 decimal places (default: False)
        binary: Whether to use binary (1024) or SI (1000) units (default: True)

    Returns:
        Formatted size string, or empty string if size is None

    Raises:
        InvalidSizeError: If size is negative, NaN, or infinite

    Examples:
        >>> size_str(0)
        '0B'
        >>> size_str(500)
        '500B'
        >>> size_str(1024)
        '1KB'
        >>> size_str(1536)
        '1.5KB'
        >>> size_str(1048576)
        '1MB'
        >>> size_str(1536, precise=True)
        '1.500KB'
        >>> size_str(1500, binary=False)
        '1.5KB'
    """
    if size is None:
        return ""

    _validate_size_input(size)

    if size == 0:
        return "0B"

    units = _BINARY_UNITS if binary else _SI_UNITS

    for threshold, suffix in units:
        if size >= threshold:
            value = size / threshold
            return f"{_format_value(value, precise)}{suffix}"

    # Fallback (shouldn't reach here)
    return f"{int(size)}B"


def _parse_unit_to_bytes(value: float, unit: str) -> int:
    """
    Convert a size value with unit to bytes.

    Args:
        value: Numeric value
        unit: Size unit (B, KB, MB, GB, TB, PB)

    Returns:
        Size in bytes

    Raises:
        InvalidSizeError: If unit is unknown
    """
    unit_upper = unit.upper()

    # Map units to multipliers (support both binary and SI parsing)
    # When parsing, assume binary (1024) since that's the common convention for bytes
    unit_map = {
        "B": 1,
        "KB": BYTES_PER_KB,
        "MB": BYTES_PER_MB,
        "GB": BYTES_PER_GB,
        "TB": BYTES_PER_TB,
        "PB": BYTES_PER_PB,
        # Also support IEC suffixes
        "KIB": BYTES_PER_KB,
        "MIB": BYTES_PER_MB,
        "GIB": BYTES_PER_GB,
        "TIB": BYTES_PER_TB,
        "PIB": BYTES_PER_PB,
    }

    if unit_upper not in unit_map:
        raise InvalidSizeError(f"Unknown size unit: '{unit}'")

    return int(value * unit_map[unit_upper])


def size_to_bytes(size_str_input: str) -> int:
    """
    Parse a size string back to bytes.

    Supports formats produced by size_str():
    - "1KB" -> 1024
    - "1.5MB" -> 1572864
    - "500B" -> 500

    Args:
        size_str_input: Size string to parse

    Returns:
        Size in bytes as integer

    Raises:
        InvalidSizeError: If the string cannot be parsed

    Examples:
        >>> size_to_bytes('1KB')
        1024
        >>> size_to_bytes('1.5MB')
        1572864
        >>> size_to_bytes('500B')
        500
    """
    if not size_str_input or not isinstance(size_str_input, str):
        raise InvalidSizeError("Size string cannot be empty")

    size_str_input = size_str_input.strip()
    if not size_str_input:
        raise InvalidSizeError("Size string cannot be empty")

    # Pattern to match: number (with optional decimals) followed by unit
    pattern = r"^(\d+(?:\.\d+)?)\s*(PIB|TIB|GIB|MIB|KIB|PB|TB|GB|MB|KB|B)$"
    match = re.match(pattern, size_str_input, re.IGNORECASE)

    if not match:
        raise InvalidSizeError(f"Could not parse size string: '{size_str_input}'")

    value = float(match.group(1))
    unit = match.group(2)

    return _parse_unit_to_bytes(value, unit)


def validate_size(size: int | float) -> bool:
    """
    Validate that a size value is reasonable.

    Args:
        size: Size in bytes

    Returns:
        True if valid, False otherwise

    Examples:
        >>> validate_size(1024)
        True
        >>> validate_size(-5)
        False
        >>> validate_size(float('inf'))
        False
    """
    if not isinstance(size, (int, float)):
        return False

    if math.isnan(size) or math.isinf(size):
        return False

    if size < 0:
        return False

    # Check for unreasonably large values (more than 1 exabyte)
    if size > 1024**6:
        return False

    return True


# Public API
__all__ = [
    "size_str",
    "size_to_bytes",
    "validate_size",
    "InvalidSizeError",
]
