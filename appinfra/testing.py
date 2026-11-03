# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Generic pytest utilities for appinfra-based projects.

This module provides pytest markers and hooks for common testing patterns.
Use as a pytest plugin by adding to your conftest.py:

    pytest_plugins = ["appinfra.testing"]

Markers:
    expected_skip: Mark tests where skipping is expected/acceptable.
        These skips won't appear in check.sh warning summaries.

Fixtures:
    destroy_test_loggers (autouse): destroys the loggers a test created with
        LoggerFactory and left registered, so the next test can create the same names.
    fake_clock: runs appinfra's Ticker, RateLimiter and ETA, and any module the test
        names with fake_clock.patch("myapp.retry"), on a FakeClock.

Example:
    @pytest.mark.expected_skip
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
    def test_windows_paths():
        ...
"""

from __future__ import annotations

import functools
import importlib
import inspect
import threading
import time
from collections.abc import Callable, Generator, Iterable
from types import ModuleType
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

import pytest

from .log import LoggerFactory

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.nodes import Item
    from _pytest.reports import TestReport
    from _pytest.runner import CallInfo


# Prefix added to skip reasons for expected skips (filtered by check.sh)
EXPECTED_SKIP_PREFIX = "[expected] "


def pytest_configure(config: Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "expected_skip: Mark test where skipping is expected/acceptable. "
        "These skips won't appear in check.sh warning summaries.",
    )


@pytest.fixture(autouse=True)
def destroy_test_loggers() -> Generator[None, None, None]:
    """
    Destroy the loggers a test created with LoggerFactory and left registered.

    LoggerFactory.create() raises for a name this process already holds, so a logger
    one test leaves behind fails the next test in the same process that creates the
    same name. Loggers that existed before the test (session or module fixtures) stay.
    """
    before = LoggerFactory.names()
    yield
    for name in LoggerFactory.names() - before:
        # destroying a parent already removed the loggers derived from it
        LoggerFactory.destroy_if_exists(name)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: Item, call: CallInfo[None]
) -> Generator[None, TestReport, TestReport]:
    """
    Modify skip reason for tests marked with expected_skip.

    When a test with the expected_skip marker is skipped, this hook prefixes
    the skip reason with '[expected] ' so that check.sh can filter it out
    of the warning summary.
    """
    report: TestReport = yield

    # Process skipped tests in call or setup phase (not teardown - rare and typically fixture failures)
    if (
        report.skipped
        and call.when in ("call", "setup")
        and item.get_closest_marker("expected_skip")
    ):
        _prefix_skip_reason(report)

    return report


# appinfra's modules that read time through a module-level `import time`: every FakeClock puts
# them on its clock
_APPINFRA_CLOCKED_MODULES = (
    "appinfra.time.ticker",
    "appinfra.rate_limit",
    "appinfra.time.eta",
)
# The Ticker also waits on threading.Event (its scheduler's delay and its iterator)
_TICKER_MODULE = "appinfra.time.ticker"

_P = ParamSpec("_P")
_R = TypeVar("_R")


class FakeClock:
    """
    A virtual clock that takes the waiting out of tests of time-based code: it moves only
    when slept on.

    While active, as a context manager, a decorator or the fake_clock fixture, it stands in
    for the module-level ``time`` of appinfra's Ticker, RateLimiter and ETA, of the modules
    given as ``modules``, and of any module passed to patch(): their ``time.monotonic()``,
    ``time.time()`` and ``time.sleep()`` read and advance the clock, so a sleep returns at
    once. Every other ``time`` function stays real, and so does the time of every module not
    patched (pytest, logging). On exit the modules get their real ``time`` back.

    The clock only speeds a test up: a test on it must pass on the real clock as well, so it
    asserts what the code does rather than the clock's readings, and any bound on time holds
    however much real time passes too (an elapsed time at least, a time remaining at most).

    As a decorator, each call runs on a fresh clock made from the same ``start`` and
    ``modules``; it does not take an async or generator function.

    Limits: only a module-level ``import time`` is redirected, not ``from time import
    sleep``, which binds the real function when the module is imported. Code on the clock
    runs in one thread: the Ticker's threading.Event waits advance the clock instead of
    blocking, so a wait that is not already set runs out its full timeout.
    """

    def __init__(self, start: float = 1000.0, modules: Iterable[str] = ()) -> None:
        """Start the clock at ``start`` (monotonic seconds); ``modules`` are patched on enter."""
        self.now = start
        self._start = start
        self._wall_start = time.time()
        self._modules = tuple(modules)
        self._saved: list[tuple[ModuleType, str, Any]] | None = None

    def monotonic(self) -> float:
        """Current virtual monotonic time."""
        return self.now

    def time(self) -> float:
        """Virtual wall-clock time: the real time when the clock was made, plus what it ran."""
        return self._wall_start + (self.now - self._start)

    def sleep(self, secs: float) -> None:
        """Advance virtual time by ``secs`` without waiting."""
        self.now += max(secs, 0.0)

    def patch(self, *modules: str) -> None:
        """Put each named module's module-level ``time`` on this clock until it exits."""
        if self._saved is None:
            raise RuntimeError("FakeClock.patch() called outside an active FakeClock")
        for name in modules:
            module = importlib.import_module(name)
            current = vars(module).get("time")
            if current is not time and not isinstance(current, _TimeProxy):
                raise AttributeError(
                    f"{name} has no module-level time: patch() redirects `import time`"
                )
            self._swap(module, "time", _TimeProxy(self))

    def __enter__(self) -> FakeClock:
        """Patch appinfra's clocked modules and ``modules``."""
        if self._saved is not None:
            raise RuntimeError("FakeClock is already active")
        self._saved = []
        try:
            self.patch(*_APPINFRA_CLOCKED_MODULES, *self._modules)
            ticker = importlib.import_module(_TICKER_MODULE)
            self._swap(ticker, "threading", _ThreadingProxy(self))
        except BaseException:
            self._restore()
            raise
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Give every patched module its real ``time`` back."""
        self._restore()

    def __call__(self, func: Callable[_P, _R]) -> Callable[_P, _R]:
        """Decorate ``func`` to run each call on a fresh clock like this one.

        Raises TypeError for an async or generator function: calling one only makes the
        coroutine or generator, whose body would run after the clock exits.
        """
        if (
            inspect.iscoroutinefunction(func)
            or inspect.isgeneratorfunction(func)
            or inspect.isasyncgenfunction(func)
        ):
            raise TypeError(
                f"FakeClock cannot decorate {_callable_name(func)}, an async or generator "
                "function: its body would run after the clock exits; use "
                "`with FakeClock(...)` inside it, or the fake_clock fixture"
            )

        @functools.wraps(func)
        def on_clock(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            with FakeClock(self._start, self._modules):
                return func(*args, **kwargs)

        return on_clock

    def _swap(self, module: ModuleType, attr: str, value: Any) -> None:
        """Set ``module.attr`` to ``value``, recording the old value for _restore()."""
        assert self._saved is not None
        self._saved.append((module, attr, getattr(module, attr)))
        setattr(module, attr, value)

    def _restore(self) -> None:
        """Undo every swap, last first, and deactivate the clock."""
        saved, self._saved = self._saved or [], None
        for module, attr, value in reversed(saved):
            setattr(module, attr, value)


def _callable_name(func: Callable[..., Any]) -> str:
    """The qualified name of ``func``, through any functools.partial around it.

    A partial has no __qualname__, and its repr would also print the arguments it binds.
    """
    while isinstance(func, functools.partial):
        func = func.func
    return getattr(func, "__qualname__", type(func).__name__)


class _TimeProxy:
    """Stands in for a module's ``time``: monotonic, time and sleep from the clock, the rest real."""

    def __init__(self, clock: FakeClock) -> None:
        """Read and advance ``clock``."""
        self._clock = clock

    def monotonic(self) -> float:
        """The clock's monotonic time."""
        return self._clock.monotonic()

    def time(self) -> float:
        """The clock's wall-clock time."""
        return self._clock.time()

    def sleep(self, secs: float) -> None:
        """Advance the clock by ``secs``."""
        self._clock.sleep(secs)

    def __getattr__(self, name: str) -> Any:
        """Any other attribute from the real ``time`` module."""
        return getattr(time, name)


class _FakeEvent:
    """A threading.Event for one thread whose wait() advances the virtual clock."""

    def __init__(self, clock: FakeClock) -> None:
        """An unset event on ``clock``."""
        self._clock = clock
        self._flag = False

    def set(self) -> None:
        """Set the flag."""
        self._flag = True

    def clear(self) -> None:
        """Clear the flag."""
        self._flag = False

    def is_set(self) -> bool:
        """Whether the flag is set."""
        return self._flag

    def wait(self, timeout: float | None = None) -> bool:
        """Return the flag; when unset, first advance the clock by ``timeout``."""
        if not self._flag and timeout is not None:
            self._clock.sleep(timeout)
        return self._flag


class _ThreadingProxy:
    """Stands in for the ticker module's ``threading``: Event on the clock, the rest real."""

    def __init__(self, clock: FakeClock) -> None:
        """Make events on ``clock``."""
        self._clock = clock

    def Event(self) -> _FakeEvent:  # noqa: N802 - mirrors threading.Event
        """A new event on the clock."""
        return _FakeEvent(self._clock)

    def __getattr__(self, name: str) -> Any:
        """Any other attribute from the real ``threading`` module."""
        return getattr(threading, name)


@pytest.fixture
def fake_clock() -> Generator[FakeClock, None, None]:
    """
    Run appinfra's Ticker, RateLimiter and ETA on a FakeClock for one test.

    ``fake_clock.patch("myapp.retry")`` puts a project's own module on the same clock. The
    test must pass on the real clock as well; the fake one only removes the waiting.
    Objects that capture time functions when constructed (a Ticker's scheduler and stop
    event) must be created after this fixture is set up, which pytest guarantees for
    objects the test body creates.
    """
    with FakeClock() as clock:
        yield clock


def _prefix_skip_reason(report: TestReport) -> None:
    """Add [expected] prefix to a skip report's reason."""
    # report.longrepr is a tuple: (file, line, reason)
    if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
        file_path, line, reason = report.longrepr
        if not reason.startswith(EXPECTED_SKIP_PREFIX):
            report.longrepr = (file_path, line, f"{EXPECTED_SKIP_PREFIX}{reason}")
