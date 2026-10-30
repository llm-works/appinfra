# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for EWMA (Exponentially Weighted Moving Average)."""

import pytest

from appinfra.ewma import EWMA


@pytest.mark.unit
class TestEWMAInitialization:
    """Test EWMA initialization."""

    def test_default_age(self):
        """Test default age parameter."""
        ewma = EWMA()
        # decay = 2 / (30 + 1) ≈ 0.0645
        assert abs(ewma._decay - 0.0645) < 0.001

    def test_custom_age(self):
        """Test custom age parameter."""
        ewma = EWMA(age=10.0)
        # decay = 2 / (10 + 1) ≈ 0.182
        assert abs(ewma._decay - 0.182) < 0.001

    def test_zero_age(self):
        """Test age=0 gives decay=2.0 (capped effectively at 1.0 behavior)."""
        ewma = EWMA(age=0.0)
        assert ewma._decay == 2.0  # Formula gives 2/(0+1)=2

    def test_negative_age_raises(self):
        """Test negative age raises ValueError."""
        with pytest.raises(ValueError, match="age must be non-negative"):
            EWMA(age=-1.0)

    def test_initial_value_is_zero(self):
        """Test initial value is zero."""
        ewma = EWMA()
        assert ewma.value() == 0.0


@pytest.mark.unit
class TestEWMAAddAndValue:
    """Test EWMA add and value methods."""

    def test_first_sample_sets_value(self):
        """Test first sample sets value directly (no decay)."""
        ewma = EWMA(age=10.0)
        ewma.add(100.0)
        assert ewma.value() == 100.0

    def test_second_sample_applies_decay(self):
        """Test second sample applies exponential decay."""
        ewma = EWMA(age=10.0)  # decay ≈ 0.182
        ewma.add(100.0)
        ewma.add(0.0)
        # Expected: 0 * 0.182 + 100 * 0.818 ≈ 81.8
        assert 81.0 < ewma.value() < 82.0

    def test_convergence_to_constant(self):
        """Test EWMA converges when fed constant values."""
        ewma = EWMA(age=5.0)  # decay = 2/6 ≈ 0.333, faster convergence
        for _ in range(50):
            ewma.add(50.0)
        # Should converge very close to 50
        assert abs(ewma.value() - 50.0) < 0.01

    def test_responds_to_change(self):
        """Test EWMA responds to value changes."""
        ewma = EWMA(age=5.0)
        # Feed low values
        for _ in range(20):
            ewma.add(10.0)
        low_value = ewma.value()

        # Feed high values
        for _ in range(20):
            ewma.add(100.0)
        high_value = ewma.value()

        # Should have moved significantly toward 100
        assert high_value > low_value
        assert high_value > 80.0

    def test_higher_age_smoother(self):
        """Test higher age gives smoother (slower) response."""
        ewma_fast = EWMA(age=5.0)
        ewma_slow = EWMA(age=50.0)

        # Initialize both to 0
        ewma_fast.add(0.0)
        ewma_slow.add(0.0)

        # Add spike
        ewma_fast.add(100.0)
        ewma_slow.add(100.0)

        # Fast should respond more
        assert ewma_fast.value() > ewma_slow.value()


@pytest.mark.unit
class TestEWMAReset:
    """Test EWMA reset method."""

    def test_reset_to_zero(self):
        """Test reset to zero."""
        ewma = EWMA()
        ewma.add(100.0)
        ewma.reset()
        assert ewma.value() == 0.0

    def test_reset_to_value(self):
        """Test reset to specific value."""
        ewma = EWMA()
        ewma.add(100.0)
        ewma.reset(50.0)
        assert ewma.value() == 50.0

    def test_reset_reinitializes(self):
        """Test that reset allows proper reinitialization."""
        ewma = EWMA()
        ewma.add(100.0)
        ewma.reset()
        # After reset to 0, adding should set directly (uninitialized state)
        ewma.add(25.0)
        assert ewma.value() == 25.0

    def test_reset_to_nonzero_marks_initialized(self):
        """Test reset to non-zero marks as initialized."""
        ewma = EWMA(age=10.0)
        ewma.reset(50.0)
        ewma.add(100.0)
        # Should apply decay, not set directly
        assert ewma.value() != 100.0
        assert ewma.value() > 50.0
