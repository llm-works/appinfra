# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for ScheduledService.run(): its tick loop."""

from unittest.mock import MagicMock

import pytest

from appinfra.service import ScheduledService


class FakeStop:
    """A stop signal that is set after *waits* calls to wait(); never, if None.
    *trace* records its waits, and the ticks of the service it stops."""

    def __init__(self, waits: int | None = None) -> None:
        self._waits_left = waits
        self.timeouts: list[float | None] = []
        self.trace: list[object] = []

    def is_set(self) -> bool:
        return self._waits_left is not None and self._waits_left <= 0

    def wait(self, timeout: float | None = None) -> bool:
        self.timeouts.append(timeout)
        self.trace.append(("wait", timeout))
        if self._waits_left is not None:
            self._waits_left -= 1
        return self.is_set()


class Ticker(ScheduledService):
    interval = 5.0

    def __init__(self, stop: FakeStop, fails: bool = False) -> None:
        self._lg = MagicMock()
        self.stopping = stop  # type: ignore[assignment]  # what run() reads
        self._fails = fails
        self.ticks = 0

    @property
    def name(self) -> str:
        return "ticker"

    def tick(self) -> None:
        self.ticks += 1
        self.stopping.trace.append("tick")  # type: ignore[attr-defined]
        if self._fails:
            raise RuntimeError("tick fails")


class TestScheduledRun:
    def test_ticks_then_waits_interval_until_stopped(self):
        """tick() runs at once, then the loop waits interval seconds, until
        stopping is set."""
        stop = FakeStop(waits=3)
        svc = Ticker(stop)

        svc.run()

        assert stop.trace == ["tick", ("wait", 5.0)] * 3

    def test_a_service_stopped_before_its_run_never_ticks(self):
        svc = Ticker(FakeStop(waits=0))

        svc.run()

        assert svc.ticks == 0

    def test_a_failing_tick_ends_the_run_with_its_error(self):
        stop = FakeStop()
        svc = Ticker(stop, fails=True)

        with pytest.raises(RuntimeError, match="tick fails"):
            svc.run()

        assert svc.ticks == 1
        assert stop.timeouts == []
