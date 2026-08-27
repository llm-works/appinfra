# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
ETA (Estimated Time of Arrival) progress tracking.

Provides accurate time-to-completion estimates using EWMA-smoothed rate calculation.
Handles variable update intervals - you don't need to call update() at fixed intervals.

Example:
    >>> from appinfra.time import ETA
    >>>
    >>> # Track progress of 1000 items
    >>> eta = ETA(total=1000)
    >>> for i, item in enumerate(items):
    ...     process(item)
    ...     eta.update(i + 1)
    ...     remaining = eta.remaining_secs()
    ...     if remaining is not None:
    ...         print(f"{eta.percent():.1f}% - {remaining:.0f}s remaining")
    >>>
    >>> # Or use percentage-based tracking (default total=100)
    >>> eta = ETA()
    >>> eta.update(25.0)  # 25% complete
    >>> eta.update(50.0)  # 50% complete
"""

import time

from ..ewma import EWMA


class ETA:
    """
    Estimate time to completion using EWMA-smoothed rate.

    Tracks progress updates and calculates a smoothed processing rate,
    then estimates remaining time based on work left to complete.
    """

    def __init__(self, total: float = 100.0, age: float = 30.0) -> None:
        """
        Initialize ETA tracker.

        Args:
            total: Total units to complete. Default 100.0 for percentage-based tracking.
            age: EWMA smoothing parameter. Higher = smoother rate, slower to react.

        Raises:
            ValueError: If total is not positive.
        """
        if total <= 0:
            raise ValueError("total must be positive")

        self._total = total
        self._rate_ewma = EWMA(age=age)
        self._last_time: float | None = None
        self._last_completed: float = 0.0
        self._completed: float = 0.0

    def update(self, completed: float) -> None:
        """
        Update with current progress.

        Args:
            completed: Absolute progress value (not delta). Should be between 0 and total.
        """
        now = time.monotonic()
        self._completed = completed

        if self._last_time is not None:
            delta_time = now - self._last_time
            delta_completed = completed - self._last_completed

            # Only update rate if meaningful time has passed (avoid division issues)
            if delta_time > 0.001 and delta_completed > 0:
                instant_rate = delta_completed / delta_time
                self._rate_ewma.add(instant_rate)

        self._last_time = now
        self._last_completed = completed

    def remaining_secs(self) -> float | None:
        """
        Estimate seconds until completion.

        Returns:
            Estimated seconds remaining, or None if rate is unknown/zero.
        """
        current_rate = self._rate_ewma.value()
        if current_rate <= 0:
            return None

        remaining_work = self._total - self._completed
        if remaining_work <= 0:
            return 0.0

        return remaining_work / current_rate

    def rate(self) -> float:
        """
        Get current smoothed processing rate.

        Returns:
            Units per second (smoothed), or 0.0 if no rate data yet.
        """
        return self._rate_ewma.value()

    def percent(self) -> float:
        """
        Get completion percentage.

        Returns:
            Percentage complete (0-100).
        """
        return (self._completed / self._total) * 100.0
