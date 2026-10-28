# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Virtual clock for tests of time-based code.

The ``fake_clock`` fixture replaces the ``time`` module reference in the
modules that schedule work (Ticker, RateLimiter, ETA) with a proxy whose
``monotonic()`` reads a virtual clock and whose ``sleep()`` advances it
instantly. Timing tests then run in microseconds with exact assertions, and
host load or CI jitter cannot make them flaky. The real ``time`` module is
untouched, so pytest and everything else keep real time.
"""

import importlib
import time
from typing import Any

import pytest

# Modules whose module-level `time` reference the fixture redirects
_CLOCKED_MODULES = ("appinfra.time.ticker", "appinfra.rate_limit", "appinfra.time.eta")


class FakeClock:
    """A monotonic clock that moves only when slept on."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        """Current virtual time."""
        return self.now

    def sleep(self, secs: float) -> None:
        """Advance virtual time by ``secs`` without waiting."""
        self.now += max(secs, 0.0)


class _TimeProxy:
    """Stands in for a module's `time`: monotonic and sleep from the clock, the rest real."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock

    def monotonic(self) -> float:
        return self._clock.monotonic()

    def sleep(self, secs: float) -> None:
        self._clock.sleep(secs)

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Run Ticker, RateLimiter and ETA on a virtual clock for one test.

    Objects that capture time functions when constructed (a Ticker's
    scheduler) must be created after this fixture is set up, which pytest
    guarantees for objects the test body creates.
    """
    clock = FakeClock()
    proxy = _TimeProxy(clock)
    for name in _CLOCKED_MODULES:
        monkeypatch.setattr(importlib.import_module(name), "time", proxy)
    return clock
