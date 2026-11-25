# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the Runtime: spawn, dependencies, stop order, supervision."""

from __future__ import annotations

import asyncio
import contextlib
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
    HealthTimeoutError,
    ProcessRunner,
    RestartPolicy,
    RunError,
    Runtime,
    Service,
    State,
    TaskRunner,
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
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def name(self) -> str:
        return "fails"

    async def run(self) -> None:
        self.runs += 1
        self._release = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        self.parked.set()
        if self.runs > self._fails:
            await asyncio.Event().wait()
        await self._release.wait()
        self.parked.clear()
        raise RuntimeError(f"run {self.runs} failed")

    def release(self) -> None:
        """Let the parked run fail; call once parked is set."""
        assert self._release is not None and self._loop is not None
        self._loop.call_soon_threadsafe(self._release.set)


class MeetsAt(Service):
    """Healthy only once its run() and every other one at *barrier* have met."""

    def __init__(self, name: str, barrier: threading.Barrier) -> None:
        self._lg = MagicMock()
        self._name = name
        self._barrier = barrier
        self._met = threading.Event()

    @property
    def name(self) -> str:
        return self._name

    def run(self) -> None:
        self._barrier.wait(timeout=5.0)  # the timeout is the failure path
        self._met.set()
        self.stopping.wait()

    def is_healthy(self) -> bool:
        return self._met.is_set()


class SetupGate:
    """Holds the first setup() that reaches it until released; notes them all."""

    def __init__(self) -> None:
        self.setups: list[str] = []
        self.blocked = threading.Event()
        self.release = threading.Event()
        self._first = threading.Lock()

    def enter(self, name: str) -> None:
        self.setups.append(name)
        if self._first.acquire(blocking=False):
            self.blocked.set()
            assert self.release.wait(5.0)  # the timeout is the failure path


class GatedSetup(Parked):
    """setup() passes through a SetupGate shared with others."""

    def __init__(self, name: str, depends: tuple[str, ...], gate: SetupGate) -> None:
        super().__init__(name, depends=depends)
        self._gate = gate

    def setup(self) -> None:
        self._gate.enter(self.name)


class FailsInProcess(Service):
    """Its run() fails in the subprocess at once; setup(), in the parent, fails
    from its second call on. Module level, so the spawn start method can
    pickle it."""

    def __init__(self) -> None:
        self._lg = Logger(name="test")
        self.setups = 0

    @property
    def name(self) -> str:
        return "fails-in-process"

    def setup(self) -> None:
        self.setups += 1
        if self.setups > 1:
            raise RuntimeError("no second setup")

    def run(self) -> None:
        raise RuntimeError("run fails")


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
        assert isinstance(rt.spawn(Blocking("thread", [])), TaskRunner)
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

    def test_a_runtime_starts_once(self):
        """Single use: not started again while running nor after stop(), and a
        stopped runtime takes no more services."""
        rt = Runtime(MagicMock(), name="once")
        rt.start()
        with pytest.raises(RuntimeError, match="started already"):
            rt.start()
        rt.stop()
        with pytest.raises(RuntimeError, match="started already"):
            rt.start()
        with pytest.raises(RuntimeError, match="not running"):
            rt.spawn(Parked("late"))

    def test_ready_on_a_service_never_healthy_times_out(self, rt):
        """ready() gives up on a service that runs but never reports healthy;
        the timeout is what is under test."""

        class NeverHealthy(Parked):
            def is_healthy(self) -> bool:
                return False

        runner = rt.spawn(NeverHealthy("sick"))
        with pytest.raises(HealthTimeoutError):
            rt.ready(runner, timeout=0.2)

    def test_independent_services_run_at_once(self, rt):
        """spawn() starts a service without waiting for its health, so services
        independent of each other run together: neither becomes healthy until
        both run()s have reached the barrier."""
        barrier = threading.Barrier(2)
        a = rt.spawn(MeetsAt("a", barrier))
        b = rt.spawn(MeetsAt("b", barrier))

        rt.ready(a, b, timeout=10.0)

        assert a.state == State.RUNNING and b.state == State.RUNNING


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

    def test_a_service_depending_on_itself_is_refused(self, rt):
        with pytest.raises(CycleError, match="a → a"):
            rt.spawn(Parked("a", depends=("a",)))
        assert rt.services == {}

    def test_the_spawn_that_closes_a_longer_cycle_is_refused(self, rt):
        rt.spawn(Parked("a", depends=("b",)))
        rt.spawn(Parked("b", depends=("c",)))
        with pytest.raises(CycleError, match="c → a → b → c"):
            rt.spawn(Parked("c", depends=("a",)))
        assert set(rt.services) == {"a", "b"}

    def test_a_diamond_is_no_cycle(self, rt):
        """d needs b and c, which both need a: a is reached twice, not a cycle."""
        d = rt.spawn(Parked("d", depends=("b", "c")))
        rt.spawn(Parked("b", depends=("a",)))
        rt.spawn(Parked("c", depends=("a",)))
        rt.spawn(Parked("a"))

        rt.ready(d)

        assert all(r.state == State.RUNNING for r in rt.services.values())

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

    def test_a_queued_waiter_whose_dependency_left_is_not_started(self, rt):
        """Waiters released together start one after another: one queued behind
        a slow setup() checks its dependencies again before it starts, and fails
        if one left meanwhile."""
        gate = SetupGate()
        a = rt.spawn(GatedSetup("a", ("d",), gate))
        b = rt.spawn(GatedSetup("b", ("d",), gate))
        d = rt.spawn(Parked("d"))  # RUNNING releases a and b
        assert gate.blocked.wait(5.0)
        first = gate.setups[0]
        queued = b if first == "a" else a

        d.stop()  # d leaves the runtime while the first waiter is in setup()
        assert "d" not in rt.services
        gate.release.set()

        with pytest.raises(DependencyFailedError, match="'d'"):
            rt.ready(queued, timeout=5.0)
        assert gate.setups == [first]

    def test_a_new_service_does_not_get_a_failure_of_one_with_its_name(self, rt):
        """A failure belongs to its runner: a service spawned after another of
        its name failed and left is not given that failure by ready()."""

        class FailsSetup(Parked):
            def setup(self) -> None:
                raise RuntimeError("no setup")

        rt.spawn(Parked("x", depends=("db",)))
        with pytest.raises(Exception, match="no setup"):
            rt.spawn(FailsSetup("db"))  # x fails and leaves, never ready()'d
        assert "x" not in rt.services

        again = rt.spawn(Parked("x"))
        rt.ready(again)

        assert again.state == State.RUNNING

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

        svc.release()

        assert _wait_until(lambda: svc.runs == 2 and runner.state == State.RUNNING)
        assert rt.services == {"fails": runner}

    def test_a_restart_failing_right_after_it_runs_is_restarted_again(self, rt):
        """The restarted service fails before the restart's own bookkeeping is
        done: that failure is not lost, the next attempt follows."""
        svc = FailsOnRelease(fails=2)
        runner = rt.spawn(svc, RestartPolicy(backoff=0.0))
        rt.ready(runner)
        assert svc.parked.wait(5.0)
        restarts = 0
        failed_again = threading.Event()

        def hook(_name: str, _old: State, new: State) -> None:
            nonlocal restarts
            if new == State.FAILED and svc.runs == 2:
                failed_again.set()
            if new == State.RUNNING:
                restarts += 1
                if restarts == 1:  # on the restart thread, before restart() returns
                    assert svc.parked.wait(5.0)
                    svc.release()
                    assert failed_again.wait(5.0)  # the timeout is the failure path

        runner.on_state_change(hook)
        svc.release()  # the first run fails: a restart follows

        assert _wait_until(lambda: svc.runs == 3 and runner.state == State.RUNNING)

    def test_a_service_with_no_restart_left_leaves_the_runtime(self, rt):
        svc = FailsOnRelease(fails=1)
        runner = rt.spawn(svc, RestartPolicy(restart_on_failure=False))
        other = rt.spawn(Parked("other"))
        rt.ready(runner, other)
        assert svc.parked.wait(5.0)

        svc.release()

        assert _wait_until(lambda: "fails" not in rt.services)
        assert runner.state == State.FAILED
        assert other.state == State.RUNNING

    def test_a_thread_service_failing_with_no_restart_left_is_torn_down(self, rt):
        """It leaves the runtime, which then no longer stops it: its runner
        tears it down when run() fails."""

        class FailsOnce(Service):
            def __init__(self) -> None:
                self._lg = MagicMock()
                self.torn_down = threading.Event()

            @property
            def name(self) -> str:
                return "fails"

            def run(self) -> None:
                raise RuntimeError("run fails")

            def teardown(self) -> None:
                self.torn_down.set()

        svc = FailsOnce()
        rt.spawn(svc, RestartPolicy(restart_on_failure=False))

        assert svc.torn_down.wait(5.0)  # the timeout is the failure path
        assert _wait_until(lambda: "fails" not in rt.services)

    def test_a_process_service_failing_its_last_restart_leaves_the_runtime(self, rt):
        """Its monitor's last restart fails in setup(): no attempt follows, so
        the service leaves the runtime instead of staying FAILED in it."""
        runner = rt.spawn(
            FailsInProcess(), RestartPolicy(max_retries=1, backoff=0.0), isolate=True
        )
        with contextlib.suppress(RunError):  # it may die before it is healthy
            rt.ready(runner, timeout=10.0)

        # The monitor checks once a second; the deadline is the failure path
        assert _wait_until(lambda: "fails-in-process" not in rt.services, 15.0)
        assert runner.state == State.FAILED

    def test_a_service_failing_to_start_is_not_restarted(self, rt):
        class FailsSetup(Parked):
            def setup(self) -> None:
                raise RuntimeError("no setup")

        with pytest.raises(Exception, match="no setup"):
            rt.spawn(FailsSetup("broken"), RestartPolicy(backoff=0.0))
        assert rt.services == {}


class TestRefusedAtStop:
    def test_a_waiter_refused_as_the_runtime_stops_learns_it_at_once(self, monkeypatch):
        """Its dependency runs, but stop() begins before the thread that would
        start it does: ready() reports the stop at once instead of timing out
        on a dependency that is running."""
        rt = Runtime(MagicMock(), name="refused")
        rt.start()
        real_helper = rt._helper
        stopper = threading.Thread(target=rt.stop)

        def helper(target: Callable[..., None], arg: object, *, name: str) -> None:
            if name.startswith("start-after-"):  # stop() lands right here
                stopper.start()
                assert _wait_until(lambda: rt._closing)  # Private: stop() began
            real_helper(target, arg, name=name)

        monkeypatch.setattr(rt, "_helper", helper)
        waiter = rt.spawn(Parked("waiter", depends=("d",)))
        rt.spawn(Parked("d"))  # its RUNNING releases the waiter

        began = time.monotonic()
        with pytest.raises(RunError, match="stopped first"):
            rt.ready(waiter, timeout=5.0)
        assert time.monotonic() - began < 5.0  # told, not timed out
        stopper.join(10.0)


class TestStopAndStart:
    def test_stop_waits_for_a_start_it_admitted(self, monkeypatch):
        """A start the runtime admitted before stop() began, but that has not
        reached runner.start() yet, is waited for and then stopped with the
        rest: no service runs on after stop() returns."""
        in_gap, release = threading.Event(), threading.Event()
        real_start = TaskRunner.start

        def gated_start(runner: TaskRunner) -> None:
            if runner.name == "late":  # between admission and runner.start()
                in_gap.set()
                assert release.wait(5.0)  # the timeout is the failure path
            real_start(runner)

        monkeypatch.setattr(TaskRunner, "start", gated_start)
        rt = Runtime(MagicMock(), name="gap")
        rt.start()
        spawned: list[TaskRunner] = []
        log: list[str] = []
        spawner = threading.Thread(
            target=lambda: spawned.append(rt.spawn(Blocking("late", log)))
        )
        spawner.start()
        assert in_gap.wait(5.0)

        stopper = threading.Thread(target=rt.stop)
        stopper.start()
        assert _wait_until(lambda: rt._closing)  # Private: stop() has begun
        release.set()
        stopper.join(10.0)
        spawner.join(10.0)

        runner = spawned[0]
        assert not runner.is_alive()
        assert runner.state == State.STOPPED
        assert log == ["late"]
