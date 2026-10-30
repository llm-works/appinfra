# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for date range utilities.

Tests key date range features including:
- Date iteration with various options
- Weekend filtering
- Date range generation
- Set operations for combining dates
"""

import datetime
from unittest.mock import patch

import pytest

from appinfra.time.date_range import (
    dates_from_lists,
    iter_dates,
    iter_dates_midnight_gmt,
)

# =============================================================================
# Test iter_dates
# =============================================================================


@pytest.mark.unit
class TestIterDates:
    """Test iter_dates function."""

    def test_iter_dates_basic(self):
        """Test iter_dates with basic parameters."""
        start_date = datetime.date.today() - datetime.timedelta(days=3)
        dates = list(iter_dates(start_date))

        assert len(dates) >= 3
        assert dates[0] == start_date

    def test_iter_dates_with_delay_hours(self):
        """Test iter_dates with delay_hours parameter."""
        start_date = datetime.date.today() - datetime.timedelta(days=2)
        dates = list(iter_dates(start_date, delay_hours=24))

        assert len(dates) >= 1
        assert dates[0] == start_date

    def test_iter_dates_with_subtract_days(self):
        """Test iter_dates with subtract_days parameter."""
        start_date = datetime.date.today() - datetime.timedelta(days=5)
        dates = list(iter_dates(start_date, subtract_days=2))

        # Should end 2 days before today
        assert len(dates) >= 1
        assert dates[0] == start_date

    def test_iter_dates_skip_weekends(self):
        """Test iter_dates with skip_weekends=True."""
        # Find a date range that includes a weekend
        start_date = datetime.date(2025, 12, 1)  # Sunday

        with patch("appinfra.time.date_range.datetime") as mock_dt:
            mock_dt.datetime.now.return_value.timestamp.return_value = (
                datetime.datetime(2025, 12, 10).timestamp()
            )
            mock_dt.datetime.fromtimestamp = datetime.datetime.fromtimestamp
            mock_dt.timedelta = datetime.timedelta
            mock_dt.date = datetime.date

            dates = list(iter_dates(start_date, skip_weekends=True))

            # Check that weekends are skipped
            for date in dates:
                assert date.weekday() < 5  # Monday=0 ... Friday=4

    def test_iter_dates_includes_weekends(self):
        """Test iter_dates includes weekends by default."""
        start_date = datetime.date(2025, 12, 1)  # Sunday

        with patch("appinfra.time.date_range.datetime") as mock_dt:
            mock_dt.datetime.now.return_value.timestamp.return_value = (
                datetime.datetime(2025, 12, 10).timestamp()
            )
            mock_dt.datetime.fromtimestamp = datetime.datetime.fromtimestamp
            mock_dt.timedelta = datetime.timedelta
            mock_dt.date = datetime.date

            dates = list(iter_dates(start_date, skip_weekends=False))

            # Check that weekends are included
            weekend_found = any(date.weekday() >= 5 for date in dates)
            assert weekend_found or len(dates) < 7  # Weekend should be in longer ranges


# =============================================================================
# Test iter_dates_midnight_gmt
# =============================================================================


@pytest.mark.unit
class TestIterDatesMidnightGmt:
    """Test iter_dates_midnight_gmt function."""

    def test_iter_dates_midnight_gmt_basic(self):
        """Test iter_dates_midnight_gmt with basic parameters."""
        start_date = datetime.date.today() - datetime.timedelta(days=3)
        dates = list(iter_dates_midnight_gmt(start_date))

        assert len(dates) >= 3
        assert dates[0] == start_date

    def test_iter_dates_midnight_gmt_with_subtract_days(self):
        """Test iter_dates_midnight_gmt with subtract_days."""
        start_date = datetime.date.today() - datetime.timedelta(days=5)
        dates = list(iter_dates_midnight_gmt(start_date, subtract_days=2))

        assert len(dates) >= 1
        assert dates[0] == start_date

    def test_iter_dates_midnight_gmt_skip_weekends(self):
        """Test iter_dates_midnight_gmt with skip_weekends=True."""
        start_date = datetime.date(2025, 12, 1)  # Sunday

        with patch("appinfra.time.date_range.datetime") as mock_dt:
            mock_dt.datetime.now.return_value.date.return_value = datetime.date(
                2025, 12, 10
            )
            mock_dt.timedelta = datetime.timedelta
            mock_dt.date = datetime.date

            dates = list(iter_dates_midnight_gmt(start_date, skip_weekends=True))

            # Check that weekends are skipped
            for date in dates:
                assert date.weekday() < 5

    def test_iter_dates_midnight_gmt_single_day(self):
        """Test iter_dates_midnight_gmt with single day range."""
        start_date = datetime.date.today()
        dates = list(iter_dates_midnight_gmt(start_date))

        assert len(dates) >= 1
        assert dates[0] == start_date


# =============================================================================
# Test dates_from_lists
# =============================================================================


@pytest.mark.unit
class TestDatesFromLists:
    """Test dates_from_lists function."""

    def test_dates_from_lists_with_individual_dates(self):
        """Test dates_from_lists with only individual dates."""
        dates_list = [
            datetime.date(2025, 12, 1),
            datetime.date(2025, 12, 5),
            datetime.date(2025, 12, 10),
        ]

        result = dates_from_lists(dates_list, strings=False)

        assert isinstance(result, set)
        assert len(result) == 3
        assert datetime.date(2025, 12, 1) in result

    def test_dates_from_lists_with_date_ranges(self):
        """Test dates_from_lists with date ranges."""
        dates_list = []
        date_range_list = [
            (datetime.date(2025, 12, 1), datetime.date(2025, 12, 3)),
        ]

        result = dates_from_lists(dates_list, date_range_list, strings=False)

        assert isinstance(result, set)
        assert len(result) == 3  # Jan 1, 2, 3
        assert datetime.date(2025, 12, 1) in result
        assert datetime.date(2025, 12, 2) in result
        assert datetime.date(2025, 12, 3) in result

    def test_dates_from_lists_combines_dates_and_ranges(self):
        """Test dates_from_lists combines individual dates and ranges."""
        dates_list = [datetime.date(2025, 12, 1)]
        date_range_list = [
            (datetime.date(2025, 12, 5), datetime.date(2025, 12, 7)),
        ]

        result = dates_from_lists(dates_list, date_range_list, strings=False)

        assert len(result) == 4  # 1, 5, 6, 7
        assert datetime.date(2025, 12, 1) in result
        assert datetime.date(2025, 12, 5) in result
        assert datetime.date(2025, 12, 6) in result
        assert datetime.date(2025, 12, 7) in result

    def test_dates_from_lists_removes_duplicates(self):
        """Test dates_from_lists removes duplicate dates."""
        dates_list = [
            datetime.date(2025, 12, 1),
            datetime.date(2025, 12, 1),  # Duplicate
        ]
        date_range_list = [
            (datetime.date(2025, 12, 1), datetime.date(2025, 12, 2)),
        ]

        result = dates_from_lists(dates_list, date_range_list, strings=False)

        assert len(result) == 2  # Only 1 and 2, duplicate removed

    def test_dates_from_lists_returns_strings(self):
        """Test dates_from_lists returns strings when strings=True."""
        dates_list = [datetime.date(2025, 12, 1)]

        result = dates_from_lists(dates_list, strings=True)

        assert isinstance(result, set)
        assert len(result) == 1
        # Check that result contains strings
        for item in result:
            assert isinstance(item, str)

    def test_dates_from_lists_empty_lists(self):
        """Test dates_from_lists with empty lists."""
        result = dates_from_lists([], [], strings=False)

        assert isinstance(result, set)
        assert len(result) == 0

    def test_dates_from_lists_with_multiple_ranges(self):
        """Test dates_from_lists with multiple date ranges."""
        dates_list = []
        date_range_list = [
            (datetime.date(2025, 12, 1), datetime.date(2025, 12, 2)),
            (datetime.date(2025, 12, 5), datetime.date(2025, 12, 6)),
        ]

        result = dates_from_lists(dates_list, date_range_list, strings=False)

        assert len(result) == 4  # 1, 2, 5, 6
        assert datetime.date(2025, 12, 3) not in result  # Gap should not be included


# =============================================================================
# Test Integration Scenarios
# =============================================================================


@pytest.mark.integration
class TestIntegrationScenarios:
    """Test real-world date range scenarios."""

    def test_business_days_workflow(self):
        """Test getting business days for a range."""
        start_date = datetime.date(2025, 12, 2)  # Monday

        with patch("appinfra.time.date_range.datetime") as mock_dt:
            mock_dt.datetime.now.return_value.date.return_value = datetime.date(
                2025, 12, 10
            )
            mock_dt.timedelta = datetime.timedelta
            mock_dt.date = datetime.date

            dates = list(iter_dates_midnight_gmt(start_date, skip_weekends=True))

            # Should only have weekdays
            for date in dates:
                assert date.weekday() < 5

    def test_combining_dates_workflow(self):
        """Test complete workflow of combining dates."""
        # Individual important dates
        individual_dates = [
            datetime.date(2025, 12, 1),  # New Year
            datetime.date(2025, 12, 25),  # Christmas
        ]

        # Date ranges
        ranges = [
            (datetime.date(2025, 12, 1), datetime.date(2025, 12, 7)),  # Week in June
        ]

        all_dates = dates_from_lists(individual_dates, ranges, strings=False)

        # Should have 8 unique dates (Dec 1-7 from range + Dec 25, with Dec 1 deduplicated)
        assert len(all_dates) == 8
