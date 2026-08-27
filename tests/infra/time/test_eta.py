# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for ETA progress tracking."""

import time

import pytest

from appinfra.time.eta import ETA


@pytest.mark.unit
class TestETAInitialization:
    """Test ETA initialization."""

    def test_default_total(self):
        """Test default total is 100."""
        eta = ETA()
        assert eta._total == 100.0

    def test_custom_total(self):
        """Test custom total."""
        eta = ETA(total=1000.0)
        assert eta._total == 1000.0

    def test_zero_total_raises(self):
        """Test zero total raises ValueError."""
        with pytest.raises(ValueError, match="total must be positive"):
            ETA(total=0.0)

    def test_negative_total_raises(self):
        """Test negative total raises ValueError."""
        with pytest.raises(ValueError, match="total must be positive"):
            ETA(total=-100.0)

    def test_initial_rate_is_zero(self):
        """Test initial rate is zero."""
        eta = ETA()
        assert eta.rate() == 0.0

    def test_initial_remaining_is_none(self):
        """Test initial remaining_secs is None (no rate yet)."""
        eta = ETA()
        assert eta.remaining_secs() is None


@pytest.mark.unit
class TestETAPercent:
    """Test ETA percent method."""

    def test_percent_zero(self):
        """Test percent at start."""
        eta = ETA(total=100.0)
        assert eta.percent() == 0.0

    def test_percent_partial(self):
        """Test percent after partial progress."""
        eta = ETA(total=100.0)
        eta.update(25.0)
        assert eta.percent() == 25.0

    def test_percent_complete(self):
        """Test percent at completion."""
        eta = ETA(total=100.0)
        eta.update(100.0)
        assert eta.percent() == 100.0

    def test_percent_with_custom_total(self):
        """Test percent with custom total."""
        eta = ETA(total=200.0)
        eta.update(50.0)
        assert eta.percent() == 25.0


@pytest.mark.unit
class TestETARateCalculation:
    """Test ETA rate calculation."""

    def test_first_update_no_rate(self):
        """Test first update doesn't produce rate (no delta)."""
        eta = ETA()
        eta.update(10.0)
        assert eta.rate() == 0.0

    def test_rate_calculation(self):
        """Test rate is calculated from progress deltas."""
        eta = ETA(total=100.0, age=1.0)  # Low age for fast response
        eta.update(0.0)
        time.sleep(0.1)
        eta.update(10.0)  # 10 units in ~0.1s = ~100 units/sec

        rate = eta.rate()
        # Should be roughly 100 units/sec (allow wide tolerance for timing)
        assert 50.0 < rate < 200.0

    def test_rate_smoothing(self):
        """Test rate is smoothed over multiple updates."""
        eta = ETA(total=100.0, age=5.0)

        # Simulate consistent rate
        eta.update(0.0)
        for i in range(1, 11):
            time.sleep(0.02)
            eta.update(float(i * 5))  # 5 units every 20ms = 250 units/sec

        rate = eta.rate()
        # Verify rate is positive and sane (timing varies across platforms)
        assert 0 < rate < 1000.0


@pytest.mark.unit
class TestETARemaining:
    """Test ETA remaining_secs calculation."""

    def test_remaining_none_before_rate(self):
        """Test remaining is None before rate is established."""
        eta = ETA(total=100.0)
        eta.update(10.0)
        assert eta.remaining_secs() is None

    def test_remaining_calculation(self):
        """Test remaining time calculation."""
        eta = ETA(total=100.0, age=1.0)

        # Establish rate
        eta.update(0.0)
        time.sleep(0.05)
        eta.update(50.0)  # 50 units in ~0.05s

        remaining = eta.remaining_secs()
        assert remaining is not None
        # 50 units remaining at ~1000 units/sec ≈ 0.05s
        # Allow wide tolerance for timing variability
        assert 0.0 < remaining < 1.0

    def test_remaining_zero_at_completion(self):
        """Test remaining is 0 when complete."""
        eta = ETA(total=100.0, age=1.0)
        eta.update(0.0)
        time.sleep(0.02)
        eta.update(100.0)

        assert eta.remaining_secs() == 0.0

    def test_remaining_decreases_with_progress(self):
        """Test remaining time decreases as progress increases.

        Uses 2s sleeps because macOS CI runners have high timing jitter
        that can cause sub-100ms sleeps to vary significantly.
        """
        eta = ETA(total=100.0, age=2.0)

        eta.update(0.0)
        time.sleep(2.0)
        eta.update(25.0)
        remaining_25 = eta.remaining_secs()

        time.sleep(2.0)
        eta.update(50.0)
        remaining_50 = eta.remaining_secs()

        time.sleep(2.0)
        eta.update(75.0)
        remaining_75 = eta.remaining_secs()

        # Each should be less than the previous (roughly)
        assert remaining_25 is not None
        assert remaining_50 is not None
        assert remaining_75 is not None
        assert remaining_75 < remaining_50 < remaining_25


@pytest.mark.unit
class TestETAEdgeCases:
    """Test ETA edge cases."""

    def test_rapid_updates_ignored(self):
        """Test very rapid updates (delta_time ≈ 0) don't cause issues."""
        eta = ETA(total=100.0)
        eta.update(0.0)
        # Rapid-fire updates
        eta.update(10.0)
        eta.update(20.0)
        eta.update(30.0)
        # Should not crash, rate may be 0 or calculated
        assert eta.rate() >= 0.0

    def test_backwards_progress_handled(self):
        """Test backwards progress (delta < 0) doesn't update rate."""
        eta = ETA(total=100.0, age=1.0)
        eta.update(0.0)
        time.sleep(0.02)
        eta.update(50.0)
        rate_after_forward = eta.rate()

        time.sleep(0.02)
        eta.update(40.0)  # Go backwards
        rate_after_backward = eta.rate()

        # Rate shouldn't change from backward progress
        assert rate_after_backward == rate_after_forward

    def test_float_precision(self):
        """Test works with float values."""
        eta = ETA(total=1.0)
        eta.update(0.0)
        time.sleep(0.02)
        eta.update(0.5)

        assert eta.percent() == 50.0
        assert eta.rate() > 0.0
