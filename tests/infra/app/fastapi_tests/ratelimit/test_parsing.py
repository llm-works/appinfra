# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for rate string parsing."""

import pytest

from appinfra.app.fastapi.ratelimit.parsing import parse_rate


@pytest.mark.unit
class TestParseRate:
    """Test parse_rate function."""

    def test_per_second(self):
        """Test parsing per-second rates."""
        assert parse_rate("10/s") == (10, 1.0)
        assert parse_rate("10/sec") == (10, 1.0)
        assert parse_rate("10/second") == (10, 1.0)
        assert parse_rate("10/seconds") == (10, 1.0)

    def test_per_minute(self):
        """Test parsing per-minute rates."""
        assert parse_rate("60/m") == (60, 60.0)
        assert parse_rate("60/min") == (60, 60.0)
        assert parse_rate("60/minute") == (60, 60.0)
        assert parse_rate("60/minutes") == (60, 60.0)

    def test_per_hour(self):
        """Test parsing per-hour rates."""
        assert parse_rate("1000/h") == (1000, 3600.0)
        assert parse_rate("1000/hr") == (1000, 3600.0)
        assert parse_rate("1000/hour") == (1000, 3600.0)
        assert parse_rate("1000/hours") == (1000, 3600.0)

    def test_per_day(self):
        """Test parsing per-day rates."""
        assert parse_rate("10000/d") == (10000, 86400.0)
        assert parse_rate("10000/day") == (10000, 86400.0)
        assert parse_rate("10000/days") == (10000, 86400.0)

    def test_whitespace_tolerance(self):
        """Test that whitespace is handled."""
        assert parse_rate("  60 / min  ") == (60, 60.0)

    def test_case_insensitive_unit(self):
        """Test that units are case-insensitive."""
        assert parse_rate("60/MIN") == (60, 60.0)
        assert parse_rate("60/Hour") == (60, 3600.0)

    def test_invalid_no_slash(self):
        """Test error on missing slash."""
        with pytest.raises(ValueError, match="count/unit"):
            parse_rate("60min")

    def test_invalid_multiple_slashes(self):
        """Test error on multiple slashes."""
        with pytest.raises(ValueError, match="count/unit"):
            parse_rate("60/min/sec")

    def test_invalid_non_integer_count(self):
        """Test error on non-integer count."""
        with pytest.raises(ValueError, match="integer"):
            parse_rate("3.5/min")

    def test_invalid_zero_count(self):
        """Test error on zero count."""
        with pytest.raises(ValueError, match="positive"):
            parse_rate("0/min")

    def test_invalid_negative_count(self):
        """Test error on negative count."""
        with pytest.raises(ValueError, match="positive"):
            parse_rate("-5/min")

    def test_invalid_unknown_unit(self):
        """Test error on unknown unit."""
        with pytest.raises(ValueError, match="Unknown rate unit"):
            parse_rate("60/fortnight")
