# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Exponentially Weighted Moving Average (EWMA) for streaming values.

EWMA provides a way to compute a running average that gives more weight to recent
values. This is useful for smoothing noisy data while remaining responsive to changes.

The decay factor determines how quickly old values are "forgotten":
- Higher age = smoother output, slower to react to changes
- Lower age = noisier output, faster to react to changes

Example:
    >>> from appinfra.ewma import EWMA
    >>>
    >>> # Track average request latency with 30-second smoothing
    >>> latency = EWMA(age=30.0)
    >>> latency.add(0.05)  # 50ms
    >>> latency.add(0.08)  # 80ms
    >>> latency.add(0.03)  # 30ms
    >>> print(f"Average latency: {latency.value():.3f}s")
"""


class EWMA:
    """
    Exponentially weighted moving average for streaming values.

    Uses the formula: avg = (new * decay) + (avg * (1 - decay))
    where decay = 2 / (age + 1)

    The 'age' parameter represents the average age of samples in the window.
    A higher age means smoother output but slower response to changes.
    """

    def __init__(self, age: float = 30.0) -> None:
        """
        Initialize EWMA with specified smoothing parameter.

        Args:
            age: Average age of samples. Higher = smoother, slower to react.
                 Default 30.0 gives decay ≈ 0.065.

        Raises:
            ValueError: If age is negative.
        """
        if age < 0:
            raise ValueError("age must be non-negative")

        self._decay = 2.0 / (age + 1.0)
        self._value = 0.0
        self._initialized = False

    def add(self, value: float) -> None:
        """
        Add a sample to the moving average.

        The first sample sets the initial value directly (no decay).
        Subsequent samples are blended using exponential weighting.

        Args:
            value: The sample value to add.
        """
        if not self._initialized:
            self._value = value
            self._initialized = True
        else:
            self._value = (value * self._decay) + (self._value * (1.0 - self._decay))

    def value(self) -> float:
        """
        Get the current smoothed average.

        Returns:
            The current EWMA value, or 0.0 if no samples added yet.
        """
        return self._value

    def reset(self, value: float = 0.0) -> None:
        """
        Reset the EWMA to a specific value.

        Args:
            value: The value to reset to (default 0.0).
        """
        self._value = value
        self._initialized = value != 0.0
