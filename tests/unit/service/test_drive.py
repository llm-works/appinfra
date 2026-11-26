# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for how a service's thread task and a ProcessRunner drive a service, and
which services the Runner and ProcessRunner accept."""

from unittest.mock import MagicMock

import pytest

from appinfra.service import (
    AsyncService,
    ProcessRunner,
    Runner,
    ScheduledService,
    Service,
)
from appinfra.service.runtime.drive import drive


class FakeStop:
    """A stop signal that is set after *waits* calls to wait(); never, if None."""

    def __init__(self, waits: int | None = None) -> None:
        self._waits_left = waits
        self.timeouts: list[float | None] = []

    def is_set(self) -> bool:
        return self._waits_left is not None and self._waits_left <= 0

    def wait(self, timeout: float | None = None) -> bool:
        self.timeouts.append(timeout)
        if self._waits_left is not None:
            self._waits_left -= 1
        return self.is_set()


class Ticker(ScheduledService):
    interval = 5.0

    def __init__(self) -> None:
        self._lg = MagicMock()
        self.ticks = 0

    @property
    def name(self) -> str:
        return "ticker"

    def tick(self) -> None:
        self.ticks += 1


class Once(Service):
    def __init__(self) -> None:
        self._lg = MagicMock()
        self.runs = 0

    @property
    def name(self) -> str:
        return "once"

    def run(self) -> None:
        self.runs += 1


class Idle(AsyncService):
    def __init__(self) -> None:
        self._lg = MagicMock()

    @property
    def name(self) -> str:
        return "idle"

    async def run(self) -> None:
        raise AssertionError("never run by these tests")


class TickAndAwait(ScheduledService, AsyncService):
    """A scheduled service that is also an async one."""

    def __init__(self) -> None:
        self._lg = MagicMock()

    @property
    def name(self) -> str:
        return "both"

    def tick(self) -> None:
        raise AssertionError("a service of two kinds is never driven")


class TestDrive:
    """drive() with a ScheduledService and a service with its own run()."""

    def test_ticks_then_waits_interval_until_stopped(self):
        """tick() runs, then the loop waits interval seconds, until stop is set."""
        svc = Ticker()
        stop = FakeStop(waits=3)

        drive(svc, stop)

        assert svc.ticks == 3
        assert stop.timeouts == [5.0, 5.0, 5.0]

    def test_run_is_called_once(self):
        """run() is called once; drive() returns when it does."""
        svc = Once()

        drive(svc, FakeStop(waits=1))

        assert svc.runs == 1

    def test_scheduled_run_refuses(self):
        with pytest.raises(TypeError, match="driven through tick"):
            Ticker().run()

    def test_drive_refuses_an_async_service(self):
        """drive() checks too: a subprocess runs it without a runner's check."""
        with pytest.raises(TypeError, match="runs on an event loop"):
            drive(Idle(), FakeStop())


class TestRunnerAccepts:
    """Which services each runner accepts."""

    def test_non_service_is_refused(self):
        with pytest.raises(TypeError, match="must be a Service"):
            Runner(object())

    def test_scheduled_and_async_at_once_is_refused(self):
        with pytest.raises(
            TypeError, match="both a ScheduledService and an AsyncService"
        ):
            Runner(TickAndAwait())

    def test_a_process_runner_refuses_an_async_service(self):
        with pytest.raises(TypeError, match="runs on an event loop"):
            ProcessRunner(Idle())

    @pytest.mark.parametrize("service_cls", [Once, Ticker, Idle])
    def test_a_runner_takes_every_kind(self, service_cls: type):
        assert Runner(service_cls()).service is not None
