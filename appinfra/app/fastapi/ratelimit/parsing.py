# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Rate string parsing.

Parses human-readable rate strings like "60/min" or "1000/hour" into
(count, window_seconds) tuples.
"""

# Map of unit suffixes to seconds
_UNITS: dict[str, float] = {
    "s": 1.0,
    "sec": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "m": 60.0,
    "min": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "d": 86400.0,
    "day": 86400.0,
    "days": 86400.0,
}


def parse_rate(rate: str) -> tuple[int, float]:
    """Parse a rate string into (count, window_seconds).

    Args:
        rate: Rate string in format "count/unit" (e.g., "60/min", "1000/hour", "10/s").

    Returns:
        Tuple of (max_requests, window_in_seconds).

    Raises:
        ValueError: If the rate string is malformed.

    Examples:
        >>> parse_rate("60/min")
        (60, 60.0)
        >>> parse_rate("1000/hour")
        (1000, 3600.0)
        >>> parse_rate("10/s")
        (10, 1.0)
    """
    parts = rate.strip().split("/")
    if len(parts) != 2:
        raise ValueError(f"Rate must be in 'count/unit' format, got: {rate!r}")

    count_str, unit = parts[0].strip(), parts[1].strip().lower()

    try:
        count = int(count_str)
    except ValueError:
        raise ValueError(f"Rate count must be an integer, got: {count_str!r}") from None

    if count <= 0:
        raise ValueError(f"Rate count must be positive, got: {count}")

    if unit not in _UNITS:
        raise ValueError(
            f"Unknown rate unit: {unit!r}. "
            f"Valid units: {', '.join(sorted(_UNITS.keys()))}"
        )

    return count, _UNITS[unit]
