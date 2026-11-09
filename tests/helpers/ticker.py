# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Handlers and spies for ticker tests."""

from typing import Any
from unittest.mock import Mock

import pytest

import appinfra.time.ticker
from appinfra.time.ticker import Ticker, TickerHandler


class SimpleHandler(TickerHandler):
    """A TickerHandler that counts ticks and records start and stop."""

    def __init__(self) -> None:
        self.tick_count = 0
        self.started = False
        self.stopped = False

    def ticker_start(self, *args: Any, **kwargs: Any) -> None:
        self.started = True

    def ticker_tick(self) -> None:
        self.tick_count += 1

    def ticker_stop(self) -> None:
        self.stopped = True


class TimeSpy:
    """Stands in for a module's ``time`` (real or the fake clock's): records the sleep()
    calls and passes everything on to it."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.sleeps: list[float] = []

    def sleep(self, secs: float) -> None:
        self.sleeps.append(secs)
        self.inner.sleep(secs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def spy_on_waits(
    ticker: Ticker, monkeypatch: pytest.MonkeyPatch
) -> tuple[TimeSpy, Mock]:
    """Record every sleep in the ticker module and every wait on ``ticker``'s stop event,
    which is how run() waits for its next tick."""
    sleeps = TimeSpy(appinfra.time.ticker.time)
    monkeypatch.setattr(appinfra.time.ticker, "time", sleeps)
    waits = Mock(wraps=ticker._stop_event.wait)
    ticker._stop_event.wait = waits  # type: ignore[method-assign]
    return sleeps, waits
