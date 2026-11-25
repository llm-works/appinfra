# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runtime: spawns each service on the runner its kind needs, and supervises it."""

from __future__ import annotations

import threading
import time
from types import TracebackType

from ...log import Logger
from ..base import AsyncService, Service
from ..errors import DependencyNotRunningError
from ..state import RestartPolicy, State
from ..stop import StopToken
from .loop import LoopHost
from .process import ProcessRunner
from .runner import Runner
from .thread import ThreadRunner

# States a service leaves the runtime's table in, unless a restart is under way
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
    """Runs services: spawn() starts each at once, on the runner its kind needs.

    - AsyncService: a task on the runtime's event loop (a LoopHost), shared by
      every async service, so one waiting on an await holds no thread
    - any other Service: a thread of its own
    - isolate=True: a process of its own (not yet for an AsyncService)

    spawn() returns the service's runner, its handle: state, health, stop().
    Services spawn in the order their dependencies need: a service's
    ``depends_on`` names must be running when it is spawned, and ready() waits
    until spawned services are healthy, several at once. stop() stops them in
    reverse spawn order, dependents before what they depend on.

    Every service's stopping token derives from the runtime's. A service under a
    thread or the loop that fails while running is restarted per its policy:
    after the policy's backoff on a loop timer, with no thread waiting it out.
    A process service is restarted by its runner's own monitor. A service that
    ends, is stopped, or fails with no restart left leaves the runtime.

    Example:
        with Runtime(lg) as rt:
            db = rt.spawn(Database(lg, cfg))
            rt.ready(db)
            api = rt.spawn(Api(lg))          # Api.depends_on == ["database"]
            rt.spawn(Indexer(lg), isolate=True)
            rt.ready(api)
            ...
    """

    def __init__(self, lg: Logger, name: str = "runtime") -> None:
        """A runtime not yet started; *name* names its event loop's thread."""
        self._lg = lg
        self.name = name
        self._host = LoopHost(name=name)
        self._root = StopToken()
        # Guards the tables below and _closing, from any thread
        self._lock = threading.Lock()
        # Spawned services by name; insertion order is spawn order
        self._runners: dict[str, Runner] = {}
        # Names of services with a restart armed or under way
        self._restarting: set[str] = set()
        self._restart_threads: set[threading.Thread] = set()
        self._started = False
        self._closing = False
        # One bound method for every runner's hooks, not one each
        self._hook = self._on_state

    @property
    def services(self) -> dict[str, Runner]:
        """The services in the runtime by name, in spawn order."""
        with self._lock:
            return dict(self._runners)

    def start(self) -> None:
        """Start the runtime's event loop.

        Raises:
            RuntimeError: If the runtime was started already.
        """
        if self._started:
            raise RuntimeError(f"runtime '{self.name}' was started already")
        self._host.start()
        self._started = True

    def spawn(
        self,
        service: Service,
        policy: RestartPolicy | None = None,
        *,
        isolate: bool = False,
    ) -> Runner:
        """Start *service* now on the runner its kind needs; returns the runner.

        It returns once the service's work has begun; ready() waits until it is
        healthy. setup() runs on the calling thread.

        Raises:
            RuntimeError: If the runtime is not running.
            ValueError: If a service of the same name is in the runtime, or
                *isolate* is asked for an AsyncService.
            DependencyNotRunningError: If a name in ``depends_on`` is not running.
            SetupError, RunError: If the service fails to start.
        """
        runner = self._runner_for(service, policy, isolate)
        with self._lock:
            self._check_spawn(runner.service)
            self._runners[runner.name] = runner
        runner.on_state_change(self._hook)
        try:
            runner.start()
        except BaseException:
            self._forget(runner)
            raise
        if isinstance(runner, ProcessRunner):
            runner.start_monitor()
        return runner

    def ready(self, *runners: Runner, timeout: float = 30.0) -> None:
        """Wait until every one of *runners* is healthy, *timeout* seconds in all.

        Raises:
            RunError: If a service exits while starting.
            HealthTimeoutError: If one is not healthy in time.
        """
        deadline = time.monotonic() + timeout
        for runner in runners:
            runner.wait_healthy(timeout=max(0.0, deadline - time.monotonic()))

    def stop(self, timeout: float = 5.0) -> None:
        """Stop every service, in reverse spawn order, then the event loop.

        Restarts under way are waited for first; no new one begins. Each
        service gets up to *timeout* seconds to stop; a failure to stop one is
        logged and the rest stop regardless.
        """
        with self._lock:
            if not self._started or self._closing:
                return
            self._closing = True
            threads = list(self._restart_threads)
            runners = list(reversed(self._runners.values()))
        for thread in threads:
            thread.join(timeout)
        for runner in runners:
            self._stop_one(runner, timeout)
        self._root.stop()
        self._host.stop(timeout)

    def _stop_one(self, runner: Runner, timeout: float) -> None:
        """Stop *runner*; a failure is logged, not raised."""
        try:
            runner.stop(timeout)
        except Exception as e:
            self._lg.warning(
                "service stop failed", extra={"service": runner.name, "exception": e}
            )

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
        if not self._started or self._closing:
            raise RuntimeError(f"runtime '{self.name}' is not running")
        if service.name in self._runners:
            raise ValueError(f"service '{service.name}' is in the runtime already")
        for dependency in service.depends_on:
            runner = self._runners.get(dependency)
            if runner is None or runner.state != State.RUNNING:
                raise DependencyNotRunningError(service.name, dependency)

    def _forget(self, runner: Runner) -> None:
        """Take *runner* out of the runtime, if it is still the one under its name."""
        with self._lock:
            if self._runners.get(runner.name) is runner:
                del self._runners[runner.name]
            self._restarting.discard(runner.name)

    def _on_state(self, name: str, old: State, new: State) -> None:
        """Every runner's state hook: arm a restart for a service that failed
        while running, and take an ended one out of the runtime."""
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
