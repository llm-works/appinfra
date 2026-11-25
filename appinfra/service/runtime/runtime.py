# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runtime: spawns services on the runners their kinds need, in dependency order."""

from __future__ import annotations

import atexit
import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any

from ...log import Logger
from ..base import AsyncService, Service
from ..errors import (
    CycleError,
    DependencyFailedError,
    DependencyNotRunningError,
    RunError,
)
from ..state import RestartPolicy, State
from ..stop import StopToken
from .loop import LoopHost
from .process import ProcessRunner
from .runner import Runner
from .thread import ThreadRunner

# States a service leaves the runtime in, unless a restart is under way
_ENDED = (State.DONE, State.STOPPED, State.FAILED)


def _restarted_by_monitor(runner: Runner) -> bool:
    """True for a process service its runner's monitor may still restart: its
    FAILED and the STOPPED of a restart do not end it. stop() ends the monitor
    first, so a service stopped on purpose is not kept."""
    return (
        isinstance(runner, ProcessRunner)
        and runner.monitoring
        and runner.restart_pending
    )


class Runtime:
    """Runs services: spawn() takes each, in any order and from any thread, and
    starts it on the runner its kind needs once its dependencies run.

    - AsyncService: a task on the runtime's event loop (a LoopHost), shared by
      every async service, so one waiting on an await holds no thread
    - any other Service: a thread of its own
    - isolate=True: a process of its own; refused for an AsyncService, which
      runs on the loop

    A service whose ``depends_on`` are all RUNNING starts at once; any other
    waits (its runner stays CREATED) and starts as soon as the last of them
    reaches RUNNING. The runtime waits for the health of a service that others
    wait on, so the chain moves on without ready(). A spawn that would close a
    dependency cycle is refused; a service waiting on one that leaves the
    runtime fails with DependencyFailedError. stop() stops services in reverse
    start order: dependents before what they depend on.

    Every service's stopping token derives from the runtime's. A service under a
    thread or the loop that fails while running is restarted per its policy,
    after the policy's backoff on a loop timer. A process service is restarted
    by its runner's own monitor. A service that ends, is stopped, or fails with
    no restart left leaves the runtime.

    Example:
        with Runtime(lg) as rt:
            api = rt.spawn(Api(lg))            # Api.depends_on == ["database"]
            rt.spawn(Indexer(lg), isolate=True)
            rt.spawn(Database(lg, cfg))        # api starts once this runs
            rt.ready(api)
    """

    def __init__(self, lg: Logger, name: str = "runtime") -> None:
        """A runtime not yet started; *name* names its event loop's thread."""
        self._lg = lg
        self.name = name
        self._host = LoopHost(name=name)
        self._root = StopToken()
        self._lock = threading.Lock()  # guards everything below
        self._runners: dict[str, Runner] = {}  # every service, by name
        self._started: dict[str, None] = {}  # in start order, for stop()
        self._pending: set[str] = set()  # waiting for dependencies
        self._waiters: dict[str, set[str]] = {}  # dependency -> pending waiting on it
        # Set once a pending service starts or fails; read by ready()
        self._start_events: dict[str, threading.Event] = {}
        self._failures: dict[str, BaseException] = {}  # failed before starting
        self._watched: set[str] = set()  # services whose health a helper waits for
        self._restarting: set[str] = set()  # restart armed or under way
        self._restart_threads: set[threading.Thread] = set()
        self._helpers: set[threading.Thread] = set()  # starts and health watches
        self._started_runtime = False
        self._closing = False
        # One bound method for every runner's hooks, not one each
        self._hook = self._on_state

    @property
    def services(self) -> dict[str, Runner]:
        """The services in the runtime by name, waiting ones included."""
        with self._lock:
            return dict(self._runners)

    def start(self) -> None:
        """Start the runtime's event loop.

        Raises:
            RuntimeError: If the runtime was started already.
        """
        if self._started_runtime:
            raise RuntimeError(f"runtime '{self.name}' was started already")
        self._host.start()
        self._started_runtime = True
        # Its threads are daemons, ended unwound at exit: a runtime left running
        # is stopped first, so its services' teardown() runs
        atexit.register(self._atexit_stop)

    def _atexit_stop(self) -> None:
        """At interpreter exit: stop a runtime nothing stopped."""
        try:
            self.stop()
        except Exception as e:
            self._lg.warning("runtime stop at exit failed", extra={"exception": e})

    # -- spawn --------------------------------------------------------------

    def spawn(
        self,
        service: Service,
        policy: RestartPolicy | None = None,
        *,
        isolate: bool = False,
    ) -> Runner:
        """Take *service*: start it now if its dependencies run, else once they
        do. Returns its runner. A service started now runs setup() on the
        calling thread; ready() waits until it is healthy.

        Raises:
            RuntimeError: If the runtime is not running.
            ValueError: If a service of the same name is in the runtime, or
                *isolate* is asked for an AsyncService.
            CycleError: If its dependencies lead back to it.
            SetupError, RunError: If a service started now fails to start.
        """
        runner = self._runner_for(service, policy, isolate)
        runner.on_state_change(self._hook)
        with self._lock:
            self._check_spawn(runner.service)
            self._runners[runner.name] = runner
            start_now = self._dependencies_run(runner.service)
            if not start_now:
                self._wait(runner.service)
        if start_now:
            self._start(runner, raise_errors=True)
        else:
            self._watch_dependencies(runner.service)
        return runner

    def ready(self, *runners: Runner, timeout: float = 30.0) -> None:
        """Wait until every one of *runners* has started and is healthy,
        *timeout* seconds in all.

        Raises:
            DependencyNotRunningError: If one still waits for a dependency.
            DependencyFailedError: If a dependency of one left the runtime first.
            RunError: If one exits while starting.
            HealthTimeoutError: If one is not healthy in time.
        """
        deadline = time.monotonic() + timeout
        for runner in runners:
            self._await_start(runner, deadline)
            runner.wait_healthy(timeout=max(0.0, deadline - time.monotonic()))

    def _await_start(self, runner: Runner, deadline: float) -> None:
        """Wait until a pending *runner* has started; raise why it did not."""
        with self._lock:
            event = self._start_events.get(runner.name)
        if event is not None and not event.wait(max(0.0, deadline - time.monotonic())):
            raise DependencyNotRunningError(runner.name, self._missing(runner))
        with self._lock:
            failure = self._failures.pop(runner.name, None)
        if failure is not None:
            raise failure

    def _missing(self, runner: Runner) -> str:
        """The first dependency of *runner* that is not running."""
        with self._lock:
            for dependency in runner.service.depends_on:
                dep = self._runners.get(dependency)
                if dep is None or dep.state != State.RUNNING:
                    return dependency
        return ", ".join(runner.service.depends_on)

    def _runner_for(
        self, service: Service, policy: RestartPolicy | None, isolate: bool
    ) -> Runner:
        """The runner *service* needs, its token derived from the runtime's."""
        if isinstance(service, AsyncService):
            if isolate:
                raise ValueError(
                    f"async service '{service.name}' cannot run isolated: an async "
                    "service runs on the runtime's event loop"
                )
            return self._host.runner(service, policy, parent=self._root)
        if isolate:
            return ProcessRunner(service, policy, parent=self._root)
        return ThreadRunner(service, policy, parent=self._root)

    def _check_spawn(self, service: Service) -> None:
        """Refuse a spawn the runtime cannot take; called under the lock."""
        if not self._started_runtime or self._closing:
            raise RuntimeError(f"runtime '{self.name}' is not running")
        if service.name in self._runners:
            raise ValueError(f"service '{service.name}' is in the runtime already")
        cycle = self._cycle(service)
        if cycle is not None:
            raise CycleError(cycle)

    def _cycle(self, service: Service) -> list[str] | None:
        """The services a dependency cycle through *service* would pass, if its
        dependencies lead back to it through the runtime's; under the lock."""
        stack = [(dep, [service.name, dep]) for dep in service.depends_on]
        seen: set[str] = set()
        while stack:
            name, path = stack.pop()
            if name == service.name:
                return path[:-1]
            if name in seen or name not in self._runners:
                continue
            seen.add(name)
            deps = self._runners[name].service.depends_on
            stack.extend((dep, [*path, dep]) for dep in deps)
        return None

    def _dependencies_run(self, service: Service) -> bool:
        """True if every dependency of *service* is RUNNING; under the lock."""
        return all(
            dep in self._runners and self._runners[dep].state == State.RUNNING
            for dep in service.depends_on
        )

    def _wait(self, service: Service) -> None:
        """Record *service* as waiting for its dependencies; under the lock."""
        self._pending.add(service.name)
        self._start_events[service.name] = threading.Event()
        for dependency in service.depends_on:
            self._waiters.setdefault(dependency, set()).add(service.name)

    def _unindex(self, name: str) -> None:
        """Take *name* out of the waiters of its dependencies; under the lock."""
        for dependency in self._runners[name].service.depends_on:
            waiters = self._waiters.get(dependency)
            if waiters is not None:
                waiters.discard(name)
                if not waiters:
                    del self._waiters[dependency]

    # -- start --------------------------------------------------------------

    def _start(self, runner: Runner, *, raise_errors: bool) -> None:
        """Start *runner*. A failure is raised to spawn()'s caller, or kept for
        ready() when the runtime started it on its own."""
        with self._lock:
            if self._closing:
                return
            self._started[runner.name] = None
        try:
            runner.start()
        except BaseException as e:
            if raise_errors:
                self._forget(runner)
                raise
            self._fail_start(runner, e)
            return
        if isinstance(runner, ProcessRunner):
            runner.start_monitor()
        self._signal_start(runner.name)
        self._watch_if_awaited(runner)

    def _fail_start(self, runner: Runner, error: BaseException) -> None:
        """Record why a service the runtime started on its own failed to."""
        self._lg.warning(
            "service failed to start",
            extra={"service": runner.name, "exception": error},
        )
        with self._lock:
            self._failures[runner.name] = error
        self._signal_start(runner.name)
        self._forget(runner)

    def _signal_start(self, name: str) -> None:
        """Wake ready() calls waiting for *name* to start."""
        with self._lock:
            event = self._start_events.pop(name, None)
        if event is not None:
            event.set()

    def _start_waiters(self, name: str) -> None:
        """Start the services waiting on *name* whose dependencies now all run.
        Each is taken out of the pending set under the lock, so two dependencies
        reaching RUNNING at once start it once."""
        with self._lock:
            if self._closing:
                return
            startable = [
                w
                for w in self._waiters.get(name, ())
                if w in self._pending
                and self._dependencies_run(self._runners[w].service)
            ]
            for waiter in startable:
                self._pending.discard(waiter)
                self._unindex(waiter)
            runners = [self._runners[w] for w in startable]
        if runners:
            # Not on this thread: the hook runs on whatever thread moved the
            # dependency, the event loop's included, and setup() may block
            self._helper(self._start_all, runners, name=f"start-after-{name}")

    def _start_all(self, runners: list[Runner]) -> None:
        """Helper thread: start *runners*, each once its turn comes."""
        for runner in runners:
            self._start(runner, raise_errors=False)

    # -- health watches -----------------------------------------------------

    def _watch_dependencies(self, service: Service) -> None:
        """Watch the health of the started dependencies a new waiter waits on."""
        with self._lock:
            runners = [
                self._runners[dep]
                for dep in service.depends_on
                if dep in self._started
                and dep not in self._watched
                and self._runners[dep].state == State.STARTING
            ]
            self._watched.update(r.name for r in runners)
        for runner in runners:
            self._helper(self._watch, runner, name=f"health-{runner.name}")

    def _watch_if_awaited(self, runner: Runner) -> None:
        """Watch *runner*'s health if a service waits on it: its RUNNING is what
        starts them, and only a health wait moves a runner to RUNNING."""
        with self._lock:
            awaited = bool(self._waiters.get(runner.name))
            watch = awaited and runner.name not in self._watched
            if watch:
                self._watched.add(runner.name)
        if watch:
            self._helper(self._watch, runner, name=f"health-{runner.name}")

    def _watch(self, runner: Runner) -> None:
        """Helper thread: wait for *runner*'s health. A failure moves it to
        FAILED, which fails what waits on it."""
        try:
            runner.wait_healthy()
        except Exception as e:
            # A watch ended by stop() is no failure
            if not self._closing:
                self._lg.warning(
                    "service did not become healthy",
                    extra={"service": runner.name, "exception": e},
                )
        finally:
            with self._lock:
                self._watched.discard(runner.name)

    def _helper(self, target: Callable[..., None], arg: Any, *, name: str) -> None:
        """Run *target*(*arg*) on a daemon thread that stop() waits for. It
        starts under the lock, so stop() never finds it in _helpers unstarted,
        which join() refuses; the thread takes the lock only once *target* ran."""
        thread = threading.Thread(
            target=self._run_helper, args=(target, arg), name=name, daemon=True
        )
        with self._lock:
            if self._closing:
                return
            self._helpers.add(thread)
            thread.start()

    def _run_helper(self, target: Callable[..., None], arg: Any) -> None:
        try:
            target(arg)
        finally:
            with self._lock:
                self._helpers.discard(threading.current_thread())

    # -- state hook, leaving the runtime ------------------------------------

    def _on_state(self, name: str, old: State, new: State) -> None:
        """Every runner's state hook: start what waited on a service that now
        runs, arm a restart for one that failed while running, and take an
        ended one out of the runtime."""
        if new == State.RUNNING:
            self._start_waiters(name)
            return
        with self._lock:
            runner = self._runners.get(name)
            if runner is None or new not in _ENDED or name in self._restarting:
                return
            if new != State.DONE and _restarted_by_monitor(runner):
                return
            restart = (
                new == State.FAILED
                and old == State.RUNNING
                and not isinstance(runner, ProcessRunner)
                and runner.can_restart
                and not self._closing
            )
            if restart:
                self._restarting.add(name)
        if restart:
            self._arm_restart(runner)
        else:
            self._forget(runner)

    def _forget(self, runner: Runner) -> None:
        """Take *runner* out of the runtime; the services still waiting on it
        fail, as it will not run for them."""
        with self._lock:
            if self._runners.get(runner.name) is not runner:
                return
            if runner.name in self._pending:
                self._pending.discard(runner.name)
                self._unindex(runner.name)
            waiting = [
                self._runners[w]
                for w in self._waiters.pop(runner.name, ())
                if w in self._pending
            ]
            del self._runners[runner.name]
            self._started.pop(runner.name, None)
            self._restarting.discard(runner.name)
        for waiter in waiting:
            self._abandon(waiter, DependencyFailedError(waiter.name, runner.name))

    def _abandon(self, runner: Runner, error: BaseException) -> None:
        """Fail a waiting service that can no longer start; its FAILED takes it
        out of the runtime, and what waits on it in turn."""
        with self._lock:
            self._failures[runner.name] = error
        self._signal_start(runner.name)
        runner._transition(State.FAILED)  # Never started: CREATED -> FAILED

    # -- restarts -----------------------------------------------------------

    def _arm_restart(self, runner: Runner) -> None:
        """Set a loop timer for *runner*'s restart, after its policy's backoff."""
        delay = runner.restart_delay
        try:
            self._host.loop.call_soon_threadsafe(
                lambda: self._host.loop.call_later(delay, self._launch_restart, runner)
            )
        except RuntimeError:  # The loop is gone: the runtime is stopping
            self._forget(runner)

    def _launch_restart(self, runner: Runner) -> None:
        """On the loop, once the backoff has passed: restart *runner* on a thread
        of its own, as a restart blocks until the service is healthy."""
        with self._lock:
            if self._closing:
                self._restarting.discard(runner.name)
                return
            # A daemon: a restart that hangs must not hold the interpreter's exit
            thread = threading.Thread(
                target=self._restart,
                args=(runner,),
                name=f"restart-{runner.name}",
                daemon=True,
            )
            self._restart_threads.add(thread)
            # Under the lock, as in _helper(): stop() joins what it finds here
            thread.start()

    def _restart(self, runner: Runner) -> None:
        """Restart thread: one attempt; if it fails, arm the next or let it go."""
        try:
            restarted = runner.restart()
        finally:
            with self._lock:
                self._restart_threads.discard(threading.current_thread())
                closing = self._closing
        if restarted:
            with self._lock:
                self._restarting.discard(runner.name)
        elif runner.can_restart and not closing:
            self._arm_restart(runner)
        else:
            self._forget(runner)

    # -- stop ---------------------------------------------------------------

    def stop(self, timeout: float = 5.0) -> None:
        """Stop every started service, in reverse start order, then the loop.

        Restarts under way are waited for first; nothing new starts. Each
        service gets up to *timeout* seconds to stop; a failure to stop one is
        logged and the rest stop regardless. A service still waiting for its
        dependencies never starts: ready() reports it.
        """
        with self._lock:
            if not self._started_runtime or self._closing:
                return
            self._closing = True
            restarts = list(self._restart_threads)
        atexit.unregister(self._atexit_stop)
        for thread in restarts:
            thread.join(timeout)
        for runner in self._stop_order():
            self._stop_one(runner, timeout)
        with self._lock:
            helpers = list(self._helpers)
        for thread in helpers:
            thread.join(timeout)
        self._root.stop()
        self._host.stop(timeout)

    def _stop_order(self) -> list[Runner]:
        """The started services, last started first; the pending ones are told
        they will not start."""
        with self._lock:
            runners = [self._runners[n] for n in reversed(self._started)]
            for name in self._pending:
                self._failures[name] = RunError(name, "the runtime stopped first")
                event = self._start_events.pop(name, None)
                if event is not None:
                    event.set()
        return runners

    def _stop_one(self, runner: Runner, timeout: float) -> None:
        """Stop *runner*; a failure is logged, not raised."""
        try:
            runner.stop(timeout)
        except Exception as e:
            self._lg.warning(
                "service stop failed", extra={"service": runner.name, "exception": e}
            )

    def __enter__(self) -> Runtime:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
