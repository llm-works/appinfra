# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runtime: runs services as appinfra.runtime tasks, in dependency order."""

from __future__ import annotations

import atexit
import contextlib
import copy
import functools
import multiprocessing as mp
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any

from ...log import Logger
from ...log.mp import LogQueueListener
from ...runtime import Chan, ChanClosedError, StoppedError, StopToken, Task, TaskDone
from ...runtime import Runtime as Tasks
from ...runtime import task_id as current_task_id
from ..base import AsyncService, ScheduledService, Service
from ..errors import (
    CycleError,
    DependencyFailedError,
    DependencyNotRunningError,
    HealthTimeoutError,
    RunError,
    SetupError,
)
from ..state import RestartPolicy, State
from . import steps
from .drive import check_drivable, drive
from .runner import OWED, TEARING, TORN, Runner

# States in which a service has started and is, or was, healthy
_UP = (State.RUNNING, State.IDLE, State.DONE)


@dataclass(frozen=True, slots=True)
class _Spawn:
    runner: Runner
    isolate: bool
    reply: Chan[Any]


@dataclass(frozen=True, slots=True)
class _Ready:
    runner: Runner
    give_up: bool  # the caller's wait timed out: why, and fail a start
    reply: Chan[Any]


@dataclass(frozen=True, slots=True)
class _StopService:
    runner: Runner
    reply: Chan[Any]


@dataclass(frozen=True, slots=True)
class _Stop:
    timeout: float  # per service
    reply: Chan[Any]


@dataclass(frozen=True, slots=True)
class _Services:
    reply: Chan[Any]


@dataclass(slots=True)
class _Child:
    """What the parent keeps for an isolated service's run."""

    healthy: Any  # a multiprocessing Event the child sets
    listener: LogQueueListener  # forwards the child's log records


@dataclass(slots=True)
class _Shutdown:
    """stop() under way: the services left, last started first."""

    queue: list[Runner]
    timeout: float
    reply: Chan[Any]
    current: Runner | None = None
    deadline: Task | None = None
    walking: bool = field(default=False)


class Runtime:
    """Runs services: spawn() takes each, in any order and from any thread, and
    starts it once its dependencies run.

    Each step of a service is a task on the appinfra.runtime Runtime this one
    owns: its setup() and teardown() on threads, its run on the event loop (an
    AsyncService), on a thread (any other service), or in a process of its own
    (isolate=True), and its health checks. One task of the runtime's own owns
    all the state: it reads an inbox, where spawn(), ready() and stop() send
    their requests and every step's task its end (TaskDone). Nothing else
    reads or writes that state, so it needs no lock.

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
        self._own: Task | None = None
        self._started_runtime = False
        self._closing = False  # set by stop()'s caller: spawn() refuses at once
        self._init_owned()

    def _init_owned(self) -> None:
        """The state only the runtime's own task reads and writes."""
        # Every service, by name: the waiting in spawn order, then the started
        # in start order (_begin() moves each to the end as it first starts)
        self._runners: dict[str, Runner] = {}
        self._pending: set[str] = set()  # waiting for dependencies
        self._waiters: dict[str, set[str]] = {}  # dependency -> pending on it
        self._isolated: set[Runner] = set()
        self._children: dict[Runner, _Child] = {}
        self._ready: dict[Runner, list[Chan[Any]]] = {}  # ready() waiting
        self._stops: dict[Runner, list[Chan[Any]]] = {}  # stops waiting
        self._stop_asked: set[Runner] = set()  # stopped during setup
        # Why a service did not start, for a ready() not waiting yet. Weak: a
        # runner no one holds is never ready()'d
        self._failures: weakref.WeakKeyDictionary[Runner, BaseException] = (
            weakref.WeakKeyDictionary()
        )
        self._health: dict[str, int] = {}  # health task ids, by service
        self._tearing: dict[str, int] = {}  # teardown task ids, by service
        self._backoffs: dict[str, Task] = {}  # waiting out a restart's backoff
        self._restarting: set[str] = set()
        self._shutdown: _Shutdown | None = None

    # -- the public API, on any thread ------------------------------------------

    @property
    def services(self) -> dict[str, Runner]:
        """The services in the runtime by name, waiting ones included."""
        try:
            return dict(self._ask(_Services))
        except ChanClosedError:  # stopped: its task has ended
            return dict(self._runners)

    def start(self) -> None:
        """Start the runtime's event loop and its own task.

        Raises:
            RuntimeError: If the runtime was started already.
        """
        if self._started_runtime:
            raise RuntimeError(f"runtime '{self.name}' was started already")
        self._tasks.start()
        self._own = self._tasks.spawn(self._serve, name=f"{self.name}-runtime")
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
        runner.service.stopping = self._root.child()
        try:
            self._ask(functools.partial(_Spawn, runner, isolate))
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
            self._ask(functools.partial(_StopService, runner), timeout=timeout)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop every service, last started first, each given up to *timeout*
        seconds to end; one still running then is logged and the rest stop
        regardless. A service still waiting for its dependencies never starts.
        Then stop the runtime's tasks: see appinfra.runtime Runtime.stop()."""
        if not self._started_runtime or self._closing:
            return
        self._closing = True
        atexit.unregister(self._atexit_stop)
        with contextlib.suppress(ChanClosedError):
            self._ask(functools.partial(_Stop, timeout))
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
        try:
            self._ask(functools.partial(_Ready, runner, False), timeout=left)
        except ChanClosedError:  # stopped: what its task left
            failure = self._failures.pop(runner, None)
            if failure is not None:
                raise failure from None
            if runner.state not in _UP:
                raise RunError(runner.name, "the runtime stopped") from None
        except TimeoutError:
            # Raises DependencyNotRunningError for a service still waiting
            self._ask(functools.partial(_Ready, runner, True))
            raise HealthTimeoutError(runner.name, timeout) from None

    # -- the inbox ----------------------------------------------------------------

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
        if self._on_own_task():
            raise RuntimeError(
                f"runtime '{self.name}' called from a state hook: hooks run on the "
                "runtime's own task and cannot call spawn(), ready() or stop()"
            )
        reply: Chan[Any] = Chan(1)
        self._inbox.send(make(reply))
        outcome = reply.recv(timeout=timeout)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def _on_own_task(self) -> bool:
        if self._own is None:
            return False
        try:
            return current_task_id() == self._own.id
        except RuntimeError:  # not in a task at all
            return False

    def _serve(self) -> None:
        """The runtime's own task: handle each message in turn until stop()
        closes the inbox. A failing handler is logged and its request gets the
        error; the next message is handled regardless."""
        with contextlib.suppress(StoppedError):
            for message in self._inbox:
                try:
                    _HANDLERS[type(message)](self, message)
                except Exception as e:
                    self._lg.warning(
                        "runtime message failed",
                        extra={"message": type(message).__name__, "exception": e},
                    )
                    reply = getattr(message, "reply", None)
                    if reply is not None:
                        _reply(reply, e)

    # -- requests, on the runtime's own task ----------------------------------------

    def _on_spawn(self, m: _Spawn) -> None:
        runner = m.runner
        refusal = self._refusal(runner.service)
        if refusal is not None:
            _reply(m.reply, refusal)
            return
        self._runners[runner.name] = runner
        if m.isolate:
            self._isolated.add(runner)
        _reply(m.reply, None)
        if self._dependencies_run(runner.service):
            self._begin(runner)
        else:
            self._wait(runner)
            self._watch_dependencies(runner.service)

    def _on_ready(self, m: _Ready) -> None:
        runner = m.runner
        if m.give_up:
            self._give_up(runner, m.reply)
            return
        failure = self._failures.pop(runner, None)
        if failure is not None:
            _reply(m.reply, failure)
        elif runner.state in _UP:
            _reply(m.reply, None)
        elif self._runners.get(runner.name) is not runner:
            _reply(m.reply, _startup_error(runner))
        elif runner.state in (State.STOPPING, State.STOPPED):
            _reply(m.reply, RunError(runner.name, "stopped during startup"))
        else:
            self._ready.setdefault(runner, []).append(m.reply)
            self._watch(runner)

    def _give_up(self, runner: Runner, reply: Chan[Any]) -> None:
        """A ready() timed out: name the missing dependency of a service still
        waiting, or end the run of one still starting, which fails it."""
        if runner.name in self._pending and self._runners.get(runner.name) is runner:
            _reply(reply, DependencyNotRunningError(runner.name, self._missing(runner)))
            return
        if runner.state == State.STARTING:
            self._end_run(runner)
        _reply(reply, None)

    def _on_stop_service(self, m: _StopService) -> None:
        if self._runners.get(m.runner.name) is not m.runner:
            _reply(m.reply, None)
            return
        self._stops.setdefault(m.runner, []).append(m.reply)
        self._halt(m.runner)

    def _on_stop(self, m: _Stop) -> None:
        """stop(): refuse the waiting, end the backoffs, then stop the started
        services one at a time, last started first."""
        self._closing = True
        for name in list(self._pending):
            # Refusing one fails what waited on it: gone by its turn
            if name in self._pending:
                self._refuse(self._runners[name])
        for task in self._backoffs.values():
            task.cancel()
        queue = list(reversed(self._runners.values()))  # only the started are left
        self._shutdown = _Shutdown(queue, m.timeout, m.reply)
        self._walk_shutdown()

    def _on_services(self, m: _Services) -> None:
        _reply(m.reply, dict(self._runners))

    def _on_task_done(self, m: TaskDone) -> None:
        """A step's task ended: hand it to its step's handler."""
        name, _, step = (m.name or "").rpartition("/")
        runner = self._runners.get(name)
        if runner is not None:
            _STEPS[step](self, runner, m)

    # -- steps, on the runtime's own task ----------------------------------------------

    def _step(
        self,
        runner: Runner,
        step: str,
        fn: Callable[..., Any],
        *args: Any,
        token: StopToken | None = None,
        process: bool = False,
    ) -> Task:
        """Spawn *fn*(*args*) as *runner*'s *step*; its end reaches the inbox."""
        return self._tasks.spawn(
            fn,
            *args,
            name=f"{runner.name}/{step}",
            token=self._root if token is None else token,
            done=self._inbox,
            process=process,
        )

    def _begin(self, runner: Runner) -> None:
        """Start *runner*: its setup step, or its launch if it has no setup()
        here (none of its own, or isolated: it sets up in its child)."""
        if runner.name not in self._restarting:  # a restart keeps its place
            self._runners[runner.name] = self._runners.pop(runner.name)
        if runner in self._isolated or not _overrides(runner.service, "setup"):
            self._launch(runner)
        else:
            runner._task = self._step(runner, "setup", steps.set_up, runner.service)

    def _on_setup(self, runner: Runner, m: TaskDone) -> None:
        if not _current(runner, m):
            return
        runner._task = None
        gone = self._gone_dependency(runner.service)
        if m.error is not None:
            self._setup_failed(runner, m.error)
        elif runner in self._stop_asked or self._closing:
            # Set up, but stopped first: it never runs, and is torn down
            for state in (State.INITD, State.STARTING, State.STOPPING):
                runner._move(state)
            self._tear(runner)
        elif gone is not None:
            # Torn down first: it fails once settled (_ended())
            runner._error = DependencyFailedError(runner.name, gone)
            self._tear(runner)
        else:
            self._launch(runner)

    def _setup_failed(self, runner: Runner, error: BaseException) -> None:
        """Setup failed: a restart attempt tries again or ends; a start fails."""
        self._lg.warning(
            "service failed to start",
            extra={"service": runner.name, "exception": error},
        )
        runner._error = error
        if runner.name in self._restarting:
            self._retry(runner)
            return
        if runner.state != State.FAILED:
            runner._move(State.FAILED)
        self._fail(runner, error)
        self._forget(runner)

    def _launch(self, runner: Runner) -> None:
        """Spawn *runner*'s run as a task: STARTING until healthy."""
        runner._move(State.INITD)
        runner._move(State.STARTING)
        runner._error = None
        service = runner.service
        if runner in self._isolated:
            runner._task = self._launch_child(runner)
            runner._teardown = OWED  # the parent's part: its log forwarding
        else:
            # Under the root token, not service.stopping: a child would give
            # that token a set of children to hold. A stop reaches the run
            # anyway: _end_run() stops the token and cancels the task.
            if isinstance(service, AsyncService):
                runner._task = self._step(runner, "run", service.run)
            else:
                runner._task = self._step(
                    runner, "run", drive, service, service.stopping
                )
            runner._teardown = OWED if _overrides(service, "teardown") else TORN
        awaited = runner in self._ready or self._waiters.get(runner.name)
        if awaited or runner.name in self._restarting:
            self._watch(runner)

    def _launch_child(self, runner: Runner) -> Task:
        """Spawn an isolated service's run in a child process, its log records
        forwarded to the service's logger here."""
        service = runner.service
        ctx = mp.get_context("spawn")
        queue = ctx.Queue()
        child = _Child(ctx.Event(), LogQueueListener(queue, service.lg))
        child.listener.start()
        self._children[runner] = child
        clone = copy.copy(service)  # a logger does not pickle; the child makes its own
        if hasattr(clone, "_lg"):
            clone._lg = None  # type: ignore[assignment]
        config = service.lg.queue_config(queue)
        return self._step(
            runner,
            "run",
            steps.isolated,
            clone,
            child.healthy,
            config,
            process=True,  # under the root token, as _launch() says
        )

    def _on_run(self, runner: Runner, m: TaskDone) -> None:
        """The run ended: its token stops, the teardown runs if owed, and the
        state settles once torn down."""
        if not _current(runner, m):
            return
        runner._task = None
        if m.error is not None and not isinstance(m.error, StoppedError):
            runner._error = m.error
        token = runner.service.stopping
        token.stop()
        token.detach()
        if runner._teardown == OWED:
            self._tear(runner)
        elif runner._teardown == TORN:
            self._settle(runner)

    def _tear(self, runner: Runner) -> None:
        """Tear *runner*'s service down on a task, or settle at once if there
        is nothing to tear down."""
        child = self._children.pop(runner, None)
        if child is not None:
            task = self._step(runner, "teardown", child.listener.stop)
        elif _overrides(runner.service, "teardown"):
            task = self._step(runner, "teardown", steps.tear_down, runner.service)
        else:
            runner._teardown = TORN
            self._settle(runner)
            return
        runner._teardown = TEARING
        self._tearing[runner.name] = task.id

    def _on_teardown(self, runner: Runner, m: TaskDone) -> None:
        if self._tearing.get(runner.name) != m.task_id:
            return
        del self._tearing[runner.name]
        if m.error is not None:
            runner.service.lg.warning(
                "teardown failed", extra={"exception": m.error, "service": runner.name}
            )
        runner._teardown = TORN
        if runner._task is None:
            self._settle(runner)

    def _settle(self, runner: Runner) -> None:
        """Once the run has ended and been torn down: STOPPED after a stop, DONE
        after a clean end of a RUNNING service, FAILED after an error or any
        end of a start."""
        old = runner.state
        to = {State.STOPPING: State.STOPPED, State.STARTING: State.FAILED}.get(old)
        if old in (State.RUNNING, State.IDLE):
            to = State.DONE if runner._error is None else State.FAILED
        elif old == State.CREATED:  # set up, then its dependency left
            to = State.FAILED
        if to is not None:
            runner._move(to)
        self._ended(runner, old, to or old)

    def _ended(self, runner: Runner, old: State, new: State) -> None:
        """Act on a settled run: answer the waits, restart a failed service the
        policy allows, else take it out of the runtime."""
        if old in (State.STARTING, State.CREATED):
            self._fail(runner, _startup_error(runner))
        for reply in self._stops.pop(runner, ()):
            _reply(reply, None)
        self._stop_asked.discard(runner)
        restart = new == State.FAILED and (
            old in (State.RUNNING, State.IDLE) or runner.name in self._restarting
        )
        if restart and self._runners.get(runner.name) is runner:
            self._retry(runner)
        else:
            self._forget(runner)
        self._shutdown_settled(runner)

    def _retry(self, runner: Runner) -> None:
        """Arm the next restart attempt if the policy allows one, else let the
        failed service go."""
        if runner.can_restart and not self._closing:
            self._restarting.add(runner.name)
            task = self._step(runner, "backoff", steps.back_off, runner.restart_delay)
            self._backoffs[runner.name] = task
            return
        self._fail(runner, _startup_error(runner))
        self._forget(runner)

    def _on_backoff(self, runner: Runner, m: TaskDone) -> None:
        """The backoff ended: make the restart attempt, unless stop() ended it."""
        task = self._backoffs.get(runner.name)
        if task is None or task.id != m.task_id:
            return
        del self._backoffs[runner.name]
        if m.error is not None or self._closing:
            self._restarting.discard(runner.name)
            if runner in self._stops:
                self._halt(runner)
            return
        runner._retries += 1
        runner.service.stopping = self._root.child()
        self._begin(runner)

    def _watch(self, runner: Runner) -> None:
        """Check *runner*'s health on a task, if it is starting and none does
        yet; its token, the run's, ends the check with the run."""
        if runner.state != State.STARTING or runner.name in self._health:
            return
        child = self._children.get(runner)
        token = runner.service.stopping
        if child is not None:
            healthy = child.healthy
            task = self._step(
                runner, "health", steps.check_child_health, healthy, token=token
            )
        else:
            service = runner.service
            task = self._step(
                runner, "health", steps.check_health, service, token=token
            )
        self._health[runner.name] = task.id

    def _on_health(self, runner: Runner, m: TaskDone) -> None:
        """A health check ended: a healthy service STARTING runs, and starts
        what waited on it; a check that raised fails the start."""
        if self._health.get(runner.name) != m.task_id:
            return
        del self._health[runner.name]
        if runner.state != State.STARTING:
            return
        if m.error is not None and not isinstance(m.error, StoppedError):
            self._lg.warning(
                "service health check failed",
                extra={"service": runner.name, "exception": m.error},
            )
            runner._error = m.error
            self._end_run(runner)
        elif m.result is True:
            runner._retries = 0
            self._restarting.discard(runner.name)
            runner._move(State.RUNNING)
            for reply in self._ready.pop(runner, ()):
                _reply(reply, None)
            self._start_waiters(runner.name)

    def _on_deadline(self, runner: Runner, m: TaskDone) -> None:
        """A service stop() waited on did not end in time: go on without it."""
        sd = self._shutdown
        if sd is None or sd.deadline is None or sd.deadline.id != m.task_id:
            return
        if sd.current is runner:
            self._lg.warning(
                "service did not stop in time",
                extra={"service": runner.name, "timeout": sd.timeout},
            )
            sd.current = None
            self._walk_shutdown()

    # -- stopping, on the runtime's own task ------------------------------------------------

    def _halt(self, runner: Runner) -> None:
        """Begin to stop *runner*; its stops are answered once it has settled."""
        task = runner._task
        if runner.name in self._pending:
            self._refuse(runner)
        elif task is not None and (task.name or "").endswith("/setup"):
            self._stop_asked.add(runner)  # stopped once its setup ends
        elif runner.state in (State.STARTING, State.RUNNING, State.IDLE):
            runner._move(State.STOPPING)
            self._end_run(runner)
            tears = runner not in self._isolated and not isinstance(
                runner.service, (ScheduledService, AsyncService)
            )
            # A run() of its own may block elsewhere: its teardown can release it
            if tears and runner._teardown == OWED:
                self._tear(runner)
        elif runner.name in self._backoffs:
            self._backoffs[runner.name].cancel()
        elif runner.state != State.STOPPING:
            for reply in self._stops.pop(runner, ()):
                _reply(reply, None)
            self._forget(runner)
            self._shutdown_settled(runner)

    def _end_run(self, runner: Runner) -> None:
        """Stop *runner*'s run: its token, and its task."""
        runner.service.stopping.stop()
        if runner._task is not None:
            runner._task.cancel()

    def _walk_shutdown(self) -> None:
        """Stop the next service of stop()'s queue, until one has to be waited
        for; reply to stop() once the queue is done."""
        sd = self._shutdown
        if sd is None:
            return
        sd.walking = True
        while sd.current is None and sd.queue:
            runner = sd.queue.pop(0)
            if self._runners.get(runner.name) is not runner:
                continue
            sd.current = runner
            self._stops.setdefault(runner, [])
            self._halt(runner)
            if sd.current is runner:
                sd.deadline = self._step(runner, "deadline", steps.back_off, sd.timeout)
        sd.walking = False
        if sd.current is None and not sd.queue:
            self._shutdown = None
            _reply(sd.reply, None)

    def _shutdown_settled(self, runner: Runner) -> None:
        """*runner* settled: stop() goes on with the next service."""
        sd = self._shutdown
        if sd is None or sd.current is not runner:
            return
        sd.current = None
        if sd.deadline is not None:
            sd.deadline.cancel()
            sd.deadline = None
        if not sd.walking:
            self._walk_shutdown()

    # -- bookkeeping, on the runtime's own task ---------------------------------------------

    def _refusal(self, service: Service) -> BaseException | None:
        """Why the runtime cannot take *service*, or None."""
        if self._closing:
            return RuntimeError(f"runtime '{self.name}' is not running")
        if service.name in self._runners:
            return ValueError(f"service '{service.name}' is in the runtime already")
        cycle = self._cycle(service)
        return CycleError(cycle) if cycle is not None else None

    def _cycle(self, service: Service) -> list[str] | None:
        """The services a dependency cycle through *service* would pass."""
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
        return all(
            dep in self._runners and self._runners[dep].state == State.RUNNING
            for dep in service.depends_on
        )

    def _gone_dependency(self, service: Service) -> str | None:
        return next((d for d in service.depends_on if d not in self._runners), None)

    def _missing(self, runner: Runner) -> str:
        """The first dependency of *runner* that is not running."""
        for dep in runner.service.depends_on:
            if dep not in self._runners or self._runners[dep].state != State.RUNNING:
                return dep
        return ", ".join(runner.service.depends_on)

    def _wait(self, runner: Runner) -> None:
        self._pending.add(runner.name)
        for dep in runner.service.depends_on:
            self._waiters.setdefault(dep, set()).add(runner.name)

    def _unindex(self, name: str) -> None:
        for dep in self._runners[name].service.depends_on:
            waiters = self._waiters.get(dep)
            if waiters is not None:
                waiters.discard(name)
                if not waiters:
                    del self._waiters[dep]

    def _start_waiters(self, name: str) -> None:
        """Start the services waiting on *name* whose dependencies all run."""
        if self._closing:
            return
        for waiter in list(self._waiters.get(name, ())):
            runner = self._runners[waiter]
            if waiter in self._pending and self._dependencies_run(runner.service):
                self._pending.discard(waiter)
                self._unindex(waiter)
                self._begin(runner)

    def _watch_dependencies(self, service: Service) -> None:
        """Check the health of the dependencies a new waiter waits on."""
        for dep in service.depends_on:
            runner = self._runners.get(dep)
            if runner is not None:
                self._watch(runner)

    def _fail(self, runner: Runner, error: BaseException) -> None:
        """*runner* will not run: tell the ready() calls waiting, or keep
        *error* for the next one."""
        waiting = self._ready.pop(runner, None)
        if waiting is None:
            self._failures[runner] = error
        for reply in waiting or ():
            _reply(reply, error)

    def _refuse(self, runner: Runner) -> None:
        """A waiting service will not start, as it is stopped first."""
        self._fail(runner, RunError(runner.name, "the runtime stopped first"))
        runner._move(State.FAILED)  # CREATED -> FAILED
        for reply in self._stops.pop(runner, ()):
            _reply(reply, None)
        self._forget(runner)

    def _forget(self, runner: Runner) -> None:
        """Take *runner* out of the runtime; the services still waiting on it
        fail, as it will not run for them."""
        name = runner.name
        if self._runners.get(name) is not runner:
            return
        if name in self._pending:
            self._pending.discard(name)
            self._unindex(name)
        waiting = [
            self._runners[w] for w in self._waiters.pop(name, ()) if w in self._pending
        ]
        del self._runners[name]
        self._restarting.discard(name)
        self._isolated.discard(runner)
        if runner in self._ready:
            outcome = None if runner.state in _UP else _startup_error(runner)
            for reply in self._ready.pop(runner):
                _reply(reply, outcome)
        for waiter in waiting:
            self._fail(waiter, DependencyFailedError(waiter.name, name))
            waiter._move(State.FAILED)  # never started: CREATED -> FAILED
            self._forget(waiter)


_HANDLERS: dict[type, Callable[[Runtime, Any], None]] = {
    _Spawn: Runtime._on_spawn,
    _Ready: Runtime._on_ready,
    _StopService: Runtime._on_stop_service,
    _Stop: Runtime._on_stop,
    _Services: Runtime._on_services,
    TaskDone: Runtime._on_task_done,
}

_STEPS: dict[str, Callable[[Runtime, Runner, TaskDone], None]] = {
    "setup": Runtime._on_setup,
    "run": Runtime._on_run,
    "teardown": Runtime._on_teardown,
    "health": Runtime._on_health,
    "backoff": Runtime._on_backoff,
    "deadline": Runtime._on_deadline,
}


def _current(runner: Runner, m: TaskDone) -> bool:
    """True if *m* ends *runner*'s current setup or run, not an older one."""
    return runner._task is not None and runner._task.id == m.task_id


def _overrides(service: Service, method: str) -> bool:
    """True if *service* overrides Service.*method*: the default does nothing,
    and needs no task to run it."""
    return getattr(type(service), method) is not getattr(Service, method)


def _check_isolable(service: Service) -> None:
    """Refuse isolate=True for an AsyncService: it runs on the loop.

    Raises:
        ValueError: If *service* is an AsyncService.
    """
    try:
        check_drivable(service)
    except TypeError:
        raise ValueError(
            f"async service '{service.name}' cannot run isolated: an async "
            "service runs on the runtime's event loop"
        ) from None


def _startup_error(runner: Runner) -> BaseException:
    """Why *runner*, no longer starting, did not become healthy."""
    error = runner.exception
    if isinstance(error, (SetupError, DependencyFailedError)):
        return error
    if runner.state != State.FAILED:
        return RunError(runner.name, "stopped during startup")
    if error is None:
        return RunError(runner.name, "exited during startup")
    failure = RunError(runner.name, f"exited during startup: {error}")
    failure.__cause__ = error
    return failure


def _reply(reply: Chan[Any], value: object) -> None:
    """Answer a request; its caller may have stopped waiting (a timeout), and
    a reply channel holds the one answer, so the send never waits."""
    with contextlib.suppress(TimeoutError, ChanClosedError):
        reply.send(value, timeout=0)
