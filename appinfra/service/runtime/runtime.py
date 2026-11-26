# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runtime: runs services as appinfra.runtime tasks, in dependency order."""

from __future__ import annotations

import atexit
import contextlib
import functools
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any

from ...log import Logger
from ...runtime import Chan, ChanClosedError, StoppedError, StopToken, Task
from ...runtime import Runtime as Tasks
from ...runtime import task_id as current_task_id
from ..base import AsyncService, Service
from ..errors import DependencyNotRunningError, HealthTimeoutError, RunError
from ..state import RestartPolicy
from .owner import UP, GiveUp, Owner, Ready, Services, Spawn, Stop, StopService
from .runner import Runner

# Seconds a ready() that timed out waits for the runtime to take its giving
# up, and to name a dependency still missing. The runtime's task answers at
# once unless a state hook blocks it; the giving up is queued either way.
GIVE_UP_GRACE = 1.0


class Runtime:
    """Runs services: spawn() takes each, in any order and from any thread, and
    starts it once its dependencies run.

    Each step of a service is a task on the appinfra.runtime Runtime this one
    owns: its setup() and teardown() on threads, its run on the event loop (an
    AsyncService), on a thread (any other service), or in a process of its own
    (isolate=True), and its health checks. One task of the runtime's own owns
    all the state (see Owner): it reads an inbox, where spawn(), ready() and
    stop() send their requests and every step's task its end (TaskDone).
    Nothing else reads or writes that state, so it needs no lock.

    A service whose ``depends_on`` are all RUNNING starts at once; any other
    waits (CREATED) until the last of them reaches RUNNING. A service starting
    is checked for health once something waits on it (ready(), or a service
    depending on it). A spawn that would close a dependency cycle is refused; a
    service waiting on one that leaves the runtime fails with
    DependencyFailedError. A service that fails while running is restarted per
    its policy, after its backoff. stop() stops services in reverse start
    order: dependents before what they depend on.

    State hooks run on the runtime's own task: a hook observes, and cannot
    call spawn(), ready() or stop().

    Example:
        with Runtime(lg) as rt:
            api = rt.spawn(Api(lg))            # Api.depends_on == ["database"]
            rt.spawn(Indexer(lg), isolate=True)
            rt.spawn(Database(lg, cfg))        # api starts once this runs
            rt.ready(api)
    """

    def __init__(self, lg: Logger, name: str = "runtime") -> None:
        """A runtime not yet started; *name* names it in errors."""
        self._lg = lg
        self.name = name
        self._tasks = Tasks(lg)
        self._root = StopToken()
        # Unbounded: a task's end is sent from any thread, the loop's included
        self._inbox: Chan[Any] = Chan(None)
        self._owner = Owner(lg, name, self._tasks, self._root, self._inbox)
        self._own: Task | None = None
        self._started_runtime = False
        self._closing = False  # set by stop()'s caller: spawn() refuses at once

    @property
    def services(self) -> dict[str, Runner]:
        """The services in the runtime by name, waiting ones included."""
        if not self._started_runtime:  # no task to ask, and nothing spawned yet
            return {}
        try:
            return dict(self._ask(Services))
        except ChanClosedError:  # stopped: its task has ended
            return self._owner.services()

    def start(self) -> None:
        """Start the runtime's event loop and its own task.

        Raises:
            RuntimeError: If the runtime was started already.
        """
        if self._started_runtime:
            raise RuntimeError(f"runtime '{self.name}' was started already")
        self._tasks.start()
        self._own = self._tasks.spawn(self._owner.serve, name=f"{self.name}-runtime")
        self._started_runtime = True
        # A runtime left running is stopped at exit, so teardown() runs
        atexit.register(self._atexit_stop)

    def spawn(
        self,
        service: Service,
        policy: RestartPolicy | None = None,
        *,
        isolate: bool = False,
    ) -> Runner:
        """Take *service*: start it now if its dependencies run, else once they
        do. Returns its runner; ready() waits until it is healthy, and raises
        how its start failed.

        Raises:
            RuntimeError: If the runtime is not running.
            TypeError: If *service* is not a Service.
            ValueError: If a service of the same name is in the runtime, or
                *isolate* is asked for an AsyncService.
            CycleError: If its dependencies lead back to it.
        """
        if not self._started_runtime or self._closing:
            raise RuntimeError(f"runtime '{self.name}' is not running")
        runner = Runner(service, policy)
        if isolate:
            _check_isolable(runner.service)
        try:
            self._ask(functools.partial(Spawn, runner, isolate))
        except ChanClosedError:
            raise RuntimeError(f"runtime '{self.name}' is not running") from None
        return runner

    def ready(self, *runners: Runner, timeout: float = 30.0) -> None:
        """Wait until every one of *runners* is healthy, *timeout* seconds in
        all; one not healthy in time fails.

        Raises:
            DependencyNotRunningError: If one still waits for a dependency.
            DependencyFailedError: If a dependency of one left the runtime first.
            SetupError: If one's setup() failed.
            RunError: If one exited or was stopped while starting.
            HealthTimeoutError: If one is not healthy in time.
        """
        deadline = time.monotonic() + timeout
        for runner in runners:
            self._await_ready(runner, max(0.0, deadline - time.monotonic()), timeout)

    def stop_service(self, runner: Runner, timeout: float = 5.0) -> None:
        """Stop one service and wait up to *timeout* seconds until it has ended
        and been torn down; then it leaves the runtime.

        Raises:
            TimeoutError: If it has not ended in time: STOPPING until it does.
        """
        with contextlib.suppress(ChanClosedError):
            self._ask(functools.partial(StopService, runner), timeout=timeout)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop every service, last started first, each given up to *timeout*
        seconds to end; one still running then is logged and the rest stop
        regardless. A service still waiting for its dependencies never starts.
        Then stop the runtime's tasks: see appinfra.runtime Runtime.stop().

        Raises:
            RuntimeError: If called from a state hook, before anything changes.
        """
        self._refuse_own_task()
        if not self._started_runtime or self._closing:
            return
        self._closing = True
        atexit.unregister(self._atexit_stop)
        with contextlib.suppress(ChanClosedError):
            self._ask(functools.partial(Stop, timeout))
        self._root.stop()
        self._inbox.close()
        if self._own is not None:
            with contextlib.suppress(StoppedError, TimeoutError):
                self._own.wait(timeout)
        self._tasks.stop(timeout)

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

    def _atexit_stop(self) -> None:
        """At interpreter exit: stop a runtime nothing stopped."""
        try:
            self.stop()
        except Exception as e:
            self._lg.warning("runtime stop at exit failed", extra={"exception": e})

    def _await_ready(self, runner: Runner, left: float, timeout: float) -> None:
        """Wait up to *left* seconds for *runner*; raise why it is not ready."""
        waited: Chan[Any] = Chan(1)  # its giving up takes this wait back
        try:
            self._ask_on(waited, Ready(runner, waited), timeout=left)
        except ChanClosedError:  # stopped: what its task left
            failure = self._owner.take_failure(runner)
            if failure is not None:
                raise failure from None
            if runner.state not in UP:
                raise RunError(runner.name, "the runtime stopped") from None
        except TimeoutError:
            # Raises DependencyNotRunningError for a service still waiting; a
            # runtime stopped meanwhile, or too busy to answer within the
            # grace, has nothing more to say than the timeout
            try:
                self._ask(functools.partial(GiveUp, runner, waited), GIVE_UP_GRACE)
            except DependencyNotRunningError:  # a TimeoutError too: the answer
                raise
            except (ChanClosedError, TimeoutError):
                pass
            raise HealthTimeoutError(runner.name, timeout) from None

    def _ask(
        self, make: Callable[[Chan[Any]], object], timeout: float | None = None
    ) -> Any:
        """Send the request *make* builds around a reply channel and wait for
        the reply; an error replied is raised.

        Raises:
            ChanClosedError: If the runtime's task has ended.
            TimeoutError: If no reply comes in *timeout* seconds.
            RuntimeError: If called from the runtime's own task (a state hook),
                which would wait for itself.
        """
        reply: Chan[Any] = Chan(1)
        return self._ask_on(reply, make(reply), timeout)

    def _ask_on(
        self, reply: Chan[Any], request: object, timeout: float | None = None
    ) -> Any:
        """_ask() with a *request* built around *reply* by the caller, who
        keeps it: a later request can name the wait.

        Raises:
            As _ask().
        """
        self._refuse_own_task()
        self._inbox.send(request)
        outcome = reply.recv(timeout=timeout)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def _refuse_own_task(self) -> None:
        """Refuse a call from the runtime's own task: a state hook.

        Raises:
            RuntimeError: If called there.
        """
        if self._own is None:
            return
        try:
            own = current_task_id() == self._own.id
        except RuntimeError:  # not in a task at all
            return
        if own:
            raise RuntimeError(
                f"runtime '{self.name}' called from a state hook: hooks run on the "
                "runtime's own task and cannot call spawn(), ready() or stop()"
            )


def _check_isolable(service: Service) -> None:
    """Refuse isolate=True for an AsyncService: it runs on the loop.

    Raises:
        ValueError: If *service* is an AsyncService.
    """
    if isinstance(service, AsyncService):
        raise ValueError(
            f"async service '{service.name}' cannot run isolated: an async "
            "service runs on the runtime's event loop"
        )
