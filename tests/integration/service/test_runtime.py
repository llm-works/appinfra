# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the Runtime: spawn, dependencies, stop order, supervision."""

from __future__ import annotations

import asyncio
import random
import threading
import time
from collections.abc import Callable, Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.log import Logger
from appinfra.service import (
    AsyncService,
    CycleError,
    DependencyFailedError,
    DependencyNotRunningError,
    ProcessRunner,
    RestartPolicy,
    Runtime,
    Service,
    State,
    TaskRunner,
    ThreadRunner,
)


class Parked(AsyncService):
    """Parks on the loop; notes its teardown in *log*."""

    def __init__(
        self, name: str, log: list[str] | None = None, depends: tuple[str, ...] = ()
    ) -> None:
        self._lg = MagicMock()
        self._name = name
        self._log = log
        self._depends = list(depends)
        self.entered = threading.Event()

    @property
    def name(self) -> str:
        return self._name

    @property
    def depends_on(self) -> list[str]:
        return self._depends

    async def run(self) -> None:
        self.entered.set()
        await asyncio.Event().wait()

    def teardown(self) -> None:
        if self._log is not None:
            self._log.append(self._name)


class Blocking(Service):
    """Blocks its thread until stopping is set; notes its teardown in *log*."""

    def __init__(
        self, name: str, log: list[str], depends: tuple[str, ...] = ()
    ) -> None:
        self._lg = MagicMock()
        self._name = name
        self._log = log
        self._depends = list(depends)

    @property
    def name(self) -> str:
        return self._name

    @property
    def depends_on(self) -> list[str]:
        return self._depends

    def run(self) -> None:
        self.stopping.wait()

    def teardown(self) -> None:
        self._log.append(self._name)


class FailsOnRelease(AsyncService):
    """Each run parks until released, then fails; the run after *fails* runs parks."""

    def __init__(self, fails: int) -> None:
        self._lg = MagicMock()
        self._fails = fails
        self.runs = 0
        self.parked = threading.Event()
        self._release: asyncio.Event | None = None

    @property
    def name(self) -> str:
        return "fails"

    async def run(self) -> None:
        self.runs += 1
        self._release = asyncio.Event()
        self.parked.set()
        if self.runs > self._fails:
            await asyncio.Event().wait()
        await self._release.wait()
        self.parked.clear()
        raise RuntimeError(f"run {self.runs} failed")

    def release(self, rt: Runtime) -> None:
        """Let the parked run fail; call once parked is set."""
        assert self._release is not None
        rt._host.loop.call_soon_threadsafe(self._release.set)  # Private: the loop


class Spawner(AsyncService):
    """Derives a token from its own, as a service does for work it starts."""

    def __init__(self) -> None:
        self._lg = MagicMock()
        self.derived: object = None

    @property
    def name(self) -> str:
        return "spawner"

    async def run(self) -> None:
        self.derived = self.stopping.child()
        await asyncio.Event().wait()


class InProcess(Service):
    """Blocks in its subprocess until stopping is set."""

    def __init__(self) -> None:
        # A real logger: ProcessRunner configures the subprocess's from it
        self._lg = Logger(name="test")

    @property
    def name(self) -> str:
        return "in-process"

    def run(self) -> None:
        self.stopping.wait()


@pytest.fixture
def rt() -> Iterator[Runtime]:
    runtime = Runtime(MagicMock(), name="test-runtime")
    runtime.start()
    yield runtime
    runtime.stop()


def _wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    """Poll *condition* until it holds; False once *timeout* passes. For changes
    no event signals, such as a service leaving the runtime."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


class TestSpawn:
    def test_each_kind_gets_its_runner(self, rt):
        assert isinstance(rt.spawn(Parked("async")), TaskRunner)
        assert isinstance(rt.spawn(Blocking("thread", [])), ThreadRunner)
        isolated = rt.spawn(InProcess(), isolate=True)
        assert isinstance(isolated, ProcessRunner)
        rt.ready(isolated, timeout=30.0)

    def test_an_async_service_cannot_be_isolated(self, rt):
        with pytest.raises(ValueError, match="cannot run isolated"):
            rt.spawn(Parked("async"), isolate=True)
        assert rt.services == {}

    def test_a_name_runs_once(self, rt):
        rt.spawn(Parked("same"))
        with pytest.raises(ValueError, match="already"):
            rt.spawn(Parked("same"))

    def test_spawn_needs_a_running_runtime(self):
        runtime = Runtime(MagicMock())
        with pytest.raises(RuntimeError, match="not running"):
            runtime.spawn(Parked("early"))
        runtime.start()
        runtime.stop()
        with pytest.raises(RuntimeError, match="not running"):
            runtime.spawn(Parked("late"))


class TestDependencies:
    def test_a_service_spawned_before_its_dependency_waits_for_it(self, rt):
        api = rt.spawn(Parked("api", depends=("db",)))
        assert api.state == State.CREATED

        rt.spawn(Parked("db"))  # nobody waits on db's health: the runtime does

        rt.ready(api)
        assert api.state == State.RUNNING

    def test_a_dependency_that_never_comes_is_named(self, rt):
        api = rt.spawn(Parked("api", depends=("db",)))
        with pytest.raises(DependencyNotRunningError, match="'db'"):
            rt.ready(api, timeout=0.2)

    def test_a_cycle_is_refused(self, rt):
        rt.spawn(Parked("a", depends=("b",)))
        with pytest.raises(CycleError, match="b → a → b"):
            rt.spawn(Parked("b", depends=("a",)))
        assert list(rt.services) == ["a"]

    def test_waiters_fail_when_their_dependency_cannot_start(self, rt):
        class FailsSetup(Parked):
            def setup(self) -> None:
                raise RuntimeError("no setup")

        api = rt.spawn(Parked("api", depends=("db",)))
        web = rt.spawn(Parked("web", depends=("api",)))
        with pytest.raises(Exception, match="no setup"):
            rt.spawn(FailsSetup("db"))

        with pytest.raises(DependencyFailedError, match="'db'"):
            rt.ready(api)
        with pytest.raises(DependencyFailedError, match="'api'"):
            rt.ready(web)
        assert rt.services == {}

    @pytest.mark.parametrize("seed", range(20))
    def test_concurrent_spawns_in_any_order_start_each_once_after_its_dependencies(
        self, seed
    ):
        """Ten services, a dependency DAG between them, spawned from ten threads
        at once in a shuffled order."""
        graph = {
            "pg": (), "redis": (), "auth": ("pg",), "users": ("pg", "auth"),
            "cache": ("redis",), "api": ("users", "cache"), "jobs": ("pg", "redis"),
            "mail": ("jobs",), "web": ("api",), "admin": ("api", "jobs"),
        }  # fmt: skip
        started: list[str] = []
        services = [StartOrder(n, deps, started) for n, deps in graph.items()]
        random.Random(seed).shuffle(services)
        go = threading.Barrier(len(services))

        def spawn(svc: StartOrder) -> None:
            go.wait()
            rt.spawn(svc)

        with Runtime(MagicMock()) as rt:
            threads = [threading.Thread(target=spawn, args=(s,)) for s in services]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5.0)
            rt.ready(*rt.services.values(), timeout=10.0)

        assert sorted(started) == sorted(graph)  # each once
        for name, deps in graph.items():
            assert all(started.index(d) < started.index(name) for d in deps), started


class StartOrder(Parked):
    """Notes in *started* when it is started: setup() runs as the runtime starts
    it. Not run(): its task may not have begun when ready() returns."""

    def __init__(self, name: str, depends: tuple[str, ...], started: list[str]) -> None:
        super().__init__(name, depends=depends)
        self._started = started

    def setup(self) -> None:
        self._started.append(self.name)


class TestStop:
    def test_dependents_stop_before_what_they_depend_on(self):
        torn_down: list[str] = []
        with Runtime(MagicMock()) as rt:
            api = rt.spawn(Parked("api", torn_down, depends=("db", "cache")))
            rt.spawn(Blocking("cache", torn_down, depends=("db",)))
            rt.spawn(Parked("db", torn_down))
            rt.ready(api)
        assert torn_down == ["api", "cache", "db"]

    def test_stopping_the_runtime_stops_what_services_derived(self):
        spawner = Spawner()
        with Runtime(MagicMock()) as rt:
            rt.ready(rt.spawn(spawner))
            assert _wait_until(lambda: spawner.derived is not None)
        assert spawner.stopping.is_set()
        assert spawner.derived.is_set()

    def test_a_service_stopped_on_its_own_leaves_the_runtime(self, rt):
        runner = rt.spawn(Parked("one"))
        rt.ready(runner)
        runner.stop()
        assert "one" not in rt.services


class TestSupervision:
    def test_a_service_failing_while_running_is_restarted(self, rt):
        svc = FailsOnRelease(fails=1)
        runner = rt.spawn(svc, RestartPolicy(backoff=0.0))
        rt.ready(runner)
        assert svc.parked.wait(5.0)

        svc.release(rt)

        assert _wait_until(lambda: svc.runs == 2 and runner.state == State.RUNNING)
        assert rt.services == {"fails": runner}

    def test_a_service_with_no_restart_left_leaves_the_runtime(self, rt):
        svc = FailsOnRelease(fails=1)
        runner = rt.spawn(svc, RestartPolicy(restart_on_failure=False))
        other = rt.spawn(Parked("other"))
        rt.ready(runner, other)
        assert svc.parked.wait(5.0)

        svc.release(rt)

        assert _wait_until(lambda: "fails" not in rt.services)
        assert runner.state == State.FAILED
        assert other.state == State.RUNNING

    def test_a_service_failing_to_start_is_not_restarted(self, rt):
        class FailsSetup(Parked):
            def setup(self) -> None:
                raise RuntimeError("no setup")

        with pytest.raises(Exception, match="no setup"):
            rt.spawn(FailsSetup("broken"), RestartPolicy(backoff=0.0))
        assert rt.services == {}
