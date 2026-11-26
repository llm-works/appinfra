# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the Runtime: spawn, dependencies, stop order, supervision."""

from __future__ import annotations

import asyncio
import functools
import multiprocessing as mp
import random
import threading
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from appinfra.log import Logger
from appinfra.runtime import Chan
from appinfra.service import (
    AsyncService,
    CycleError,
    DependencyFailedError,
    DependencyNotRunningError,
    HealthTimeoutError,
    RestartPolicy,
    RunError,
    Runner,
    Runtime,
    Service,
    SetupError,
    State,
)
from appinfra.service.runtime.owner import GiveUp
from tests.helpers.service.runner import wait_until as _wait_until


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

    def __init__(
        self,
        name: str,
        depends: tuple[str, ...],
        gate: SetupGate,
        log: list[str] | None = None,
    ) -> None:
        super().__init__(name, log, depends=depends)
        self._gate = gate

    def setup(self) -> None:
        self._gate.enter(self.name)


class FailsInProcess(Service):
    """Healthy, its run() fails in its process once *go* is set; setup(), there
    too, fails from its second call on, counted across processes. Module
    level, so the spawn start method can pickle it."""

    def __init__(self) -> None:
        self._lg = Logger(name="test")
        ctx = mp.get_context("spawn")
        self.setups = ctx.Value("i", 0)
        self.go = ctx.Event()

    @property
    def name(self) -> str:
        return "fails-in-process"

    def setup(self) -> None:
        with self.setups.get_lock():
            self.setups.value += 1
            if self.setups.value > 1:
                raise RuntimeError("no second setup")

    def run(self) -> None:
        self.go.wait(30.0)  # the deadline is the failure path
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
        # A real logger: the runtime configures the subprocess's from it
        self._lg = Logger(name="test")

    @property
    def name(self) -> str:
        return "in-process"

    def run(self) -> None:
        self.stopping.wait()


class SetupFails(Service):
    """setup() raises. Module level, so the spawn start method can pickle it."""

    def __init__(self) -> None:
        self._lg = Logger(name="test")

    @property
    def name(self) -> str:
        return "setup-fails"

    def setup(self) -> None:
        raise RuntimeError("no database")

    def run(self) -> None:
        raise AssertionError("never run")


class HealthFails(Service):
    """Runs until stopping is set; is_healthy() raises. Module level, so the
    spawn start method can pickle it."""

    def __init__(self) -> None:
        self._lg = Logger(name="test")

    @property
    def name(self) -> str:
        return "health-fails"

    def run(self) -> None:
        self.stopping.wait()

    def is_healthy(self) -> bool:
        raise RuntimeError("no health")


class TestSpawn:
    def test_each_kind_runs(self, rt):
        """On the loop, on a thread, and in a process of its own."""
        runners = [
            rt.spawn(Parked("async")),
            rt.spawn(Blocking("thread", [])),
            rt.spawn(InProcess(), isolate=True),
        ]
        rt.ready(*runners, timeout=30.0)
        assert all(isinstance(r, Runner) for r in runners)
        assert {r.state for r in runners} == {State.RUNNING}

    def test_an_isolated_setup_error_reaches_ready(self, rt):
        """setup() fails in the service's own process: ready() raises that
        SetupError, as for a service in this one."""
        runner = rt.spawn(SetupFails(), isolate=True)
        with pytest.raises(SetupError, match="setup-fails: setup failed: no database"):
            rt.ready(runner, timeout=30.0)

    def test_an_isolated_launch_that_fails_fails_the_start(self, rt):
        """The service cannot be copied for its process: its start fails with
        the cause, and nothing of the launch is left behind."""

        class Uncopyable(Blocking):
            def __copy__(self) -> Uncopyable:
                raise RuntimeError("no copy")

        runner = rt.spawn(Uncopyable("uncopyable", []), isolate=True)
        with pytest.raises(RunError, match="no copy"):
            rt.ready(runner, timeout=10.0)
        assert runner.state == State.FAILED
        assert rt._owner._children == {}

    def test_an_async_service_cannot_be_isolated(self, rt):
        with pytest.raises(ValueError, match="cannot run isolated"):
            rt.spawn(Parked("async"), isolate=True)
        assert rt.services == {}

    def test_a_name_runs_once(self, rt):
        rt.spawn(Parked("same"))
        with pytest.raises(ValueError, match="already"):
            rt.spawn(Parked("same"))

    def test_a_refused_spawn_leaves_the_running_instance_stoppable(self, rt):
        """The same instance spawned again is refused, and its run keeps the
        token a stop reaches."""
        svc = Blocking("twice", [])
        runner = rt.spawn(svc)
        rt.ready(runner, timeout=5.0)
        with pytest.raises(ValueError, match="already"):
            rt.spawn(svc)

        rt.stop_service(runner, timeout=5.0)
        assert runner.state == State.STOPPED

    def test_a_runtime_not_started_has_no_services(self):
        """Read before start(): no task answers yet, and none is needed."""
        runtime = Runtime(MagicMock())
        seen: list[dict[str, Runner]] = []
        reader = threading.Thread(target=lambda: seen.append(runtime.services))
        reader.daemon = True  # a read that blocks must not keep the process up
        reader.start()
        reader.join(5.0)  # the deadline is the failure path
        assert seen == [{}]

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

    @pytest.mark.parametrize("isolate", [False, True], ids=["in-process", "isolated"])
    def test_a_health_check_that_raises_fails_the_start(self, rt, isolate):
        """The error ends the run, in its process too, so ready() fails with
        it rather than waiting out its timeout, which is the failure path."""
        runner = rt.spawn(HealthFails(), isolate=isolate)
        with pytest.raises(RunError, match="no health"):
            rt.ready(runner, timeout=15.0)
        assert runner.state == State.FAILED

    def test_ready_returns_while_a_hook_blocks_the_runtime(self, rt):
        """A state hook blocks the runtime's task: ready() still returns once
        its timeout and the short grace for giving up have passed."""

        class NeverHealthy(Parked):
            def is_healthy(self) -> bool:
                return False

        sick = rt.spawn(NeverHealthy("sick"))
        other = rt.spawn(Parked("other"))
        rt.ready(other, timeout=5.0)
        blocked, release = threading.Event(), threading.Event()

        def hook(name: str, old: State, new: State) -> None:
            if new == State.STOPPING:
                blocked.set()
                release.wait(10.0)

        other.on_state_change(hook)
        stopper = threading.Thread(target=rt.stop_service, args=(other, 10.0))
        stopper.start()
        errors: list[BaseException] = []

        def wait_ready() -> None:
            try:
                rt.ready(sick, timeout=0.2)
            except BaseException as e:
                errors.append(e)

        waiter = threading.Thread(target=wait_ready)
        try:
            assert blocked.wait(5.0)
            with patch("appinfra.service.runtime.runtime.GIVE_UP_GRACE", 0.05):
                waiter.start()
                waiter.join(5.0)  # the deadline is the failure path
                assert not waiter.is_alive()
            assert [type(e) for e in errors] == [HealthTimeoutError]
        finally:
            release.set()
            stopper.join(10.0)
            waiter.join(10.0)

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
        db = rt.spawn(FailsSetup("db"))
        with pytest.raises(SetupError, match="no setup"):
            rt.ready(db)

        with pytest.raises(DependencyFailedError, match="'db'"):
            rt.ready(api)
        with pytest.raises(DependencyFailedError, match="'api'"):
            rt.ready(web)
        assert rt.services == {}

    def test_a_waiter_whose_dependency_left_during_its_setup_does_not_run(self, rt):
        """Its dependencies are checked again once setup() returns: one left
        meanwhile, so it is torn down and fails without running."""
        gate = SetupGate()
        torn_down: list[str] = []
        waiter = rt.spawn(GatedSetup("waiter", ("d",), gate, torn_down))
        d = rt.spawn(Parked("d"))  # RUNNING starts the waiter
        assert gate.blocked.wait(5.0)  # the timeout is the failure path

        rt.stop_service(d)  # d leaves while the waiter is in setup()
        assert "d" not in rt.services
        gate.release.set()

        with pytest.raises(DependencyFailedError, match="'d'"):
            rt.ready(waiter, timeout=5.0)
        assert waiter.state == State.FAILED
        assert "waiter" in torn_down

    def test_a_new_service_does_not_get_a_failure_of_one_with_its_name(self, rt):
        """A failure belongs to its runner: a service spawned after another of
        its name failed and left is not given that failure by ready()."""

        class FailsSetup(Parked):
            def setup(self) -> None:
                raise RuntimeError("no setup")

        rt.spawn(Parked("x", depends=("db",)))
        db = rt.spawn(FailsSetup("db"))  # x fails and leaves, never ready()'d
        with pytest.raises(SetupError, match="no setup"):
            rt.ready(db)
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
        rt.stop_service(runner)
        assert runner.state == State.STOPPED
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

    def test_a_restarted_service_failing_again_is_restarted_again(self, rt):
        svc = FailsOnRelease(fails=2)
        runner = rt.spawn(svc, RestartPolicy(backoff=0.0))
        rt.ready(runner)
        assert svc.parked.wait(5.0)  # the timeouts are the failure path
        svc.release()  # the first run fails: a restart follows

        assert _wait_until(lambda: svc.runs == 2 and svc.parked.is_set())
        svc.release()  # and so does the second

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
        """Its run fails in its process once running, and its restart fails too:
        no attempt is left, so the service leaves the runtime instead of staying
        FAILED in it."""
        svc = FailsInProcess()
        runner = rt.spawn(svc, RestartPolicy(max_retries=1, backoff=0.0), isolate=True)
        rt.ready(runner, timeout=30.0)
        svc.go.set()

        # A process starts in seconds; the deadline is the failure path
        assert _wait_until(lambda: "fails-in-process" not in rt.services, 30.0)
        assert runner.state == State.FAILED
        assert svc.setups.value == 2  # restarted once

    def test_a_service_failing_to_start_is_not_restarted(self, rt):
        class FailsSetup(Parked):
            def setup(self) -> None:
                raise RuntimeError("no setup")

        runner = rt.spawn(FailsSetup("broken"), RestartPolicy(backoff=0.0))
        with pytest.raises(SetupError, match="no setup"):
            rt.ready(runner)
        assert rt.services == {}


class TestRefusedAtStop:
    def test_a_waiter_refused_as_the_runtime_stops_learns_it(self):
        """Its dependency never comes, and stop() begins: ready() reports the
        stop instead of a dependency still missing."""
        rt = Runtime(MagicMock(), name="refused")
        rt.start()
        waiter = rt.spawn(Parked("waiter", depends=("d",)))
        stopper = threading.Thread(target=rt.stop)
        stopper.start()

        with pytest.raises(RunError, match="stopped first"):
            rt.ready(waiter, timeout=5.0)
        stopper.join(10.0)


class SetsUpWork(Service):
    """setup() starts a worker on a child of its token, then is held until
    released; teardown() joins the worker and notes whether it ended."""

    def __init__(self, name: str, depends: tuple[str, ...] = ()) -> None:
        self._lg = MagicMock()
        self._name = name
        self._depends = list(depends)
        self.in_setup, self.release = threading.Event(), threading.Event()
        self.worker_ended: bool | None = None
        self.ran = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def depends_on(self) -> list[str]:
        return self._depends

    def setup(self) -> None:
        self._worker = threading.Thread(target=self.stopping.child().wait)
        self._worker.start()
        self.in_setup.set()
        self.release.wait(10.0)

    def run(self) -> None:
        self.ran = True
        self.stopping.wait()

    def teardown(self) -> None:
        self._worker.join(5.0)  # the deadline is the failure path
        self.worker_ended = not self._worker.is_alive()


class TestTeardownWithoutRun:
    """A service set up but never run is torn down with its token stopped, as
    after a run: work setup() started on it ends before teardown() waits."""

    def test_a_service_stopped_during_setup(self, rt):
        svc = SetsUpWork("stopped-in-setup")
        runner = rt.spawn(svc)
        assert svc.in_setup.wait(5.0)
        stopper = threading.Thread(target=rt.stop_service, args=(runner, 10.0))
        stopper.start()
        assert _wait_until(lambda: runner in rt._owner._stop_asked, 5.0)

        svc.release.set()
        stopper.join(10.0)
        assert svc.worker_ended is True

    def test_a_service_whose_dependency_left_during_setup(self, rt):
        dep = rt.spawn(Parked("dep"))
        rt.ready(dep, timeout=5.0)
        svc = SetsUpWork("needs-dep", depends=("dep",))
        runner = rt.spawn(svc)
        assert svc.in_setup.wait(5.0)
        rt.stop_service(dep, timeout=5.0)

        svc.release.set()
        with pytest.raises(DependencyFailedError):
            rt.ready(runner, timeout=10.0)
        assert svc.worker_ended is True

    def test_a_service_whose_dependency_is_stopping_once_set_up(self, rt):
        """Its dependency is still in the runtime but no longer RUNNING when
        setup() returns: the service never runs, and fails."""

        class SlowToStop(Service):
            """Its run() ends only when released, not on its token."""

            def __init__(self) -> None:
                self._lg = MagicMock()
                self.release = threading.Event()

            @property
            def name(self) -> str:
                return "dep"

            def run(self) -> None:
                self.release.wait(10.0)

        dep_svc = SlowToStop()
        dep = rt.spawn(dep_svc)
        rt.ready(dep, timeout=5.0)
        svc = SetsUpWork("needs-dep", depends=("dep",))
        runner = rt.spawn(svc)
        assert svc.in_setup.wait(5.0)
        stopper = threading.Thread(target=rt.stop_service, args=(dep, 10.0))
        stopper.start()
        try:
            assert _wait_until(lambda: dep.state == State.STOPPING, 5.0)
            svc.release.set()
            with pytest.raises(DependencyFailedError):
                rt.ready(runner, timeout=10.0)
            assert not svc.ran
            assert svc.worker_ended is True
        finally:
            dep_svc.release.set()
            stopper.join(10.0)


class FailsThenFailsSetup(Service):
    """Its first run fails once told to; every later setup() is held until
    released, then raises. Counts its setups."""

    def __init__(self) -> None:
        self._lg = MagicMock()
        self.setups = 0
        self.fail, self.in_setup, self.release = (threading.Event() for _ in range(3))

    @property
    def name(self) -> str:
        return "fails-then-fails-setup"

    def setup(self) -> None:
        self.setups += 1
        if self.setups > 1:
            self.in_setup.set()
            self.release.wait(10.0)
            raise RuntimeError("no setup")

    def run(self) -> None:
        self.fail.wait(10.0)
        raise RuntimeError("run fails")


class HeldUntilTornDown(Service):
    """A plain service whose run() blocks on what teardown() releases, not on
    its token, as on a socket teardown() closes; never healthy, or its check
    raises."""

    def __init__(self, name: str, check_raises: bool) -> None:
        self._lg = MagicMock()
        self._name = name
        self._check_raises = check_raises
        self.released = threading.Event()

    @property
    def name(self) -> str:
        return self._name

    def run(self) -> None:
        self.released.wait(10.0)  # the deadline is the failure path

    def teardown(self) -> None:
        self.released.set()

    def is_healthy(self) -> bool:
        if self._check_raises:
            raise RuntimeError("no health")
        return False


class TestFailedStartReleasesTheRun:
    """A start that fails ends a plain run the way a stop does: its teardown
    runs at once, which may be what releases the run."""

    def test_a_health_check_that_raises(self, rt):
        runner = rt.spawn(HeldUntilTornDown("raises", check_raises=True))
        with pytest.raises(RunError, match="no health"):
            rt.ready(runner, timeout=5.0)

    def test_a_ready_that_times_out(self, rt):
        svc = HeldUntilTornDown("never-healthy", check_raises=False)
        runner = rt.spawn(svc)
        with pytest.raises(HealthTimeoutError):
            rt.ready(runner, timeout=0.2)
        assert _wait_until(lambda: "never-healthy" not in rt.services, 5.0)
        assert runner.state == State.FAILED


class RestartSetupStartsWork(Service):
    """Its first run fails once told to; each restart's setup() starts a
    worker on a child of its token, then raises."""

    def __init__(self) -> None:
        self._lg = MagicMock()
        self.fail = threading.Event()
        self.setups = 0
        self.workers: list[threading.Thread] = []

    @property
    def name(self) -> str:
        return "restart-setup-starts-work"

    def setup(self) -> None:
        self.setups += 1
        if self.setups == 1:
            return
        worker = threading.Thread(target=self.stopping.child().wait, daemon=True)
        worker.start()
        self.workers.append(worker)
        raise RuntimeError("no setup")

    def run(self) -> None:
        self.fail.wait(10.0)
        raise RuntimeError("run fails")


class TestFailedRestartSetup:
    def test_each_failed_restart_setup_stops_the_work_it_started(self, rt):
        """Every restart attempt whose setup() fails has its token ended,
        the ones followed by another attempt too."""
        svc = RestartSetupStartsWork()
        runner = rt.spawn(svc, RestartPolicy(max_retries=2, backoff=0.0))
        rt.ready(runner, timeout=5.0)
        svc.fail.set()
        assert _wait_until(lambda: svc.name not in rt.services, 5.0)

        assert len(svc.workers) == 2
        for worker in svc.workers:
            worker.join(5.0)  # the deadline is the failure path
        assert [w.is_alive() for w in svc.workers] == [False, False]


class FailsOnceToldTo(Service):
    """No setup() of its own; its run fails once told to. Counts its runs."""

    def __init__(self, name: str, depends: tuple[str, ...]) -> None:
        self._lg = MagicMock()
        self._name = name
        self._depends = list(depends)
        self.fail = threading.Event()
        self.runs = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def depends_on(self) -> list[str]:
        return self._depends

    def run(self) -> None:
        self.runs += 1
        self.fail.wait(10.0)
        raise RuntimeError("run fails")


class TestRestartNeedsItsDependencies:
    def test_a_restart_with_a_dependency_down_does_not_run(self, rt):
        """Its dependency left while it ran; when it fails, its restart finds
        the dependency down: the attempt fails instead of running, and with no
        attempt left the service leaves."""
        db = rt.spawn(Parked("db"))
        api_svc = FailsOnceToldTo("api", depends=("db",))
        api = rt.spawn(api_svc, RestartPolicy(max_retries=1, backoff=0.0))
        rt.ready(api, timeout=5.0)
        rt.stop_service(db, timeout=5.0)

        api_svc.fail.set()
        assert _wait_until(lambda: "api" not in rt.services, 5.0)
        assert api_svc.runs == 1
        assert api.state == State.FAILED
        assert isinstance(api.exception, DependencyFailedError)


class TestStopDuringRestart:
    def test_a_stop_during_a_restart_setup_that_fails_is_answered(self, rt):
        """stop_service() lands while a restart is in setup(), which then
        raises: the stop returns, and no further restart follows."""
        svc = FailsThenFailsSetup()
        runner = rt.spawn(svc, RestartPolicy(max_retries=3, backoff=0.0))
        rt.ready(runner, timeout=5.0)
        svc.fail.set()
        assert svc.in_setup.wait(5.0)  # the restart's setup()
        errors: list[BaseException] = []

        def stop() -> None:
            try:
                rt.stop_service(runner, timeout=5.0)
            except BaseException as e:
                errors.append(e)

        stopper = threading.Thread(target=stop)
        stopper.start()
        assert _wait_until(lambda: runner in rt._owner._stop_asked, 5.0)
        svc.release.set()
        stopper.join(10.0)

        assert errors == []
        assert svc.setups == 2
        assert "fails-then-fails-setup" not in rt.services


class TestReadyExpiresASetup:
    def test_a_service_given_up_on_during_setup_never_runs(self, rt):
        """ready() times out while setup() runs: the start has failed for its
        caller, so once set up the service is torn down and fails instead of
        running unobserved."""
        svc = SetsUpWork("slow-setup")
        runner = rt.spawn(svc)
        assert svc.in_setup.wait(5.0)
        with pytest.raises(HealthTimeoutError):
            rt.ready(runner, timeout=0.2)

        svc.release.set()
        assert _wait_until(lambda: "slow-setup" not in rt.services, 5.0)
        assert not svc.ran
        assert svc.worker_ended is True
        assert runner.state == State.FAILED


class TestForeignRunners:
    """A runner one runtime spawned, passed to another: the other refuses it
    and leaves it as it is. Only its own runtime moves its state."""

    @pytest.fixture
    def other(self) -> Iterator[Runtime]:
        other = Runtime(MagicMock(), name="other")
        other.start()
        yield other
        other.stop(timeout=10.0)

    def test_ready_refuses_a_runner_of_another_runtime(self, rt, other):
        runner = other.spawn(Parked("theirs"))
        other.ready(runner, timeout=5.0)

        with pytest.raises(ValueError, match="not a service of runtime"):
            rt.ready(runner, timeout=5.0)

    def test_giving_up_leaves_a_runner_of_another_runtime_starting(self, rt, other):
        """A ready() that timed out gives up on its runner; on a runner of
        another runtime it ends nothing."""

        class NeverHealthy(Parked):
            def is_healthy(self) -> bool:
                return False

        runner = other.spawn(NeverHealthy("theirs"))
        assert _wait_until(lambda: runner.state == State.STARTING, 5.0)

        with pytest.raises(ValueError, match="not a service of runtime"):
            rt._ask(functools.partial(GiveUp, runner, Chan(1)))
        assert runner.state == State.STARTING


class TestStopAndStart:
    def test_stop_waits_for_a_setup_under_way(self):
        """A service in setup() when stop() begins is waited for, then torn
        down and stopped without running: no service runs on after stop()
        returns."""
        in_setup, release = threading.Event(), threading.Event()

        class GatedBlocking(Blocking):
            def setup(self) -> None:
                in_setup.set()
                assert release.wait(5.0)  # the timeout is the failure path

        rt = Runtime(MagicMock(), name="gap")
        rt.start()
        log: list[str] = []
        runner = rt.spawn(GatedBlocking("late", log))
        assert in_setup.wait(5.0)

        stopper = threading.Thread(target=rt.stop)
        stopper.start()
        # Private: the runtime's task has taken the stop, so setup() ends after it
        assert _wait_until(lambda: rt._owner._closing)
        release.set()
        stopper.join(10.0)

        assert not runner.is_alive()
        assert runner.state == State.STOPPED
        assert log == ["late"]
