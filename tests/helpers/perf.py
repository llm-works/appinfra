# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""What the performance tests share."""

import sys
from collections.abc import Callable

# Share of a wall-clock rate floor enforced on macOS: its CI runners measure rates
# well under Linux runners on the same code; the full floor applies on Linux
RATE_SHARE = 0.5 if sys.platform == "darwin" else 1.0

# Attempts a rate measurement gets to clear its floor
ATTEMPTS = 3


def rates_over(
    floor: float, measure: Callable[[], tuple[float, ...]]
) -> tuple[float, ...]:
    """The rates *measure* returns, measured again while one is at or under
    *floor*, up to ATTEMPTS times in all; the last attempt's otherwise.

    A shared runner's noise only ever slows a run: a preempted attempt measures
    low, a clean one measures the code. A regression slows every attempt, so it
    still fails all of them.
    """
    for _ in range(ATTEMPTS - 1):
        rates = measure()
        if min(rates) > floor:
            return rates
    return measure()
