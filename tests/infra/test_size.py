# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for size.py.

Tests key functionality including:
- size_str formatting
- size_to_bytes parsing
- Input validation
- Edge cases
"""

import pytest

from appinfra.size import InvalidSizeError, size_str, size_to_bytes, validate_size

# =============================================================================
# Test size_str Basic Formatting
# =============================================================================


@pytest.mark.unit
class TestSizeStrBasic:
    """Test basic size_str formatting."""

    def test_zero_bytes(self):
        """Test zero bytes."""
        assert size_str(0) == "0B"

    def test_bytes_under_kb(self):
        """Test bytes under 1KB."""
        assert size_str(1) == "1B"
        assert size_str(500) == "500B"
        assert size_str(1023) == "1023B"

    def test_exactly_one_kb(self):
        """Test exactly 1KB."""
        assert size_str(1024) == "1KB"

    def test_fractional_kb(self):
        """Test fractional KB values."""
        assert size_str(1536) == "1.5KB"
        assert size_str(2048) == "2KB"

    def test_megabytes(self):
        """Test megabyte values."""
        assert size_str(1024**2) == "1MB"
        assert size_str(1024**2 * 1.5) == "1.5MB"

    def test_gigabytes(self):
        """Test gigabyte values."""
        assert size_str(1024**3) == "1GB"
        assert size_str(1024**3 * 2.5) == "2.5GB"

    def test_terabytes(self):
        """Test terabyte values."""
        assert size_str(1024**4) == "1TB"

    def test_petabytes(self):
        """Test petabyte values."""
        assert size_str(1024**5) == "1PB"

    def test_none_returns_empty(self):
        """Test None input returns empty string."""
        assert size_str(None) == ""


# =============================================================================
# Test size_str Options
# =============================================================================


@pytest.mark.unit
class TestSizeStrOptions:
    """Test size_str options."""

    def test_precise_mode(self):
        """Test precise mode shows 3 decimal places."""
        assert size_str(1536, precise=True) == "1.500KB"
        assert size_str(1024, precise=True) == "1.000KB"
        assert size_str(1024**2, precise=True) == "1.000MB"

    def test_binary_mode_default(self):
        """Test binary mode is default (1024-based)."""
        # 1024 bytes = 1KB in binary
        assert size_str(1024, binary=True) == "1KB"
        assert size_str(1024) == "1KB"

    def test_si_mode(self):
        """Test SI mode (1000-based)."""
        # 1000 bytes = 1KB in SI
        assert size_str(1000, binary=False) == "1KB"
        assert size_str(1500, binary=False) == "1.5KB"
        assert size_str(1000000, binary=False) == "1MB"

    def test_precise_and_si(self):
        """Test precise mode with SI units."""
        assert size_str(1500, precise=True, binary=False) == "1.500KB"


# =============================================================================
# Test size_str Validation
# =============================================================================


@pytest.mark.unit
class TestSizeStrValidation:
    """Test size_str input validation."""

    def test_negative_raises(self):
        """Test negative size raises error."""
        with pytest.raises(InvalidSizeError, match="cannot be negative"):
            size_str(-1)

    def test_nan_raises(self):
        """Test NaN raises error."""
        with pytest.raises(InvalidSizeError, match="cannot be NaN"):
            size_str(float("nan"))

    def test_inf_raises(self):
        """Test infinity raises error."""
        with pytest.raises(InvalidSizeError, match="cannot be infinite"):
            size_str(float("inf"))

    def test_non_number_raises(self):
        """Test non-number raises error."""
        with pytest.raises(InvalidSizeError, match="must be a number"):
            size_str("1024")  # type: ignore


# =============================================================================
# Test size_to_bytes Parsing
# =============================================================================


@pytest.mark.unit
class TestSizeToBytes:
    """Test size_to_bytes parsing."""

    def test_parse_bytes(self):
        """Test parsing bytes."""
        assert size_to_bytes("500B") == 500
        assert size_to_bytes("0B") == 0

    def test_parse_kilobytes(self):
        """Test parsing kilobytes."""
        assert size_to_bytes("1KB") == 1024
        assert size_to_bytes("1.5KB") == 1536

    def test_parse_megabytes(self):
        """Test parsing megabytes."""
        assert size_to_bytes("1MB") == 1024**2
        assert size_to_bytes("1.5MB") == int(1024**2 * 1.5)

    def test_parse_gigabytes(self):
        """Test parsing gigabytes."""
        assert size_to_bytes("1GB") == 1024**3

    def test_parse_terabytes(self):
        """Test parsing terabytes."""
        assert size_to_bytes("1TB") == 1024**4

    def test_parse_petabytes(self):
        """Test parsing petabytes."""
        assert size_to_bytes("1PB") == 1024**5

    def test_case_insensitive(self):
        """Test case insensitive parsing."""
        assert size_to_bytes("1kb") == 1024
        assert size_to_bytes("1KB") == 1024
        assert size_to_bytes("1Kb") == 1024

    def test_iec_suffixes(self):
        """Test IEC suffixes (KiB, MiB, etc.)."""
        assert size_to_bytes("1KiB") == 1024
        assert size_to_bytes("1MiB") == 1024**2
        assert size_to_bytes("1GiB") == 1024**3

    def test_whitespace_stripped(self):
        """Test whitespace is stripped."""
        assert size_to_bytes("  1KB  ") == 1024


# =============================================================================
# Test size_to_bytes Validation
# =============================================================================


@pytest.mark.unit
class TestSizeToBytesValidation:
    """Test size_to_bytes input validation."""

    def test_empty_string_raises(self):
        """Test empty string raises error."""
        with pytest.raises(InvalidSizeError, match="cannot be empty"):
            size_to_bytes("")

    def test_whitespace_only_raises(self):
        """Test whitespace-only string raises error."""
        with pytest.raises(InvalidSizeError, match="cannot be empty"):
            size_to_bytes("   ")

    def test_invalid_format_raises(self):
        """Test invalid format raises error."""
        with pytest.raises(InvalidSizeError, match="Could not parse"):
            size_to_bytes("abc")

    def test_missing_unit_raises(self):
        """Test missing unit raises error."""
        with pytest.raises(InvalidSizeError, match="Could not parse"):
            size_to_bytes("1024")

    def test_unknown_unit_raises(self):
        """Test unknown unit raises error."""
        with pytest.raises(InvalidSizeError, match="Could not parse"):
            size_to_bytes("1XB")


# =============================================================================
# Test Round-Trip
# =============================================================================


@pytest.mark.unit
class TestRoundTrip:
    """Test round-trip conversion (size_str -> size_to_bytes)."""

    def test_round_trip_bytes(self):
        """Test round-trip for byte values."""
        for size in [0, 1, 500, 1023]:
            assert size_to_bytes(size_str(size)) == size

    def test_round_trip_kb(self):
        """Test round-trip for KB values."""
        for size in [1024, 1536, 2048, 10240]:
            assert size_to_bytes(size_str(size)) == size

    def test_round_trip_mb(self):
        """Test round-trip for MB values."""
        assert size_to_bytes(size_str(1024**2)) == 1024**2

    def test_round_trip_gb(self):
        """Test round-trip for GB values."""
        assert size_to_bytes(size_str(1024**3)) == 1024**3


# =============================================================================
# Test validate_size
# =============================================================================


@pytest.mark.unit
class TestValidateSize:
    """Test validate_size function."""

    def test_valid_sizes(self):
        """Test valid sizes return True."""
        assert validate_size(0) is True
        assert validate_size(1024) is True
        assert validate_size(1024**4) is True

    def test_negative_invalid(self):
        """Test negative sizes return False."""
        assert validate_size(-1) is False

    def test_nan_invalid(self):
        """Test NaN returns False."""
        assert validate_size(float("nan")) is False

    def test_inf_invalid(self):
        """Test infinity returns False."""
        assert validate_size(float("inf")) is False

    def test_non_number_invalid(self):
        """Test non-number returns False."""
        assert validate_size("1024") is False  # type: ignore

    def test_too_large_invalid(self):
        """Test extremely large values return False."""
        # More than 1 exabyte
        assert validate_size(1024**7) is False
