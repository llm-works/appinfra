# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The service Runtime's own task: the Owner, which holds every service's state
and reads the inbox that requests and the ends of the services' tasks reach.
Everything here runs on that one task, so it needs no lock."""

from __future__ import annotations

import contextlib
import copy
import functools
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ...log import Logger
from ...log.mp import LogQueueListener
from ...runtime import (
    Chan,
    ChanClosedError,
    StoppedError,
    StopToken,
    Task,
    TaskDone,
    process_context,
    this_task,
)
from ...runtime import Runtime as Tasks
from ..base import AsyncService, ScheduledService, Service
from ..errors import (
    CycleError,
    DependencyFailedError,
    DependencyNotRunningError,
    RunError,
    SetupError,
)
from ..state import State
from . import child as child_process
from .deps import Dependencies
from .runner import OWED, TEARING, TORN, Runner

# States in which a service has started and is, or was, healthy
UP = (State.RUNNING, State.IDLE, State.DONE)

# Seconds between two health checks of a service starting
_HEALTH_INTERVAL = 0.1


# -- the requests the Runtime sends ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class Spawn:
    runner: Runner
    isolate: bool
    reply: Chan[Any]


@dataclass(frozen=True, slots=True)
class Ready:
    runner: Runner
    reply: Chan[Any]


@dataclass(frozen=True, slots=True)
class GiveUp:
    """A ready() timed out: why, and fail a start."""

    runner: Runner
    waited: Chan[Any]  # the reply channel of the Ready it waited on
    reply: Chan[Any]


@dataclass(frozen=True, slots=True)
class StopService:
    runner: Runner
    reply: Chan[Any]
    timeout: float  # how long its run gets before it is forced


@dataclass(frozen=True, slots=True)
class Stop:
    timeout: float  # per service
    reply: Chan[Any]


@dataclass(frozen=True, slots=True)
class Services:
    reply: Chan[Any]


# -- what the Owner keeps -------------------------------------------------------------


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


class Owner:
    """The state of a service Runtime and the task that alone reads and writes
    it: serve() handles the inbox's messages one at a time, each request and
    each end of a service's step."""

    def __init__(
        self, lg: Logger, name: str, tasks: Tasks, root: StopToken, inbox: Chan[Any]
    ) -> None:
        """The owner of runtime *name*'s services: their steps run on *tasks*,
        under *root*, and end in *inbox*, which serve() reads."""
        self._lg = lg
        self._name = name
        self._tasks = tasks
        self._root = root
        self._inbox = inbox
        self._closing = False  # stop() reached: nothing new starts
        # Every service, by name: the waiting in spawn order, then the started
        # in start order (_begin() moves each to the end as it first starts)
        self._runners: dict[str, Runner] = {}
        self._deps = Dependencies(self._runners)
        self._isolated: set[Runner] = set()
        self._children: dict[Runner, _Child] = {}
        self._ready: dict[Runner, list[Chan[Any]]] = {}  # ready() waiting
        self._stops: dict[Runner, list[Chan[Any]]] = {}  # stops waiting
        self._stop_asked: set[Runner] = set()  # stopped during setup
        self._expired: set[Runner] = set()  # a ready() gave up during setup
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

    # -- read once serve() has ended ------------------------------------------------

    def services(self) -> dict[str, Runner]:
        """The services left in the runtime, by name: for after serve() ended."""
        return dict(self._runners)

    def take_failure(self, runner: Runner) -> BaseException | None:
        """Why *runner* did not start, if no ready() was told: for after
        serve() ended."""
        return self._failures.pop(runner, None)

    # -- the task -------------------------------------------------------------------

    def serve(self) -> None:
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
                    del reply
                # The next message can be long in coming: meanwhile this frame
                # holds nothing of this one, the runner a stop let go of least
                del message

    # -- requests --------------------------------------------------------------------

    def _on_spawn(self, m: Spawn) -> None:
        runner = m.runner
        refusal = self._refusal(runner.service)
        if refusal is not None:
            _reply(m.reply, refusal)
            return
        runner._owner = self
        # Only once accepted: a refused spawn of a running instance leaves the
        # token its run waits on in place
        runner.service.stopping = self._root.child()
        self._runners[runner.name] = runner
        if m.isolate:
            self._isolated.add(runner)
        _reply(m.reply, None)
        if self._deps.all_run(runner.service):
            self._begin(runner)
        else:
            self._deps.wait(runner.service)
            self._watch_dependencies(runner.service)

    def _on_ready(self, m: Ready) -> None:
        runner = m.runner
        if self._refused_foreign(runner, m.reply):
            return
        failure = self._failures.pop(runner, None)
        if failure is not None:
            _reply(m.reply, failure)
        elif runner.state in UP:
            _reply(m.reply, None)
        elif self._runners.get(runner.name) is not runner:
            _reply(m.reply, _startup_error(runner))
        elif runner.state in (State.STOPPING, State.STOPPED):
            _reply(m.reply, RunError(runner.name, "stopped during startup"))
        else:
            self._ready.setdefault(runner, []).append(m.reply)
            self._watch(runner)

    def _on_give_up(self, m: GiveUp) -> None:
        """A ready() timed out: its wait is taken back, then name the missing
        dependency of a service still waiting, or end the start of one still
        in setup() or starting, which fails it."""
        runner, reply = m.runner, m.reply
        if self._refused_foreign(runner, reply):
            return
        waits = self._ready.get(runner)
        if waits is not None and m.waited in waits:
            waits.remove(m.waited)
            if not waits:
                del self._ready[runner]
        waiting = self._deps.is_waiting(runner.name)
        if waiting and self._runners.get(runner.name) is runner:
            missing = self._deps.missing(runner.service)
            _reply(reply, DependencyNotRunningError(runner.name, missing))
            return
        if runner.state == State.STARTING:
            self._end_run(runner, runner.policy.stop_timeout)
        elif _in_setup(runner):
            self._expired.add(runner)  # once set up, it fails (_on_setup())
        _reply(reply, None)

    def _refused_foreign(self, runner: Runner, reply: Chan[Any]) -> bool:
        """Refuse a runner this runtime did not admit: another runtime's, or
        one refused at spawn.

        Returns:
            True if refused, with ValueError replied.
        """
        if runner._owner is self:
            return False
        error = ValueError(
            f"{runner.name!r} is not a service of runtime {self._name!r}"
        )
        _reply(reply, error)
        return True

    def _on_stop_service(self, m: StopService) -> None:
        if self._runners.get(m.runner.name) is not m.runner:
            _reply(m.reply, None)
            return
        self._stops.setdefault(m.runner, []).append(m.reply)
        self._halt(m.runner, m.timeout)

    def _on_stop(self, m: Stop) -> None:
        """stop(): refuse the waiting, end the backoffs, then stop the started
        services one at a time, last started first."""
        self._closing = True
        for name in self._deps.waiting():
            # Refusing one fails what waited on it: gone by its turn
            if self._deps.is_waiting(name):
                self._refuse(self._runners[name])
        for task in self._backoffs.values():
            task.cancel()
        queue = list(reversed(self._runners.values()))  # only the started are left
        self._shutdown = _Shutdown(queue, m.timeout, m.reply)
        self._walk_shutdown()

    def _on_services(self, m: Services) -> None:
        _reply(m.reply, dict(self._runners))

    def _on_task_done(self, m: TaskDone) -> None:
        """A step's task ended: hand it to its step's handler."""
        name, _, step = (m.name or "").rpartition("/")
        runner = self._runners.get(name)
        if runner is not None:
            _STEPS[step](self, runner, m)

    # -- steps -----------------------------------------------------------------------

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
            runner._task = self._step(runner, "setup", runner.service.setup)

    def _on_setup(self, runner: Runner, m: TaskDone) -> None:
        if not _current(runner, m):
            return
        runner._task = None
        expired = runner in self._expired
        self._expired.discard(runner)
        # The start rule again, once set up: a dependency may have stopped,
        # left or failed during setup()
        down = self._deps.down(runner.service)
        if m.error is not None:
            self._setup_failed(runner, _setup_error(runner, m.error))
        elif runner in self._stop_asked or self._closing:
            # Set up, but stopped first: it never runs, and is torn down
            for state in (State.INITD, State.STARTING, State.STOPPING):
                runner._move(state)
            _end_token(runner)
            self._tear(runner)
        elif down is not None or expired:
            # Torn down first: it fails once settled (_ended())
            runner._error = (
                DependencyFailedError(runner.name, down)
                if down is not None
                else RunError(runner.name, "not ready in time")
            )
            _end_token(runner)
            self._tear(runner)
        else:
            self._launch(runner)

    def _setup_failed(self, runner: Runner, error: BaseException) -> None:
        """Setup failed: a restart attempt tries again or ends; a start fails.
        A stop asked during the setup ends it either way, and is answered."""
        self._lg.warning(
            "service failed to start",
            extra={"service": runner.name, "exception": error},
        )
        runner._error = error
        stopped = runner in self._stop_asked
        self._stop_asked.discard(runner)
        if runner.name in self._restarting and not stopped:
            _end_token(runner)  # this attempt's; the next one gets its own
            self._retry(runner)
            return
        if runner.state != State.FAILED:
            runner._move(State.FAILED)
        self._fail(runner, error)
        self._let_go(runner)

    def _let_go(self, runner: Runner) -> None:
        """*runner* will not run again: answer its stops, take it out of the
        runtime, and let stop() go on if it was stopping it."""
        for reply in self._stops.pop(runner, ()):
            _reply(reply, None)
        self._forget(runner)
        self._shutdown_settled(runner)

    def _launch(self, runner: Runner) -> None:
        """Spawn *runner*'s run as a task: STARTING until healthy."""
        runner._move(State.INITD)
        runner._move(State.STARTING)
        runner._error = None
        try:
            self._start_run(runner)
        except Exception as e:  # the run never began: its start fails with e
            runner._error = e
            runner._teardown = TORN
            _end_token(runner)
            self._settle(runner)
            return
        awaited = runner in self._ready or self._deps.awaited(runner.name)
        if awaited or runner.name in self._restarting:
            self._watch(runner)

    def _start_run(self, runner: Runner) -> None:
        """Spawn *runner*'s run task."""
        service = runner.service
        if runner in self._isolated:
            runner._task = self._launch_child(runner)
            runner._teardown = OWED  # the parent's part: its log forwarding
        else:
            # On the loop for an AsyncService, else on a thread. Under the root
            # token, not service.stopping: a child would give that token a set
            # of children to hold. A stop reaches the run anyway: _end_run()
            # stops the token and cancels the task.
            runner._task = self._step(runner, "run", service.run)
            runner._teardown = OWED if _overrides(service, "teardown") else TORN

    def _launch_child(self, runner: Runner) -> Task:
        """Spawn an isolated service's run in a child process, its log records
        forwarded to the service's logger here. What it set up is undone if
        the spawn fails."""
        service = runner.service
        ctx = process_context()
        queue = ctx.Queue()
        child = _Child(ctx.Event(), LogQueueListener(queue, service.lg))
        child.listener.start()
        self._children[runner] = child
        try:
            return self._spawn_child(runner, child, queue)
        except BaseException:
            del self._children[runner]
            child.listener.stop()
            raise

    def _spawn_child(self, runner: Runner, child: _Child, queue: Any) -> Task:
        """The run task of an isolated service, given its log queue."""
        service = runner.service
        clone = copy.copy(service)  # a logger does not pickle; the child makes its own
        if hasattr(clone, "_lg"):
            clone._lg = None  # type: ignore[assignment]
        config = service.lg.queue_config(queue)
        return self._step(
            runner,
            "run",
            child_process.main,
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
        _end_token(runner)
        # A check blocked in is_healthy() outlives the run: what it reports
        # later is the ended run's, and the next start gets a check of its own
        self._health.pop(runner.name, None)
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
            task = self._step(runner, "teardown", runner.service.teardown)
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
        stopped = runner in self._stop_asked
        self._stop_asked.discard(runner)
        restart = (
            new == State.FAILED
            and not stopped
            and (old in (State.RUNNING, State.IDLE) or runner.name in self._restarting)
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
            task = self._step(runner, "backoff", _back_off, runner.restart_delay)
            self._backoffs[runner.name] = task
            return
        self._fail(runner, _startup_error(runner))
        self._let_go(runner)

    def _on_backoff(self, runner: Runner, m: TaskDone) -> None:
        """The backoff ended: make the restart attempt, unless a stop ended it.
        A stop_service() handled after the backoff finished, its end still
        queued, cancelled nothing: its recorded stop ends the restart too. A
        service stopped while it waited, by stop_service() or stop(), ends
        STOPPED, its hooks told, and leaves the runtime: no run is left to end."""
        task = self._backoffs.get(runner.name)
        if task is None or task.id != m.task_id:
            return
        del self._backoffs[runner.name]
        if m.error is not None or self._closing or runner in self._stops:
            self._restarting.discard(runner.name)
            if runner in self._stops or self._closing:
                runner._move(State.STOPPED)
                self._let_go(runner)
            return
        runner._retries += 1
        down = self._deps.down(runner.service)
        if down is not None:
            # The start rule holds for a restart too: with a dependency down the
            # attempt fails, and the next, if any, follows after its backoff
            runner._error = DependencyFailedError(runner.name, down)
            self._retry(runner)
            return
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
            check = functools.partial(child_process.wait_healthy, child.healthy)
        else:
            check = functools.partial(_poll_health, runner.service)
        self._health[runner.name] = self._step(runner, "health", check, token=token).id

    def _on_health(self, runner: Runner, m: TaskDone) -> None:
        """A health check ended: a healthy service STARTING runs, and starts
        what waited on it; a check that raised fails the start. A run already
        ended (its token stopped) is not promoted: its own end settles it."""
        if self._health.get(runner.name) != m.task_id:
            return
        del self._health[runner.name]
        if runner.state != State.STARTING or runner.service.stopping.is_set():
            return
        if m.error is not None and not isinstance(m.error, StoppedError):
            self._lg.warning(
                "service health check failed",
                extra={"service": runner.name, "exception": m.error},
            )
            runner._error = m.error
            self._end_run(runner, runner.policy.stop_timeout)
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

    # -- stopping --------------------------------------------------------------------

    def _halt(self, runner: Runner, timeout: float) -> None:
        """Begin to stop *runner*, its run given *timeout* seconds before it is
        forced; its stops are answered once it has settled."""
        if self._deps.is_waiting(runner.name):
            self._refuse(runner)
        elif _in_setup(runner):
            self._stop_asked.add(runner)  # stopped once its setup ends
        elif runner.state in (State.STARTING, State.RUNNING, State.IDLE):
            runner._move(State.STOPPING)
            self._end_run(runner, timeout)
        elif runner.name in self._backoffs:
            self._backoffs[runner.name].cancel()
        elif runner._teardown == TEARING:
            # A setup that ended expired or with a dependency down, being torn
            # down: stopped once its teardown settles
            self._stop_asked.add(runner)
        elif runner.state == State.STOPPING:
            # Stopping already, maybe under a longer timeout: this stop forces
            # an isolated run within its own. Nothing more for one on the loop
            # or a thread: cancelling an async run again would interrupt its
            # cleanup, and its token is stopped already
            task = runner._task
            if task is not None and task.process is not None:
                task.stop(timeout)
        else:
            self._let_go(runner)

    def _end_run(self, runner: Runner, timeout: float) -> None:
        """Stop *runner*'s run: its token, and its task, which a process task
        must end within *timeout* seconds before the runtime forces it; on a
        stop, a failed health check and a ready() given up on alike.

        A plain service's run() on a thread may block elsewhere than on its
        token, and its teardown can release it: that teardown runs now. An
        async run is cancelled, a scheduled one ticks on its token, and an
        isolated one ends with its process: theirs follows the run."""
        runner.service.stopping.stop()
        if runner._task is not None:
            runner._task.stop(timeout)
        tears = runner not in self._isolated and not isinstance(
            runner.service, (ScheduledService, AsyncService)
        )
        if tears and runner._teardown == OWED:
            self._tear(runner)

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
            self._halt(runner, sd.timeout)
            if sd.current is runner:
                span = runner._stop_span(sd.timeout)
                sd.deadline = self._step(runner, "deadline", _back_off, span)
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

    # -- bookkeeping -----------------------------------------------------------------

    def _refusal(self, service: Service) -> BaseException | None:
        """Why the runtime cannot take *service*, or None."""
        if self._closing:
            return RuntimeError(f"runtime '{self._name}' is not running")
        if service.name in self._runners:
            return ValueError(f"service '{service.name}' is in the runtime already")
        cycle = self._deps.cycle(service)
        return CycleError(cycle) if cycle is not None else None

    def _start_waiters(self, name: str) -> None:
        """Start the services waiting on *name* whose dependencies all run."""
        if self._closing:
            return
        for waiter in self._deps.released(name):
            self._begin(self._runners[waiter])

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
        fail, as it will not run for them, and leave in turn.

        A worklist, not recursion: a chain of waiters is as long as it is. A
        waiter can be reached twice, through two of its dependencies; once
        gone, it is skipped."""
        work = [runner]
        while work:
            left = work.pop()
            if self._runners.get(left.name) is not left:
                continue
            for waiter in self._drop(left):
                if self._runners.get(waiter.name) is waiter and waiter not in work:
                    self._fail(waiter, DependencyFailedError(waiter.name, left.name))
                    waiter._move(State.FAILED)  # never started: CREATED -> FAILED
                    work.append(waiter)

    def _drop(self, runner: Runner) -> list[Runner]:
        """Take *runner* out of the runtime and answer its ready() calls;
        return the services that were waiting on it. Its token ends here too:
        one that left without a run (refused, failed setup, a dependency gone)
        never had it ended, and ending it again is a no-op."""
        name = runner.name
        waiting = [self._runners[w] for w in self._deps.drop(name)]
        _end_token(runner)
        del self._runners[name]
        self._restarting.discard(name)
        self._expired.discard(runner)
        self._isolated.discard(runner)
        if runner in self._ready:
            outcome = None if runner.state in UP else _startup_error(runner)
            for reply in self._ready.pop(runner):
                _reply(reply, outcome)
        return waiting


_HANDLERS: dict[type, Callable[[Owner, Any], None]] = {
    Spawn: Owner._on_spawn,
    Ready: Owner._on_ready,
    GiveUp: Owner._on_give_up,
    StopService: Owner._on_stop_service,
    Stop: Owner._on_stop,
    Services: Owner._on_services,
    TaskDone: Owner._on_task_done,
}

_STEPS: dict[str, Callable[[Owner, Runner, TaskDone], None]] = {
    "setup": Owner._on_setup,
    "run": Owner._on_run,
    "teardown": Owner._on_teardown,
    "health": Owner._on_health,
    "backoff": Owner._on_backoff,
    "deadline": Owner._on_deadline,
}


def _current(runner: Runner, m: TaskDone) -> bool:
    """True if *m* ends *runner*'s current setup or run, not an older one."""
    return runner._task is not None and runner._task.id == m.task_id


def _in_setup(runner: Runner) -> bool:
    """True while *runner*'s current step is its setup()."""
    task = runner._task
    return task is not None and (task.name or "").endswith("/setup")


def _end_token(runner: Runner) -> None:
    """The service will not run on: stop its token, so work started on it
    ends before teardown() waits for it, and detach it from the root's."""
    token = runner.service.stopping
    token.stop()
    token.detach()


def _overrides(service: Service, method: str) -> bool:
    """True if *service* overrides Service.*method*: the default does nothing,
    and needs no task to run it."""
    return getattr(type(service), method) is not getattr(Service, method)


def _setup_error(runner: Runner, error: BaseException) -> BaseException:
    """What *runner*'s setup task ended with, as a SetupError: a stop or a
    non-Exception stays as it is."""
    if isinstance(error, StoppedError) or not isinstance(error, Exception):
        return error
    return SetupError.of(runner.name, error)


def _poll_health(service: Service) -> bool:
    """Health task: ask is_healthy() every _HEALTH_INTERVAL seconds, waiting on
    this task's token, which the run's ends.

    Returns:
        True once healthy; False if the run ended first.
    """
    token = this_task().token
    while not token.is_set():
        if service.is_healthy():
            return True
        token.wait(_HEALTH_INTERVAL)
    return False


def _back_off(delay: float) -> None:
    """Backoff and deadline task: wait out *delay* seconds, unless this task's
    token stops first.

    Raises:
        StoppedError: If stopped first, as a stopped task ends.
    """
    if this_task().token.wait(delay):
        raise StoppedError()


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
