# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Duration formatting utilities.

Simple, focused module for converting durations to/from human-readable strings.

Example Usage:
    # Format duration
    >>> delta_str(3661.5)
    '1h1m1s'

    >>> delta_str(0.000001, precise=True)
    '1μs'

    # Parse duration string back to seconds
    >>> delta_to_secs('1h30m')
    5400.0

    >>> delta_to_secs('2d12h30m45s')
    219045.0
"""

import math
import re

# Time conversion constants
SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60
MILLISECONDS_PER_SECOND = 1000
MICROSECONDS_PER_SECOND = 1_000_000


class InvalidDurationError(Exception):
    """Raised when an invalid duration value or string is provided."""

    pass


def _validate_duration_input(secs: float | None) -> None:
    """
    Validate duration input for formatting.

    Raises:
        InvalidDurationError: If input is invalid
    """
    if not isinstance(secs, (int, float)):
        raise InvalidDurationError(
            f"Duration must be a number, got {type(secs).__name__}"
        )
    if math.isnan(secs):
        raise InvalidDurationError("Duration cannot be NaN")
    if math.isinf(secs):
        raise InvalidDurationError("Duration cannot be infinite")
    if secs < 0:
        raise InvalidDurationError(f"Duration cannot be negative, got {secs}")


def _handle_special_cases(secs: float, precise: bool) -> str | None:
    """
    Handle special duration cases (zero, very small values).

    Returns:
        Formatted string if special case applies, None otherwise
    """
    if secs == 0:
        return "0s"

    # For values < 1ms, show microseconds even for precise=False (more informative than "0ms")
    if secs < 0.001 and secs > 0:
        micros_val = int(secs * MICROSECONDS_PER_SECOND)
        return f"{micros_val}μs"

    return None


def _extract_time_components(secs: float) -> tuple[int, int, int, int, float]:
    """
    Extract time components from total seconds.

    Returns:
        Tuple of (days, hours, minutes, integer_seconds, fractional_seconds)
    """
    remaining = secs

    days = int(remaining / SECONDS_PER_DAY)
    remaining -= days * SECONDS_PER_DAY

    hours = int(remaining / SECONDS_PER_HOUR)
    remaining -= hours * SECONDS_PER_HOUR

    minutes = int(remaining / SECONDS_PER_MINUTE)
    remaining -= minutes * SECONDS_PER_MINUTE

    isecs = int(remaining)
    fractional = remaining - isecs

    return days, hours, minutes, isecs, fractional


def _format_fractional_with_micros(fractional: float, precise: bool) -> tuple[int, int]:
    """
    Calculate millisecond and microsecond parts from fractional seconds.

    Returns:
        Tuple of (msecs_part, usecs_part)
    """
    if not (fractional > 0 and precise):
        msecs = round(fractional * MILLISECONDS_PER_SECOND)
        return msecs, 0

    total_micros = round(fractional * MICROSECONDS_PER_SECOND)
    msecs_part = total_micros // 1000
    usecs_part = total_micros % 1000
    return msecs_part, usecs_part


def _format_only_fractional(fractional: float, precise: bool) -> str:
    """Format fractional seconds when no integer seconds present."""
    if precise and fractional < 0.001:
        micros_val = int(fractional * MICROSECONDS_PER_SECOND)
        return f"{micros_val}μs"

    msecs_part, usecs_part = _format_fractional_with_micros(fractional, precise)

    if precise:
        return f"{msecs_part}.{usecs_part:03d}ms"
    else:
        # For precise=False: if ms < 10, show fractional; if ms >= 10, show integer
        msecs = fractional * MILLISECONDS_PER_SECOND
        if msecs < 10:
            # Show fractional milliseconds, strip trailing zeros
            msec_str = f"{msecs:.3f}".rstrip("0").rstrip(".")
            return f"{msec_str}ms"
        else:
            # Show integer milliseconds, but convert to seconds if >= 1000ms
            rounded_ms = round(msecs)
            if rounded_ms >= 1000:
                # >= 1000ms becomes 1 second (no fractional part)
                return "1s"
            return f"{rounded_ms}ms"


def _format_precise_seconds(
    isecs: int, fractional: float, has_higher_unit: bool
) -> str:
    """Format seconds with full precision (microseconds)."""
    total_micros = round(fractional * MICROSECONDS_PER_SECOND)
    msecs_part = total_micros // 1000
    usecs_part = total_micros % 1000
    # Zero-pad integer seconds when higher units present
    if has_higher_unit:
        return f"{isecs:02d}.{msecs_part:03d},{usecs_part:03d}s"
    return f"{isecs}.{msecs_part:03d},{usecs_part:03d}s"


def _format_standard_seconds(isecs: int, msecs: int, precise: bool) -> str:
    """Format seconds with millisecond precision."""
    if precise:
        return f"{isecs}.{msecs:03d}s"
    elif isecs < 10:
        # Show fractional for seconds < 10 (always 3 decimal places)
        return f"{isecs}.{msecs:03d}s"
    else:
        # Hide fractional for seconds >= 10
        return f"{isecs}s"


def _format_seconds_with_fractional(
    isecs: int, fractional: float, precise: bool, has_higher_unit: bool
) -> str:
    """Format seconds with fractional part."""
    # For precise=False with higher units, drop fractional seconds
    if not precise and has_higher_unit:
        return f"{isecs}s"

    msecs = round(fractional * MILLISECONDS_PER_SECOND)

    # Handle case where fractional rounds to 1000ms (should become next second)
    if msecs >= 1000:
        return f"{isecs + 1}s"

    if fractional > 0 and precise:
        return _format_precise_seconds(isecs, fractional, has_higher_unit)
    elif msecs > 0:
        return _format_standard_seconds(isecs, msecs, precise)
    else:
        return f"{isecs}s"


def _format_seconds_component(
    isecs: int, fractional: float, precise: bool, has_higher_unit: bool
) -> str:
    """
    Format seconds component with optional fractional part.

    Args:
        isecs: Integer seconds
        fractional: Fractional part of seconds
        precise: Whether to show full precision
        has_higher_unit: Whether higher time units are present

    Returns:
        Formatted seconds string (e.g., "5s", "1.500s", "1.123,456s")
    """
    # For precise=False with higher units, always show seconds (even if 0)
    if not precise and has_higher_unit and isecs == 0 and fractional == 0:
        return "0s"

    # Only fractional part (< 1 second) - but not if there are higher units
    if isecs == 0 and not has_higher_unit:
        return _format_only_fractional(fractional, precise)

    # Format seconds with optional fractional part
    return _format_seconds_with_fractional(isecs, fractional, precise, has_higher_unit)


def _format_components_precise(
    days: int, hours: int, minutes: int, isecs: int, fractional: float
) -> str:
    """Format duration components with precise mode (zero-padding, full precision)."""
    result = ""
    has_higher_unit = False

    # Days (never zero-padded, first unit)
    if days > 0:
        result = f"{days}d"
        has_higher_unit = True

    # Hours (zero-padded if we have days)
    if hours > 0 or (has_higher_unit and result):
        result += f"{hours:02d}h" if result else f"{hours}h"
        has_higher_unit = True

    # Minutes (zero-padded if we have hours/days)
    if minutes > 0 or (has_higher_unit and result):
        if result:
            result += f"{minutes:02d}m"
        elif minutes > 0:
            result = f"{minutes}m"

    # Seconds (with fractional part)
    seconds_str = _format_seconds_component(
        isecs, fractional, precise=True, has_higher_unit=bool(result)
    )
    result += seconds_str
    return result


def _format_components_standard(
    days: int, hours: int, minutes: int, isecs: int, fractional: float
) -> str:
    """Format duration components with standard mode (no zero-padding)."""
    result = ""
    has_higher_unit = False

    # Days
    if days > 0:
        result = f"{days}d"
        has_higher_unit = True

    # Hours
    if hours > 0 or has_higher_unit:
        result += f"{hours}h"
        has_higher_unit = True

    # Minutes
    if minutes > 0 or has_higher_unit:
        result += f"{minutes}m"
        has_higher_unit = True

    # Seconds
    seconds_str = _format_seconds_component(
        isecs, fractional, precise=False, has_higher_unit=has_higher_unit
    )
    result += seconds_str
    return result


def _format_duration_components(
    days: int, hours: int, minutes: int, isecs: int, fractional: float, precise: bool
) -> str:
    """
    Format all time components into a human-readable duration string.

    For precise=False: Always show seconds when minutes/hours/days present, no zero-padding.
    For precise=True: Show full precision (legacy behavior with zero-padding).
    """
    if precise:
        result = _format_components_precise(days, hours, minutes, isecs, fractional)
    else:
        result = _format_components_standard(days, hours, minutes, isecs, fractional)

    return result if result else "0s"


def delta_str(secs: float | None, precise: bool = False) -> str:
    """
    Format a duration in seconds as a compact human-readable string.

    Args:
        secs: Duration in seconds (can be None)
        precise: Whether to show full precision (microseconds, zero-padding)

    Returns:
        Formatted duration string, or empty string if secs is None

    Raises:
        InvalidDurationError: If secs is negative, NaN, or infinite

    Format rules for precise=False (default):
        - Durations ≥60s: Always show seconds, no fractional, no zero-padding
          Examples: 60s → "1m0s", 70.123s → "1m10s", 3665s → "1h1m5s"
        - Seconds < 10: Show 3 decimal places ONLY if non-zero fractional
          Examples: 1s → "1s", 1.001s → "1.001s", 9.123s → "9.123s"
        - Seconds ≥ 10: No fractional (rounded to nearest second)
          Examples: 10s → "10s", 10.5s → "10s", 59.9s → "59s"
        - Milliseconds: Fractional if <10ms, integer if ≥10ms
          Examples: 9.123ms → "9.123ms", 10ms → "10ms"
        - Microseconds: Always show
          Example: 123μs → "123μs"

    Format rules for precise=True:
        - Full precision with microseconds and zero-padding
          Examples: 70.123456s → "1m10.123,456s", 60s → "1m00s"

    Examples:
        >>> delta_str(3661.5)
        '1h1m1s'
        >>> delta_str(60)
        '1m0s'
        >>> delta_str(1.0)
        '1s'
        >>> delta_str(1.001)
        '1.001s'
        >>> delta_str(9.123)
        '9.123s'
        >>> delta_str(10.5)
        '10s'
        >>> delta_str(0.001)
        '1ms'
        >>> delta_str(0.009123)
        '9.123ms'
        >>> delta_str(0.000001, precise=True)
        '1μs'
        >>> delta_str(0)
        '0s'
    """
    if secs is None:
        return ""

    # Validate input
    _validate_duration_input(secs)

    # Handle special cases
    special_result = _handle_special_cases(secs, precise)
    if special_result is not None:
        return special_result

    # Extract time components
    days, hours, minutes, isecs, fractional = _extract_time_components(secs)

    # Format components into string
    return _format_duration_components(days, hours, minutes, isecs, fractional, precise)


def _convert_unit_to_seconds(value_str: str, unit: str, seen_units: set) -> float:
    """
    Convert a duration value with unit to seconds.

    Args:
        value_str: String representation of the value (may contain comma)
        unit: Time unit (d, h, m, s, ms, μs)
        seen_units: Set to track duplicate units

    Returns:
        Value in seconds

    Raises:
        InvalidDurationError: If unit is duplicated
    """
    # Handle comma separator for microsecond precision
    value_str = value_str.replace(",", "")
    value = float(value_str)

    # Check for duplicate units
    if unit in seen_units:
        raise InvalidDurationError(f"Duplicate unit '{unit}' in duration string")
    seen_units.add(unit)

    # Convert to seconds
    if unit == "d":
        return value * SECONDS_PER_DAY
    elif unit == "h":
        return value * SECONDS_PER_HOUR
    elif unit == "m":
        return value * SECONDS_PER_MINUTE
    elif unit == "s":
        return value
    elif unit == "ms":
        return value / MILLISECONDS_PER_SECOND
    elif unit == "μs":
        return value / MICROSECONDS_PER_SECOND
    return 0.0


def _validate_duration_string(duration_str: str) -> str:
    """Validate and normalize duration string input."""
    if not duration_str or not isinstance(duration_str, str):
        raise InvalidDurationError("Duration string cannot be empty")

    duration_str = duration_str.strip()
    if not duration_str:
        raise InvalidDurationError("Duration string cannot be empty")

    return duration_str


def _validate_parsed_matches(matches: list[tuple[str, str]], duration_str: str) -> None:
    """Validate that regex matches consumed the entire input string."""
    reconstructed = "".join(f"{val}{unit}" for val, unit in matches)
    if reconstructed != duration_str.replace(" ", ""):
        raise InvalidDurationError(
            f"Invalid characters in duration string: '{duration_str}'"
        )


def delta_to_secs(duration_str: str) -> float:
    """
    Parse a duration string back to seconds.

    Supports formats produced by delta_str():
    - "1h30m" → 5400.0
    - "45.5s" → 45.5
    - "2d12h30m45s" → 219045.0
    - "1ms" → 0.001
    - "5μs" → 0.000005

    Args:
        duration_str: Duration string to parse

    Returns:
        Duration in seconds as float

    Raises:
        InvalidDurationError: If the string cannot be parsed

    Examples:
        >>> delta_to_secs('1h30m')
        5400.0
        >>> delta_to_secs('45.5s')
        45.5
        >>> delta_to_secs('2d12h30m45.500s')
        219045.5
    """
    duration_str = _validate_duration_string(duration_str)

    # Pattern to match time components: number followed by unit
    # Supports: d, h, m, s (with decimals and comma separator for μs), ms, μs
    # IMPORTANT: Match longer units first (ms, μs before m, s)
    # Format with comma: "1.123,456s" = 1.123456 seconds
    pattern = r"(\d+(?:\.\d+)?(?:,\d+)?)(ms|μs|d|h|m|s)"
    matches = re.findall(pattern, duration_str)

    if not matches:
        raise InvalidDurationError(f"Could not parse duration string: '{duration_str}'")

    _validate_parsed_matches(matches, duration_str)

    # Convert all matched units to seconds
    total_seconds = 0.0
    seen_units: set[str] = set()
    for value_str, unit in matches:
        total_seconds += _convert_unit_to_seconds(value_str, unit, seen_units)

    return total_seconds


def validate_duration(secs: int | float) -> bool:
    """
    Validate that a duration value is reasonable.

    Args:
        secs: Duration in seconds

    Returns:
        True if valid, False otherwise

    Examples:
        >>> validate_duration(60)
        True
        >>> validate_duration(-5)
        False
        >>> validate_duration(float('inf'))
        False
    """
    if not isinstance(secs, (int, float)):
        return False

    if math.isnan(secs) or math.isinf(secs):
        return False

    if secs < 0:
        return False

    # Check for unreasonably large values (more than 1000 years)
    if secs > 365.25 * 24 * 3600 * 1000:
        return False

    return True


# Public API
__all__ = [
    "delta_str",
    "delta_to_secs",
    "validate_duration",
    "InvalidDurationError",
]
