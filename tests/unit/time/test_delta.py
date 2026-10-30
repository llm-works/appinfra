# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for appinfra.time.delta module (duration formatting).

Comprehensive tests for duration string formatting and parsing,
including edge cases, round-trip conversion, and error handling.
"""

import pytest

from appinfra.time.delta import (
    InvalidDurationError,
    delta_str,
    delta_to_secs,
    validate_duration,
)

# =============================================================================
# delta_str() Tests - Formatting
# =============================================================================


@pytest.mark.unit
class TestDeltaStrBasic:
    """Test basic delta_str formatting."""

    def test_zero(self):
        """Test zero duration."""
        assert delta_str(0) == "0s"
        assert delta_str(0.0) == "0s"

    def test_none(self):
        """Test None input returns empty string."""
        assert delta_str(None) == ""

    def test_seconds_only(self):
        """Test formatting seconds only."""
        assert delta_str(1) == "1s"  # Whole second - no .000
        assert delta_str(5) == "5s"  # Whole second - no .000
        assert delta_str(30) == "30s"  # >= 10: no fractional
        assert delta_str(59) == "59s"  # >= 10: no fractional

    def test_minutes_only(self):
        """Test formatting minutes only."""
        assert delta_str(60) == "1m0s"
        assert delta_str(120) == "2m0s"
        assert delta_str(300) == "5m0s"
        assert delta_str(3540) == "59m0s"

    def test_hours_only(self):
        """Test formatting hours only."""
        assert delta_str(3600) == "1h0m0s"
        assert delta_str(7200) == "2h0m0s"
        assert delta_str(18000) == "5h0m0s"

    def test_days_only(self):
        """Test formatting days only."""
        assert delta_str(86400) == "1d0h0m0s"
        assert delta_str(172800) == "2d0h0m0s"
        assert delta_str(259200) == "3d0h0m0s"


@pytest.mark.unit
class TestDeltaStrCombined:
    """Test combined unit formatting."""

    def test_minutes_and_seconds(self):
        """Test minutes with seconds."""
        assert delta_str(61) == "1m1s"
        assert delta_str(90) == "1m30s"
        assert delta_str(125) == "2m5s"

    def test_hours_minutes_seconds(self):
        """Test hours, minutes, and seconds."""
        assert delta_str(3661) == "1h1m1s"
        assert delta_str(3660) == "1h1m0s"
        assert delta_str(3600) == "1h0m0s"

    def test_days_hours_minutes_seconds(self):
        """Test days, hours, minutes, and seconds."""
        assert delta_str(90061) == "1d1h1m1s"
        assert delta_str(90060) == "1d1h1m0s"
        assert delta_str(86400) == "1d0h0m0s"

    def test_zero_padding(self):
        """Test no zero-padding for non-leading units (precise=False)."""
        assert delta_str(3605) == "1h0m5s"
        assert delta_str(3665) == "1h1m5s"
        assert delta_str(86405) == "1d0h0m5s"


@pytest.mark.unit
class TestDeltaStrFractional:
    """Test fractional seconds formatting."""

    def test_fractional_seconds(self):
        """Test fractional seconds formatting (< 10s shows fractional, >= 10s hides it)."""
        assert delta_str(1.5) == "1.500s"  # < 10: always 3 decimal places
        assert delta_str(1.123) == "1.123s"  # < 10: always 3 decimal places
        assert delta_str(1.001) == "1.001s"  # < 10: always 3 decimal places
        assert delta_str(9.999) == "9.999s"  # < 10: always 3 decimal places
        # Seconds >= 10 hide fractional
        assert delta_str(10.001) == "10s"
        assert delta_str(10.5) == "10s"
        assert delta_str(30.123) == "30s"

    def test_fractional_with_minutes(self):
        """Test fractional seconds with minutes (precise=False drops fractional)."""
        assert delta_str(61.5) == "1m1s"
        assert delta_str(90.123) == "1m30s"

    def test_fractional_with_hours(self):
        """Test fractional seconds with hours (precise=False drops fractional)."""
        assert delta_str(3661.5) == "1h1m1s"
        assert delta_str(3661.123) == "1h1m1s"

    def test_fractional_with_days(self):
        """Test fractional seconds with days (precise=False drops fractional)."""
        assert delta_str(90061.5) == "1d1h1m1s"


@pytest.mark.unit
class TestDeltaStrMilliseconds:
    """Test millisecond formatting."""

    def test_milliseconds_only(self):
        """Test milliseconds-only values."""
        assert delta_str(0.001) == "1ms"
        assert delta_str(0.010) == "10ms"
        assert delta_str(0.100) == "100ms"
        assert delta_str(0.999) == "999ms"

    def test_milliseconds_rounding(self):
        """Test milliseconds formatting with precise=False (< 1ms shows microseconds, >= 1ms shows fractional if < 10ms)."""
        # Values < 1ms show microseconds
        assert delta_str(0.0005) == "500μs"
        assert delta_str(0.0004) == "400μs"
        # Values >= 1ms and < 10ms show fractional
        assert delta_str(0.0015) == "1.5ms"


@pytest.mark.unit
class TestDeltaStrMicroseconds:
    """Test microsecond precision formatting."""

    def test_microseconds_with_flag(self):
        """Test microsecond formatting when precise=True."""
        assert delta_str(0.000001, precise=True) == "1μs"
        assert delta_str(0.00001, precise=True) == "10μs"
        assert delta_str(0.0001, precise=True) == "100μs"
        assert delta_str(0.0005, precise=True) == "500μs"

    def test_milliseconds_with_micros_flag(self):
        """Test milliseconds with microsecond precision."""
        assert delta_str(0.001, precise=True) == "1.000ms"
        assert delta_str(0.01, precise=True) == "10.000ms"

    def test_seconds_with_micros_comma_separator(self):
        """Test comma separator for microsecond precision."""
        assert delta_str(1.123456, precise=True) == "1.123,456s"
        assert delta_str(60.000001, precise=True) == "1m00.000,001s"
        assert delta_str(3661.123456, precise=True) == "1h01m01.123,456s"

    def test_microseconds_without_flag(self):
        """Test very small values without precise flag (now shows microseconds)."""
        assert delta_str(0.000001) == "1μs"
        assert delta_str(0.00001) == "10μs"


@pytest.mark.unit
class TestDeltaStrBoundaries:
    """Test boundary values and edge cases."""

    def test_boundary_values(self):
        """Test values at unit boundaries."""
        assert delta_str(59.999) == "59s"  # >= 10s hides fractional
        assert delta_str(60.0) == "1m0s"
        assert delta_str(60.001) == "1m0s"
        assert delta_str(3599.999) == "59m59s"
        assert delta_str(3600.0) == "1h0m0s"

    def test_very_large_values(self):
        """Test very large duration values."""
        # 100 days
        assert "100d" in delta_str(8640000)
        # 365 days
        assert "365d" in delta_str(31536000)

    def test_very_small_values(self):
        """Test very small duration values (< 1ms always shows microseconds)."""
        assert delta_str(0.0001) == "100μs"
        assert delta_str(0.0001, precise=True) == "100μs"


@pytest.mark.unit
class TestDeltaStrErrors:
    """Test error handling in delta_str."""

    def test_negative_values_raise_error(self):
        """Test negative values raise InvalidDurationError."""
        with pytest.raises(InvalidDurationError, match="cannot be negative"):
            delta_str(-1)
        with pytest.raises(InvalidDurationError, match="cannot be negative"):
            delta_str(-0.001)

    def test_nan_raises_error(self):
        """Test NaN raises InvalidDurationError."""
        with pytest.raises(InvalidDurationError, match="cannot be NaN"):
            delta_str(float("nan"))

    def test_infinity_raises_error(self):
        """Test infinity raises InvalidDurationError."""
        with pytest.raises(InvalidDurationError, match="cannot be infinite"):
            delta_str(float("inf"))
        with pytest.raises(InvalidDurationError, match="cannot be infinite"):
            delta_str(float("-inf"))

    def test_invalid_type_raises_error(self):
        """Test invalid types raise InvalidDurationError."""
        with pytest.raises(InvalidDurationError, match="must be a number"):
            delta_str("not a number")
        with pytest.raises(InvalidDurationError, match="must be a number"):
            delta_str([1, 2, 3])


# =============================================================================
# delta_to_secs() Tests - Parsing
# =============================================================================


@pytest.mark.unit
class TestDeltaToSecsSimple:
    """Test simple unit parsing."""

    def test_simple_seconds(self):
        """Test parsing simple seconds."""
        assert delta_to_secs("60s") == 60.0
        assert delta_to_secs("1s") == 1.0
        assert delta_to_secs("0s") == 0.0

    def test_simple_minutes(self):
        """Test parsing simple minutes."""
        assert delta_to_secs("1m") == 60.0
        assert delta_to_secs("5m") == 300.0
        assert delta_to_secs("60m") == 3600.0

    def test_simple_hours(self):
        """Test parsing simple hours."""
        assert delta_to_secs("1h") == 3600.0
        assert delta_to_secs("2h") == 7200.0
        assert delta_to_secs("24h") == 86400.0

    def test_simple_days(self):
        """Test parsing simple days."""
        assert delta_to_secs("1d") == 86400.0
        assert delta_to_secs("2d") == 172800.0


@pytest.mark.unit
class TestDeltaToSecsFractional:
    """Test fractional value parsing."""

    def test_fractional_seconds(self):
        """Test parsing fractional seconds."""
        assert delta_to_secs("1.5s") == 1.5
        assert delta_to_secs("45.500s") == 45.5
        assert delta_to_secs("0.001s") == 0.001

    def test_fractional_minutes(self):
        """Test parsing fractional minutes."""
        assert delta_to_secs("1.5m") == 90.0
        assert delta_to_secs("2.5m") == 150.0

    def test_fractional_hours(self):
        """Test parsing fractional hours."""
        assert delta_to_secs("1.5h") == 5400.0
        assert delta_to_secs("0.5h") == 1800.0


@pytest.mark.unit
class TestDeltaToSecsMilliseconds:
    """Test millisecond and microsecond parsing."""

    def test_milliseconds(self):
        """Test parsing milliseconds."""
        assert delta_to_secs("1ms") == 0.001
        assert delta_to_secs("100ms") == 0.1
        assert delta_to_secs("999ms") == 0.999

    def test_microseconds(self):
        """Test parsing microseconds."""
        assert delta_to_secs("1μs") == 0.000001
        assert delta_to_secs("1000μs") == 0.001

    def test_comma_separator_format(self):
        """Test parsing comma separator format (ms,μs)."""
        assert delta_to_secs("1.123,456s") == 1.123456
        assert delta_to_secs("1m00.000,001s") == 60.000001
        assert delta_to_secs("1h01m01.123,456s") == 3661.123456


@pytest.mark.unit
class TestDeltaToCombined:
    """Test parsing combined units."""

    def test_combined_units(self):
        """Test parsing combined units."""
        assert delta_to_secs("1h30m") == 5400.0
        assert delta_to_secs("1h01m01s") == 3661.0
        assert delta_to_secs("1h01m01.500s") == 3661.5
        assert delta_to_secs("2d12h30m45s") == 217845.0

    def test_order_independence(self):
        """Test that unit order doesn't matter."""
        assert delta_to_secs("30m1h") == 5400.0
        assert delta_to_secs("45s30m1h") == 5445.0
        # 1d=86400, 1h=3600, 1m=60, 1s=1 => 90061
        assert delta_to_secs("1s1m1h1d") == 90061.0


@pytest.mark.unit
class TestDeltaToSecsErrors:
    """Test error handling in delta_to_secs."""

    def test_empty_string_raises_error(self):
        """Test empty strings raise InvalidDurationError."""
        with pytest.raises(InvalidDurationError, match="cannot be empty"):
            delta_to_secs("")
        with pytest.raises(InvalidDurationError, match="cannot be empty"):
            delta_to_secs("   ")

    def test_invalid_format_raises_error(self):
        """Test invalid formats raise InvalidDurationError."""
        with pytest.raises(InvalidDurationError, match="Could not parse"):
            delta_to_secs("invalid")
        with pytest.raises(InvalidDurationError, match="Could not parse"):
            delta_to_secs("10x")

    def test_duplicate_units_raise_error(self):
        """Test duplicate units raise InvalidDurationError."""
        with pytest.raises(InvalidDurationError, match="Duplicate unit"):
            delta_to_secs("1h2h")
        with pytest.raises(InvalidDurationError, match="Duplicate unit"):
            delta_to_secs("30m15m")
        with pytest.raises(InvalidDurationError, match="Duplicate unit"):
            delta_to_secs("5s10s")


# =============================================================================
# Round-Trip Tests
# =============================================================================


@pytest.mark.unit
class TestRoundTrip:
    """Test round-trip conversion (seconds → string → seconds)."""

    @pytest.mark.parametrize(
        "secs",
        [
            60,
            120,
            3600,
            7200,
            86400,  # Exact units
            1.5,  # Fractional seconds (< 60s, preserved)
            0.001,
            0.010,
            0.100,
            0.999,  # Milliseconds
        ],
    )
    def test_round_trip_conversion(self, secs):
        """Test that conversion is reversible for precise=False (fractional preserved only for seconds < 60s)."""
        formatted = delta_str(secs)
        parsed = delta_to_secs(formatted)
        assert abs(parsed - secs) < 0.001  # Within 1ms

    @pytest.mark.parametrize(
        "secs",
        [
            61.5,
            3661.5,
            90061.5,  # Fractional with higher units (requires precise=True for round-trip)
        ],
    )
    def test_round_trip_conversion_precise(self, secs):
        """Test that conversion is reversible for precise=True with fractional and higher units."""
        formatted = delta_str(secs, precise=True)
        parsed = delta_to_secs(formatted)
        assert abs(parsed - secs) < 0.001  # Within 1ms

    @pytest.mark.parametrize(
        "secs",
        [
            0.000001,
            0.00001,
            0.0001,
            1.123456,
            60.000001,
        ],
    )
    def test_round_trip_with_microseconds(self, secs):
        """Test round-trip with microsecond precision."""
        formatted = delta_str(secs, precise=True)
        parsed = delta_to_secs(formatted)
        assert abs(parsed - secs) < 0.000001  # Within 1μs

    def test_round_trip_preserves_zero(self):
        """Test that zero survives round-trip."""
        assert delta_to_secs(delta_str(0)) == 0.0

    def test_round_trip_complex_durations(self):
        """Test round-trip with complex durations (requires precise=True for fractional preservation)."""
        test_cases = [
            3661.5,  # 1h01m01.500s
            90061.25,  # 1d01h01m01.250s
            217845.123,  # 2d12h30m45.123s
        ]
        for secs in test_cases:
            formatted = delta_str(secs, precise=True)
            parsed = delta_to_secs(formatted)
            assert abs(parsed - secs) < 0.001


# =============================================================================
# validate_duration() Tests
# =============================================================================


@pytest.mark.unit
class TestValidateDuration:
    """Test duration validation."""

    @pytest.mark.parametrize(
        "duration",
        [
            0,
            1,
            60,
            3600,
            86400,  # Common values
            1.5,
            0.001,
            0.000001,  # Fractional
            31536000,  # 1 year
        ],
    )
    def test_valid_durations(self, duration):
        """Test that valid durations return True."""
        assert validate_duration(duration) is True

    @pytest.mark.parametrize(
        "duration",
        [
            -1,
            -0.001,
            -100,  # Negative
        ],
    )
    def test_negative_durations_invalid(self, duration):
        """Test that negative durations are invalid."""
        assert validate_duration(duration) is False

    def test_nan_invalid(self):
        """Test that NaN is invalid."""
        assert validate_duration(float("nan")) is False

    def test_infinity_invalid(self):
        """Test that infinity is invalid."""
        assert validate_duration(float("inf")) is False
        assert validate_duration(float("-inf")) is False

    def test_non_numeric_invalid(self):
        """Test that non-numeric types are invalid."""
        assert validate_duration("string") is False
        assert validate_duration(None) is False
        assert validate_duration([1, 2, 3]) is False
        assert validate_duration({"key": "value"}) is False

    def test_unreasonably_large_invalid(self):
        """Test that unreasonably large values are invalid."""
        # More than 1000 years (>1000 years is invalid)
        thousand_years = 365.25 * 24 * 3600 * 1000
        assert validate_duration(thousand_years + 1) is False
        # Exactly 1000 years should be valid (boundary)
        assert validate_duration(thousand_years) is True

    def test_boundary_at_1000_years(self):
        """Test boundary at 1000 years."""
        # Just under 1000 years should be valid
        almost_thousand = 365.25 * 24 * 3600 * 999
        assert validate_duration(almost_thousand) is True


# =============================================================================
# Edge Cases & Integration
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_very_precise_fractional(self):
        """Test very precise fractional seconds."""
        # Test precision handling
        result = delta_str(1.123456789)
        # Should truncate to milliseconds without micros flag
        assert "1.123s" in result

    def test_zero_with_fractional_part(self):
        """Test zero with tiny fractional part (shows as microseconds)."""
        result = delta_str(0.0000001)
        assert result == "0μs"

    def test_just_below_minute(self):
        """Test value just below minute boundary (>= 10s hides fractional)."""
        assert delta_str(59.999) == "59s"

    def test_just_above_minute(self):
        """Test value just above minute boundary (precise=False drops fractional)."""
        assert delta_str(60.001) == "1m0s"

    def test_parsing_with_spaces(self):
        """Test parsing handles spaces gracefully."""
        # The parser removes spaces
        assert delta_to_secs("1h 30m") == 5400.0

    def test_format_parse_none(self):
        """Test that formatting None returns empty string."""
        assert delta_str(None) == ""

    def test_integer_vs_float_equivalence(self):
        """Test integer and float inputs give same results."""
        assert delta_str(60) == delta_str(60.0)
        assert delta_str(3600) == delta_str(3600.0)


@pytest.mark.integration
class TestDeltaIntegration:
    """Integration tests for duration utilities."""

    def test_typical_workflow(self):
        """Test typical usage workflow."""
        # Format a duration (precise=True for exact round-trip with fractional and higher units)
        duration_secs = 3661.5
        formatted = delta_str(duration_secs, precise=True)

        # Parse it back
        parsed = delta_to_secs(formatted)

        # Should be very close to original
        assert abs(parsed - duration_secs) < 0.001

    def test_user_input_validation_workflow(self):
        """Test validating user input."""
        # Valid input
        assert validate_duration(100) is True

        # Invalid inputs
        assert validate_duration(-1) is False
        assert validate_duration(float("inf")) is False

    def test_format_for_display(self):
        """Test formatting for user display."""
        durations = [0.5, 5, 65, 3665, 90065]
        formatted = [delta_str(d) for d in durations]

        # All should be non-empty strings
        assert all(isinstance(f, str) and len(f) > 0 for f in formatted)

        # All should be parseable back
        parsed = [delta_to_secs(f) for f in formatted]
        for orig, back in zip(durations, parsed):
            assert abs(orig - back) < 0.001

    def test_config_file_duration_parsing(self):
        """Test parsing durations from config files."""
        # Simulated config values
        config_values = {
            "timeout": "30s",
            "retry_delay": "5m",
            "session_duration": "2h",
            "cache_ttl": "1d",
        }

        parsed = {k: delta_to_secs(v) for k, v in config_values.items()}

        assert parsed["timeout"] == 30
        assert parsed["retry_delay"] == 300
        assert parsed["session_duration"] == 7200
        assert parsed["cache_ttl"] == 86400

    def test_microsecond_precision_workflow(self):
        """Test high-precision timing workflow."""
        # Measure very short duration
        short_duration = 0.000123  # 123 microseconds

        # Format with microsecond precision
        formatted = delta_str(short_duration, precise=True)
        assert "μs" in formatted

        # Parse back
        parsed = delta_to_secs(formatted)
        assert abs(parsed - short_duration) < 0.000001


@pytest.mark.unit
class TestEdgeCaseCoverage:
    """Test edge cases to achieve 100% coverage."""

    def test_rounding_999_5ms_to_1s(self):
        """Test that 999.5ms rounds to 1s (line 141)."""
        # 999.5ms should round to 1000ms which becomes "1s"
        assert delta_str(0.9995) == "1s"

    def test_precise_seconds_formatting(self):
        """Test precise formatting for seconds >= 10 (line 159)."""
        # With precise=True, should show exact fractional seconds
        assert delta_str(10.5, precise=True) == "10.500,000s"
        assert delta_str(15.123456, precise=True) == "15.123,456s"

    def test_fractional_rounding_to_1000ms(self):
        """Test fractional seconds that round to 1000ms become next second (line 180)."""
        # 5.9995s should round to 6s (fractional rounds to 1000ms)
        assert delta_str(5.9995) == "6s"
        # 59.9996s: fractional=0.9996 rounds to 1000ms, becomes 60s
        assert delta_str(59.9996) == "60s"
        assert delta_str(59.9999) == "60s"

    def test_sub_millisecond_precise_formatting(self):
        """Test sub-millisecond values with precise=True (lines 122-123)."""
        # Values < 1ms with precise=True should show microseconds
        assert delta_str(0.0005, precise=True) == "500μs"
        assert delta_str(0.0001, precise=True) == "100μs"
        assert delta_str(0.00001, precise=True) == "10μs"

    def test_invalid_characters_in_duration_string(self):
        """Test that invalid characters trigger error (line 422)."""
        with pytest.raises(InvalidDurationError) as exc_info:
            delta_to_secs("1d2x3m")  # 'x' is invalid
        assert "Invalid characters" in str(exc_info.value)

        with pytest.raises(InvalidDurationError) as exc_info:
            delta_to_secs("5s!!")  # '!' is invalid
        assert "Invalid characters" in str(exc_info.value)


@pytest.mark.unit
class TestInvalidDurationError:
    """Test InvalidDurationError exception."""

    def test_exception_inheritance(self):
        """Test exception inherits from Exception."""
        exc = InvalidDurationError("test")
        assert isinstance(exc, Exception)

    def test_exception_message(self):
        """Test exception message is preserved."""
        msg = "Duration must be positive"
        exc = InvalidDurationError(msg)
        assert str(exc) == msg
