# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A task: the Task handle its caller holds, and the runtime's side of it, the
one call of a function it runs and keeps the outcome of. The kinds of task,
by where the call runs, are in thread.py, loop.py and process.py."""

from __future__ import annotations

import contextlib
import contextvars
import enum
import functools
import weakref
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine, Generator
from dataclasses import dataclass
from types import CodeType, FunctionType, TracebackType
from typing import Any, Protocol, final

from .errors import StoppedError
from .stop import StopToken


@dataclass(frozen=True, slots=True)
class _Running:
    """The task the code runs in, as its context holds it: its id and token,
    and the task itself only weakly. The context is the task's own
    (_Task._context): holding the task, it would make a cycle with it, and
    what the task keeps, its error and the frames on that, would wait for
    the cyclic GC."""

    id: int
    token: StopToken
    task: weakref.ReferenceType[_Task]


# The task the code runs in: set in the task's own context (_Task.__init__)
_current: contextvars.ContextVar[_Running] = contextvars.ContextVar(
    "appinfra_runtime_task"
)


def _running(caller: str) -> _Running:
    """The task the caller runs in.

    Raises:
        RuntimeError: If called outside a task.
    """
    try:
        return _current.get()
    except LookupError:
        raise RuntimeError(f"{caller}() called outside a task") from None


def stopping() -> StopToken:
    """The token of the task the caller runs in: stopped when the task is
    cancelled or the runtime stops.

    Raises:
        RuntimeError: If called outside a task.
    """
    return _running("stopping").token


def task_id() -> int:
    """The id of the task the caller runs in.

    Raises:
        RuntimeError: If called outside a task.
    """
    return _running("task_id").id


def _current_token() -> StopToken | None:
    """The token of the task the caller runs in, or None outside a task."""
    running = _current.get(None)
    return None if running is None else running.token


def _in_task(t: _Task) -> bool:
    """True if the caller runs in *t*: on its thread, or in work handed its
    context."""
    running = _current.get(None)
    return running is not None and running.task() is t


def _past_own_frames(e: BaseException, task: _Task) -> TracebackType | None:
    """*e*'s traceback from its first frame that is not one of *task*'s own
    methods, set on *e* as well; the frames left out are cleared, but for
    the one still running. Those frames hold the task (``self``) and the
    call's arguments: kept with the task's error, directly or through the
    call's frame linking back to them (f_back), they would make a cycle that
    holds the arguments until the cyclic GC runs."""
    own = _own_codes(type(task))
    tb = e.__traceback__
    while tb is not None and tb.tb_frame.f_code in own:
        with contextlib.suppress(RuntimeError):  # still running: _run()
            tb.tb_frame.clear()
        tb = tb.tb_next
    e.__traceback__ = tb
    return tb


@functools.cache
def _own_codes(cls: type[_Task]) -> frozenset[CodeType]:
    """The code of the methods a task of class *cls* runs its call through.
    Told apart by code, not by the frame's ``self``: reading the locals of a
    running frame (f_locals) keeps a copy of them in it, before 3.13."""
    return frozenset(
        f.__code__
        for k in cls.__mro__
        if issubclass(k, _Task)
        for f in vars(k).values()
        if isinstance(f, FunctionType)
    )


@dataclass(frozen=True)
class TaskDone:
    """How a task ended, as spawn() sends it on *done*, once per task: what
    its call returned, or *error*, the way wait() would raise it: what the
    call raised, or StoppedError when its stop ended it without a result.
    *name* is spawn()'s, if one was given."""

    task_id: int
    name: str | None
    result: Any
    error: BaseException | None


class TaskKind(enum.Enum):
    """What a task runs as, fixed when it is spawned: a coroutine on the
    runtime's loop, a call on a thread of its own, or a call in a child
    process (spawn(process=True))."""

    LOOP = "loop"
    THREAD = "thread"
    PROCESS = "process"


@dataclass(frozen=True, slots=True)
class ProcessDetail:
    """A process task's child as last seen: its pid (None until it has
    started), its exit code (None while it runs; negative, the signal's
    number, for one a signal ended) and whether it is alive."""

    pid: int | None
    exitcode: int | None
    alive: bool


class _TaskOps(Protocol):
    """What a Task needs of the runtime that runs it: its waits, detach and
    stop, which take the runtime's lock and table of tasks. A protocol, so
    this module need not import the runtime, which imports it."""

    def _wait(self, t: _Task, timeout: float | None) -> Any: ...

    def _await(self, t: _Task) -> Coroutine[Any, Any, Any]: ...

    def _detach(self, t: _Task) -> None: ...

    def _stop(self, t: _Task, timeout: float) -> None: ...


@final
class Task:
    """A task, as spawn() returns it: what its caller waits on and cancels it
    with. The task itself is the runtime's, which may run it anywhere; this
    handle is all of it the caller sees. Waited for with ``wait()`` in
    blocking code and ``await task`` in a coroutine, as often as wanted; it
    keeps the outcome as long as it is held. Not to be subclassed."""

    __slots__ = ("_rt", "_t")
    _rt: _TaskOps
    _t: _Task

    def __init__(self) -> None:
        """Refused: a Task comes from Runtime.spawn(), as re.Match from a
        pattern.

        Raises:
            TypeError: Always.
        """
        raise TypeError("a Task comes from Runtime.spawn()")

    @classmethod
    def _of(cls, rt: _TaskOps, t: _Task) -> Task:
        """The handle to *t*, run by *rt*; for Runtime.spawn()."""
        task = object.__new__(cls)
        task._rt = rt
        task._t = t
        return task

    @property
    def id(self) -> int:
        """The id the runtime assigned, never reused; a TaskDone carries it."""
        return self._t.id

    @property
    def name(self) -> str | None:
        """spawn()'s name, if one was given; a TaskDone carries it."""
        return self._t.name

    def wait(self, timeout: float | None = None) -> Any:
        """Wait up to *timeout* seconds for the task to end.

        Returns:
            What the task's function returned.

        Raises:
            RuntimeError: If the task is detached, or the wait would block the
                runtime's loop or the task's own thread.
            TimeoutError: If the task is still running after *timeout*.
            StoppedError: If the task was stopped before it returned: its call
                was skipped, cancelled, or ended by a wait the stop ended. A
                function that sees the stop and returns gives its result.
            BaseException: Whatever the task's function raised.
        """
        return self._rt._wait(self._t, timeout)

    def __await__(self) -> Generator[Any, None, Any]:
        """``await task``: wait(), on any event loop, which runs meanwhile.
        Bounded with ``asyncio.wait_for(task, timeout)``; cancelled, it
        leaves nothing behind. Raises as wait(), except RuntimeError for
        blocking: the loop runs on."""
        return self._rt._await(self._t).__await__()

    def cancel(self) -> None:
        """Stop the task's token and, on the loop, cancel it; returns at once.
        A task on a thread sees its token and returns."""
        self._t.cancel()

    def stop(self, timeout: float) -> None:
        """cancel(), and for a process task, an end within *timeout* seconds:
        a child still running then gets SIGTERM, and SIGKILL a grace later.
        A task on the loop or a thread cannot be forced: its token is all a
        stop has. Returns at once.

        Raises:
            ValueError: If *timeout* is negative.
        """
        if timeout < 0:
            raise ValueError(f"timeout must not be negative: {timeout}")
        self._rt._stop(self._t, timeout)

    def alive(self) -> bool:
        """True while the task has not ended."""
        return not self._t.ended

    @property
    def kind(self) -> TaskKind:
        """What the task runs as: on the loop, on a thread, or in a process."""
        return self._t.kind

    @property
    def process(self) -> TaskProcess | None:
        """The child process of a task spawned with process=True: its detail,
        and the signals that end it; None for a task on the loop or a thread."""
        if self._t.kind is not TaskKind.PROCESS:
            return None
        return TaskProcess._of(self._t)

    def detach(self) -> None:
        """Give up waiting for the task: its failure is logged, as nobody
        else sees it; now, if it has ended already."""
        self._rt._detach(self._t)

    def __repr__(self) -> str:
        """``<Task 7 running>``, or ``<Task 7 db running>`` with its name."""
        who = self.id if self.name is None else f"{self.id} {self.name}"
        return f"<Task {who} {'running' if self.alive() else 'ended'}>"


@final
class TaskProcess:
    """A process task's child, as Task.process gives it: what it is, and the
    signals that end it. A signal sent before the child has started reaches
    it once it has. Not to be subclassed."""

    __slots__ = ("_t",)
    _t: _Task

    def __init__(self) -> None:
        """Refused: a TaskProcess comes from Task.process.

        Raises:
            TypeError: Always.
        """
        raise TypeError("a TaskProcess comes from Task.process")

    @classmethod
    def _of(cls, t: _Task) -> TaskProcess:
        """The process of the process task *t*; for Task.process."""
        process = object.__new__(cls)
        process._t = t
        return process

    def detail(self) -> ProcessDetail:
        """The child as it is now, or as it ended: read anew on each call."""
        return self._t.process_detail()

    @property
    def grace(self) -> float:
        """Seconds past a stop's timeout that forcing the child can take:
        SIGTERM, SIGKILL a grace later, and a grace more for the reap. A stop
        with *timeout* has run its course *timeout* + grace seconds on."""
        return self._t.grace()

    def terminate(self) -> None:
        """Send the child SIGTERM, now or once it has started; returns at once."""
        self._t.terminate()

    def kill(self) -> None:
        """Send the child SIGKILL, now or once it has started; returns at once."""
        self._t.kill()


def _label(task_id: int, name: str | None) -> str:
    """The name of a task's thread or asyncio task: prefixed, so a thread dump
    shows whose it is, and carrying the id the runtime's log records carry."""
    label = f"appinfra-task-{task_id}"
    return label if name is None else f"{label}-{name}"


class _Task(ABC):
    """One call of a function, run once.

    Its token derives from the token of the task that spawned it, or from the
    runtime's; it stops when the call ends, and leaves its parent's tree then.
    A failure ends this task only. A task is not restarted.

    A task ended by its stop has no result. Its call was skipped, or ended
    with the stop's own signal (*stop_signals*) while its token was stopped;
    the same signal raised while the token runs is a failure. A function that
    sees the stop and returns ends with its result.

    It runs in a copy of the spawner's contextvars, taken as it is made, as
    asyncio's create_task() and to_thread() do: it sees the spawner's values,
    and what it sets stays its own.

    The runtime uses what has no underscore. It sets *ended*, *detached*,
    *wakes* and *done_chan* under its lock; the task sets the outcome before
    it reports its end.
    """

    # Slots, not an instance dict: a runtime holds one of these per task
    __slots__ = (
        "id",
        "name",
        "token",
        "_on_end",
        "_fn",
        "_args",
        "_context",
        "result",
        "exception",
        "exception_tb",
        "stopped",
        "ended",
        "detached",
        "wakes",
        "done_chan",
        "__weakref__",  # its context's _Running holds it weakly
    )

    # What a stop ends a call with, on this kind of task
    stop_signals: tuple[type[BaseException], ...] = (StoppedError,)

    # Whether terminate() and kill() can end a call this kind of task runs: a
    # thread and the loop cannot be killed, a process can
    killable = False

    # What this kind of task runs as; each kind sets its own
    kind: TaskKind

    def __init__(
        self,
        on_end: Callable[[_Task], None],
        task_id: int,
        name: str | None,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
    ) -> None:
        """Initialize task, on the spawner's thread.

        Args:
            on_end: The runtime's report of the end, once the call has ended.
            task_id: The id the runtime assigned.
            name: spawn()'s name, if one was given.
            fn: The function to call.
            args: Its arguments.
            token: The task's token, derived from its parent's.
        """
        self.id = task_id
        self.name = name
        self.token = token
        self._on_end = on_end
        # Until the call takes them (_take_call())
        self._fn: Callable[..., Any] | None = fn
        self._args = args
        # The context the call runs in, with the task current in it
        self._context = contextvars.copy_context()
        self._context.run(_current.set, _Running(task_id, token, weakref.ref(self)))
        # The outcome
        self.result: Any = None
        self.exception: BaseException | None = None
        # The exception's own traceback: each wait raises it from there
        self.exception_tb: TracebackType | None = None
        self.stopped = False
        # The runtime's
        self.ended = False  # the call has ended
        self.detached = False  # nobody waits: a failure is logged or sent
        # Wakes the awaits waiting for the end; created by the first, as
        # most tasks are not awaited
        self.wakes: list[Callable[[], None]] | None = None
        # spawn()'s done Chan: typed in Runtime.spawn(), as chan imports this
        # module
        self.done_chan: Any = None

    def _take_call(self) -> tuple[Callable[..., Any], tuple[Any, ...]]:
        """The function and its arguments, no longer held here: the call's
        frame holds them while it runs, and a parked task keeps no copy."""
        fn, args = self._fn, self._args
        assert fn is not None, "a task's function is called once"
        self._fn, self._args = None, ()
        return fn, args

    @abstractmethod
    def launch(self) -> None:
        """Start the call; called once, by the runtime."""

    @abstractmethod
    def cancel(self) -> None:
        """Stop the task's token and, on the loop, cancel it; returns at once."""

    @abstractmethod
    def join(self, timeout: float | None = None) -> bool:
        """Block up to *timeout* seconds for the call to end.

        Returns:
            False if it is still running after *timeout*.
        """

    @abstractmethod
    def is_running(self) -> bool:
        """True while the call has not ended."""

    def terminate(self) -> None:
        """Ask a call that outlived the runtime's stop to end now, if this kind
        of task is killable; returns at once."""

    def kill(self) -> None:
        """End a call that outlived terminate(), if this kind of task is
        killable; returns at once."""

    def process_detail(self) -> ProcessDetail:
        """The child of a process task, which overrides this; reached through
        Task.process, which only a process task has.

        Raises:
            TypeError: For a task of another kind.
        """
        raise TypeError(f"task {self.id} runs as {self.kind.value}, not a process")

    def grace(self) -> float:
        """The forcing grace of a process task, which overrides this.

        Raises:
            TypeError: For a task of another kind.
        """
        raise TypeError(f"task {self.id} runs as {self.kind.value}, not a process")

    def _raised(self, e: BaseException) -> None:
        """Record how the call ended on *e*: a stop if it is the stop's own
        signal and the token is stopped, a failure otherwise. StopIteration
        becomes a RuntimeError caused by it, as a coroutine's does (PEP 479):
        wait() and await raise the same, from either kind of task. The
        traceback kept leaves out the task's own frames (_past_own_frames())."""
        if isinstance(e, self.stop_signals) and self.token.is_set():
            self.stopped = True
        elif isinstance(e, StopIteration):
            _past_own_frames(e, self)
            error = RuntimeError(f"task {self.id} raised StopIteration")
            error.__cause__ = e
            self.exception = error
        else:
            self.exception = e
            self.exception_tb = _past_own_frames(e, self)

    def _end(self) -> None:
        """Once the call has ended: stop the token, so work derived from it is
        told to stop, leave the parent's tree, and report the end."""
        self.token.stop()
        self.token.detach()
        self._on_end(self)
