# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for utility functions.

Tests key utility features including:
- Value formatting
- Type checking
"""

import pytest

from appinfra.utils import is_int, pretty

# =============================================================================
# Test pretty() Function
# =============================================================================


@pytest.mark.unit
class TestPrettyFunction:
    """Test pretty() formatting function."""

    def test_pretty_with_integer(self):
        """Test pretty() formats integers with commas."""
        assert pretty(1000) == "1,000"
        assert pretty(1000000) == "1,000,000"
        assert pretty(123456789) == "123,456,789"

    def test_pretty_with_small_integer(self):
        """Test pretty() with small integers."""
        assert pretty(0) == "0"
        assert pretty(1) == "1"
        assert pretty(999) == "999"

    def test_pretty_with_negative_integer(self):
        """Test pretty() with negative integers."""
        assert pretty(-1000) == "-1,000"
        assert pretty(-123456) == "-123,456"

    def test_pretty_with_string(self):
        """Test pretty() returns strings unchanged."""
        assert pretty("hello") == "hello"
        assert pretty("12345") == "12345"

    def test_pretty_with_float(self):
        """Test pretty() returns floats unchanged."""
        value = 123.45
        assert pretty(value) == value

    def test_pretty_with_none(self):
        """Test pretty() returns None unchanged."""
        assert pretty(None) is None

    def test_pretty_with_list(self):
        """Test pretty() returns lists unchanged."""
        value = [1, 2, 3]
        assert pretty(value) == value


# =============================================================================
# Test is_int() Function
# =============================================================================


@pytest.mark.unit
class TestIsIntFunction:
    """Test is_int() type checking function."""

    def test_is_int_with_integer(self):
        """Test is_int() returns True for integers."""
        assert is_int(123) is True
        assert is_int(0) is True
        assert is_int(-456) is True

    def test_is_int_with_string_integer(self):
        """Test is_int() returns True for string integers."""
        assert is_int("123") is True
        assert is_int("0") is True
        assert is_int("-456") is True

    def test_is_int_with_float(self):
        """Test is_int() returns True for floats convertible to int."""
        assert is_int(123.0) is True
        assert is_int(0.0) is True

    def test_is_int_with_string_float(self):
        """Test is_int() returns False for string floats."""
        # String floats like "123.0" cannot be directly converted to int
        assert is_int("123.0") is False
        assert is_int("0.0") is False

    def test_is_int_with_invalid_string(self):
        """Test is_int() returns False for non-numeric strings."""
        assert is_int("hello") is False
        assert is_int("12.34.56") is False
        assert is_int("") is False

    def test_is_int_with_none(self):
        """Test is_int() returns False for None."""
        assert is_int(None) is False

    def test_is_int_with_list(self):
        """Test is_int() returns False for lists."""
        assert is_int([1, 2, 3]) is False

    def test_is_int_with_dict(self):
        """Test is_int() returns False for dicts."""
        assert is_int({"key": "value"}) is False

    def test_is_int_with_boolean(self):
        """Test is_int() with boolean values."""
        # Booleans are technically convertible to int in Python
        assert is_int(True) is True
        assert is_int(False) is True


# =============================================================================
# Test Edge Cases
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases for utility functions."""

    def test_pretty_with_zero(self):
        """Test pretty() with zero."""
        assert pretty(0) == "0"

    def test_is_int_with_very_large_number(self):
        """Test is_int() with very large numbers."""
        assert is_int(10**100) is True
        assert is_int(str(10**100)) is True

    def test_is_int_with_whitespace_string(self):
        """Test is_int() with whitespace in string."""
        assert is_int("  123  ") is True
        assert is_int("  ") is False
