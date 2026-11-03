# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for ETA progress tracking."""

import time

import pytest

from appinfra.time.eta import ETA


@pytest.fixture
def clock(fake_clock):
    """Put this module's sleeps on the fake clock with ETA's, so they take no real time.

    Every assertion holds on the real clock as well. Each update() is bracketed by clock
    readings taken just before and after it, which bound the time it read; on the fake
    clock the two readings are equal and the bounds exact.
    """
    fake_clock.patch(__name__)


def _update(eta: ETA, completed: float) -> tuple[float, float]:
    """Update ``eta``; return the clock readings taken just before and just after."""
    before = time.monotonic()
    eta.update(completed)
    return before, time.monotonic()


def _rate_bounds(
    units: float, previous: tuple[float, float], current: tuple[float, float]
) -> tuple[float, float]:
    """The lowest and highest rate of ``units`` done between two bracketed updates."""
    (before0, after0), (before1, after1) = previous, current
    return units / (after1 - before0), units / (before1 - after0)


def _within(value: float, low: float, high: float) -> bool:
    """``low <= value <= high``, allowing for float rounding in ETA's arithmetic."""
    return low * (1 - 1e-9) <= value <= high * (1 + 1e-9)


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


class TestETARateCalculation:
    """Test ETA rate calculation."""

    def test_first_update_no_rate(self):
        """Test first update doesn't produce rate (no delta)."""
        eta = ETA()
        eta.update(10.0)
        assert eta.rate() == 0.0

    def test_rate_calculation(self, clock):
        """Test rate is calculated from progress deltas."""
        eta = ETA(total=100.0, age=1.0)  # Age 1: the rate is the latest sample's
        start = _update(eta, 0.0)
        time.sleep(0.25)
        end = _update(eta, 10.0)

        # 10 units over the time between the updates: 40 units/sec on the fake clock
        assert _within(eta.rate(), *_rate_bounds(10.0, start, end))

    def test_rate_smoothing(self, clock):
        """Test the smoothed rate of steady progress stays within its samples' rates."""
        eta = ETA(total=100.0, age=5.0)

        # A binary fraction of a second, so virtual time adds up without rounding
        readings = [_update(eta, 0.0)]
        for i in range(1, 11):
            time.sleep(1 / 64)
            readings.append(_update(eta, float(i * 5)))

        # The smoothed rate lies between its samples': 320 units/sec on the fake clock
        bounds = [_rate_bounds(5.0, a, b) for a, b in zip(readings, readings[1:])]
        low = min(lo for lo, _ in bounds)
        high = max(hi for _, hi in bounds)
        assert _within(eta.rate(), low, high)


class TestETARemaining:
    """Test ETA remaining_secs calculation."""

    def test_remaining_none_before_rate(self):
        """Test remaining is None before rate is established."""
        eta = ETA(total=100.0)
        eta.update(10.0)
        assert eta.remaining_secs() is None

    def test_remaining_calculation(self, clock):
        """Test remaining time calculation."""
        eta = ETA(total=100.0, age=1.0)

        # Establish rate
        start = _update(eta, 0.0)
        time.sleep(0.25)
        end = _update(eta, 50.0)

        # 200 units/sec on the fake clock, so 50 units left take 0.25s
        assert _within(eta.rate(), *_rate_bounds(50.0, start, end))
        assert eta.remaining_secs() == pytest.approx(50.0 / eta.rate())

    def test_remaining_zero_at_completion(self, clock):
        """Test remaining is 0 when complete."""
        eta = ETA(total=100.0, age=1.0)
        eta.update(0.0)
        time.sleep(0.02)
        eta.update(100.0)

        assert eta.remaining_secs() == 0.0

    def test_remaining_is_work_left_over_rate(self, clock):
        """Test remaining time is the work left at the smoothed rate, at every step."""
        eta = ETA(total=100.0, age=2.0)

        readings = [_update(eta, 0.0)]
        for completed in (25.0, 50.0, 75.0):
            time.sleep(0.25)
            readings.append(_update(eta, completed))
            bounds = [_rate_bounds(25.0, a, b) for a, b in zip(readings, readings[1:])]

            # The smoothed rate lies between its samples': 100 units/sec on the fake
            # clock, so 75, 50 and 25 units left take 0.75, 0.5 and 0.25s
            rate = eta.rate()
            assert _within(rate, min(b[0] for b in bounds), max(b[1] for b in bounds))
            assert eta.remaining_secs() == pytest.approx((100.0 - completed) / rate)


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

    def test_backwards_progress_handled(self, clock):
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

    def test_float_precision(self, clock):
        """Test works with float values."""
        eta = ETA(total=1.0)
        eta.update(0.0)
        time.sleep(0.02)
        eta.update(0.5)

        assert eta.percent() == 50.0
        assert eta.rate() > 0.0
