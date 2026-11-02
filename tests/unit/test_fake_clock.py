# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.testing's FakeClock and the fake_clock fixture."""

import sys
import time
import types

import pytest

import appinfra.rate_limit
from appinfra.testing import FakeClock

_MODULE = "fake_clock_target"


@pytest.fixture
def target(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """A module that does `import time` at module level, as project code does."""
    module = types.ModuleType(_MODULE)
    module.time = time  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, _MODULE, module)
    return module


class TestClock:
    """The clock moves only when slept on."""

    def test_sleep_advances_monotonic_by_exactly_the_amount(self):
        clock = FakeClock()
        clock.sleep(2.5)
        assert clock.monotonic() == 1002.5

    def test_negative_sleep_does_not_go_back(self):
        clock = FakeClock()
        clock.sleep(-1.0)
        assert clock.monotonic() == 1000.0

    def test_start(self):
        assert FakeClock(start=5.0).monotonic() == 5.0

    def test_time_starts_at_the_wall_clock(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0)
        assert FakeClock().time() == 1_700_000_000.0

    def test_time_advances_with_monotonic(self):
        clock = FakeClock()
        wall = clock.time()
        clock.sleep(8.0)
        assert clock.time() == wall + 8.0


class TestPatch:
    """A patched module's `time` reads the clock while the clock is active."""

    def test_module_runs_on_the_clock_inside_the_block(self, target):
        with FakeClock(modules=[_MODULE]) as clock:
            target.time.sleep(8.0)
            assert target.time.monotonic() == clock.monotonic() == 1008.0
            assert target.time.time() == clock.time()

    def test_other_functions_stay_real(self, target):
        with FakeClock(modules=[_MODULE]):
            assert target.time.perf_counter is time.perf_counter

    def test_module_gets_real_time_back_after_the_block(self, target):
        with FakeClock(modules=[_MODULE]):
            pass
        assert target.time is time

    def test_module_gets_real_time_back_after_an_exception(self, target):
        with pytest.raises(ValueError), FakeClock(modules=[_MODULE]):
            raise ValueError("boom")
        assert target.time is time

    def test_patch_inside_the_block(self, target):
        with FakeClock() as clock:
            clock.patch(_MODULE)
            target.time.sleep(5.0)
            assert clock.monotonic() == 1005.0
        assert target.time is time

    def test_patch_outside_the_block_raises(self, target):
        with pytest.raises(RuntimeError, match="outside"):
            FakeClock().patch(_MODULE)
        assert target.time is time

    def test_unknown_module_raises(self):
        with FakeClock() as clock, pytest.raises(ModuleNotFoundError):
            clock.patch("fake_clock_no_such_module")

    def test_module_without_time_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setitem(sys.modules, _MODULE, types.ModuleType(_MODULE))
        with FakeClock() as clock, pytest.raises(AttributeError, match="import time"):
            clock.patch(_MODULE)

    def test_appinfra_modules_on_the_clock_by_default(self):
        with FakeClock() as clock:
            appinfra.rate_limit.time.sleep(3.0)
            assert clock.monotonic() == 1003.0
        assert appinfra.rate_limit.time is time

    def test_decorator(self, target):
        @FakeClock(modules=[_MODULE])
        def wait_ten_seconds() -> float:
            target.time.sleep(10.0)
            return target.time.monotonic()

        assert wait_ten_seconds() == 1010.0
        assert target.time is time

    def test_decorator_starts_each_call_on_a_fresh_clock(self, target):
        @FakeClock(modules=[_MODULE])
        def wait_ten_seconds() -> float:
            target.time.sleep(10.0)
            return target.time.monotonic()

        assert wait_ten_seconds() == 1010.0
        assert wait_ten_seconds() == 1010.0

    def test_decorator_passes_arguments_and_keeps_the_name(self, target):
        @FakeClock(start=0.0, modules=[_MODULE])
        def wait(secs: float, *, times: int) -> float:
            for _ in range(times):
                target.time.sleep(secs)
            return target.time.monotonic()

        assert wait(2.0, times=3) == 6.0
        assert wait.__name__ == "wait"

    @FakeClock(modules=[_MODULE])
    def test_decorated_test_still_takes_fixtures(self, target):
        target.time.sleep(10.0)
        assert target.time.monotonic() == 1010.0


@pytest.fixture
def plugin_fake_clock(request: pytest.FixtureRequest, fake_clock):
    """The plugin's fake_clock fixture; --real-clock replaces it, so its tests skip there."""
    if request.config.getoption("--real-clock"):
        pytest.skip("--real-clock replaces the fake_clock fixture these tests check")
    return fake_clock


class TestFixture:
    """The fake_clock fixture: appinfra's modules on the clock, plus any the test patches."""

    def test_appinfra_modules_on_the_clock(self, plugin_fake_clock):
        appinfra.rate_limit.time.sleep(1.0)
        assert plugin_fake_clock.monotonic() == 1001.0

    def test_patch_a_project_module(self, plugin_fake_clock, target):
        plugin_fake_clock.patch(_MODULE)
        target.time.sleep(2.0)
        assert plugin_fake_clock.monotonic() == 1002.0
