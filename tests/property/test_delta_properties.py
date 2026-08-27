# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Property-based tests for duration parsing and formatting."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from appinfra.time.delta import InvalidDurationError, delta_str, delta_to_secs


@pytest.mark.property
@pytest.mark.unit
class TestDeltaProperties:
    """Property-based tests for delta.py functions."""

    @given(
        value=st.integers(min_value=1, max_value=999),
        unit=st.sampled_from(["s", "m", "h", "d"]),  # Note: 'w' not supported by parser
    )
    def test_simple_duration_parses_correctly(self, value: int, unit: str) -> None:
        """Single-unit duration strings should parse to positive values."""
        duration_str = f"{value}{unit}"
        result = delta_to_secs(duration_str)
        assert result > 0
        assert isinstance(result, float)

    @given(
        hours=st.integers(min_value=0, max_value=23),
        minutes=st.integers(min_value=0, max_value=59),
        seconds=st.integers(min_value=0, max_value=59),
    )
    def test_compound_duration_parses_correctly(
        self, hours: int, minutes: int, seconds: int
    ) -> None:
        """Compound duration strings should parse correctly."""
        # Build duration string, skipping zero components
        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if seconds > 0:
            parts.append(f"{seconds}s")

        if not parts:
            return  # Skip all-zero case

        duration_str = "".join(parts)
        result = delta_to_secs(duration_str)
        expected = hours * 3600 + minutes * 60 + seconds
        assert result == expected

    @given(text=st.text(max_size=100))
    @settings(max_examples=100)
    def test_arbitrary_input_doesnt_crash(self, text: str) -> None:
        """Any input should either parse successfully or raise InvalidDurationError."""
        try:
            result = delta_to_secs(text)
            # If it parsed, result should be non-negative
            assert result >= 0
        except InvalidDurationError:
            pass  # Expected for invalid input

    @given(secs=st.floats(min_value=0, max_value=86400 * 365, allow_nan=False))
    @settings(max_examples=50)
    def test_format_doesnt_crash(self, secs: float) -> None:
        """Formatting any valid duration should not crash."""
        result = delta_str(secs)
        assert isinstance(result, str)
        assert len(result) > 0

    @given(secs=st.floats(min_value=1, max_value=86400, allow_nan=False))
    @settings(max_examples=50)
    def test_format_parse_roundtrip_approximate(self, secs: float) -> None:
        """Format then parse should give approximately the same value."""
        formatted = delta_str(secs)
        parsed = delta_to_secs(formatted)
        # Allow some loss due to formatting (seconds are truncated)
        assert abs(parsed - secs) < secs * 0.1 + 1  # Within 10% or 1 second
