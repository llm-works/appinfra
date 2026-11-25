# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The runtime's side of a task: what runs one call of a function, on the
runtime's loop or a thread of its own, and keeps its outcome. The caller holds
a Task (runtime.py) and reaches this only through it."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any

from .errors import StoppedError
from .loop import LoopHost
from .stop import StopToken

# The task the code runs in: set in the task's own context (_Task.__init__)
_current: contextvars.ContextVar[_Task] = contextvars.ContextVar(
    "appinfra_runtime_task"
)


def _running(caller: str) -> _Task:
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


def _current_task() -> _Task | None:
    """The task the caller runs in, or None outside a task."""
    return _current.get(None)


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

    # What a stop ends a call with, on this kind of task
    stop_signals: tuple[type[BaseException], ...] = (StoppedError,)

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
        self._fn = fn
        self._args = args
        # The context the call runs in, with the task current in it
        self._context = contextvars.copy_context()
        self._context.run(_current.set, self)
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
        # spawn()'s done, a Chan or a pipe's Sender: typed in Runtime.spawn(),
        # as chan imports this module
        self.done_chan: Any = None

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

    def _raised(self, e: BaseException) -> None:
        """Record how the call ended on *e*: a stop if it is the stop's own
        signal and the token is stopped, a failure otherwise. StopIteration
        becomes a RuntimeError caused by it, as a coroutine's does (PEP 479):
        wait() and await raise the same, from either kind of task."""
        if isinstance(e, self.stop_signals) and self.token.is_set():
            self.stopped = True
        elif isinstance(e, StopIteration):
            error = RuntimeError(f"task {self.id} raised StopIteration")
            error.__cause__ = e
            self.exception = error
        else:
            self.exception = e
            self.exception_tb = e.__traceback__

    def _end(self) -> None:
        """Once the call has ended: stop the token, so work derived from it is
        told to stop, leave the parent's tree, and report the end."""
        self.token.stop()
        self.token.detach()
        self._on_end(self)


class _ThreadTask(_Task):
    """Calls a function on a daemon thread of its own. A thread cannot be
    interrupted: the function sees its token (``stopping()``) and returns."""

    def __init__(
        self,
        on_end: Callable[[_Task], None],
        task_id: int,
        name: str | None,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
    ) -> None:
        """Initialize task; see _Task."""
        super().__init__(on_end, task_id, name, fn, args, token)
        self._thread: threading.Thread | None = None
        # Set by _run() as its last step. Thread.is_alive() on Python 3.13+
        # stays True until the OS thread handle is marked done, after the GIL
        # is released, so it alone can report an ended call as running
        self._finished = False

    def launch(self) -> None:
        """Start the task's thread."""
        self._thread = threading.Thread(
            target=self._context.run,
            args=(self._run,),
            name=_label(self.id, self.name),
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        """Thread target, in the task's context: call the function, unless
        its token was stopped before the thread got here, as on the loop."""
        try:
            if self.token.is_set():
                self.stopped = True
            else:
                try:
                    self.result = self._fn(*self._args)
                except BaseException as e:
                    self._raised(e)
            self._end()
        finally:
            # Last, so the outcome is settled before is_running() reports the
            # end
            self._finished = True

    def cancel(self) -> None:
        """Stop the task's token; the function sees it and returns."""
        self.token.stop()

    def join(self, timeout: float | None = None) -> bool:
        """Join the task's thread for up to *timeout* seconds.

        Raises:
            RuntimeError: If called on the task's own thread, which would wait
                for itself.
        """
        thread = self._thread
        if thread is threading.current_thread():
            raise RuntimeError(f"task {self.id} cannot wait for itself")
        if thread is not None:
            thread.join(timeout)
        return not self.is_running()

    def is_running(self) -> bool:
        """True while the task's thread has not finished the call."""
        thread = self._thread
        return thread is not None and not self._finished and thread.is_alive()


class _LoopTask(_Task):
    """Runs an async function as a task on a LoopHost's loop, so one waiting on
    an await holds no thread. cancel() raises CancelledError at the await it is
    parked on; a cancel is a stop."""

    stop_signals = (asyncio.CancelledError, StoppedError)

    def __init__(
        self,
        on_end: Callable[[_Task], None],
        host: LoopHost,
        task_id: int,
        name: str | None,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
    ) -> None:
        """Initialize task on *host*'s loop; see _Task for the rest."""
        super().__init__(on_end, task_id, name, fn, args, token)
        self._host = host
        # Held here: the loop keeps only a weak reference to a task
        self._aio: asyncio.Task[None] | None = None
        self._finished = False
        # Events of join() calls waiting for the task to end; loop thread only
        self._waiters: list[threading.Event] | None = None

    def launch(self) -> None:
        """Schedule the task's creation on the loop.

        Raises:
            RuntimeError: If the host is not running, or is stopping.
        """
        self._host._schedule(self._spawn)

    def _spawn(self) -> None:
        """Create the asyncio task, in the task's context; called on the loop.
        _finish() runs when it ends, however it ends: also when cancelled
        before its first step, when the call never runs."""
        aio = asyncio.get_running_loop().create_task(
            self._call(), name=_label(self.id, self.name), context=self._context
        )
        aio.add_done_callback(self._finish)
        self._aio = aio

    async def _call(self) -> None:
        """The call, unless a stop came first. A cancel, from cancel() or the
        host shutting down, comes with the token stopped: it is a stop."""
        if self.token.is_set():
            self.stopped = True
            return
        try:
            self.result = await self._fn(*self._args)
        except BaseException as e:
            self._raised(e)

    def _finish(self, aio: asyncio.Task[None]) -> None:
        """On the loop, once the asyncio task has ended: end the task and wake
        the join() calls waiting for it."""
        self._aio = None
        waiters, self._waiters = self._waiters, None
        # Cancelled before its first step: _call() never ran to record it.
        # _call() catches everything, so a task that ran is never cancelled
        if aio.cancelled():
            self.stopped = True
        self._end()
        # Last, so the outcome is settled before is_running() reports the end
        self._finished = True
        for waiter in waiters or ():
            waiter.set()

    def cancel(self) -> None:
        """Stop the task's token and cancel it on the loop. A task not begun
        yet sees the token and skips the call. Ctrl-C during the stop reaches
        the caller once the cancel is scheduled."""
        try:
            self.token.stop()
        finally:
            # RuntimeError: the host stopped, and its shutdown ended the task
            with contextlib.suppress(RuntimeError):
                self._host.loop.call_soon_threadsafe(self._cancel)

    def _cancel(self) -> None:
        """On the loop: cancel the asyncio task, if it is still running."""
        if self._aio is not None:
            self._aio.cancel()

    def join(self, timeout: float | None = None) -> bool:
        """Block up to *timeout* seconds for the task to end.

        Raises:
            RuntimeError: If called on the loop thread while the task runs,
                which the wait would block.
        """
        if not self.is_running():
            return True
        if self._host.on_loop_thread():
            raise RuntimeError(f"waiting for task {self.id} on the loop would block it")
        ended = threading.Event()
        try:
            self._host.loop.call_soon_threadsafe(self._watch, ended)
        except RuntimeError:
            return True  # Host stopped: its shutdown ended the task
        if ended.wait(timeout):
            return True
        # Timed out: drop the registration, or every poll would leave one
        with contextlib.suppress(RuntimeError):  # Host stopped: nothing to drop
            self._host.loop.call_soon_threadsafe(self._unwatch, ended)
        return False

    def _watch(self, ended: threading.Event) -> None:
        """On the loop: set *ended* once the task has ended."""
        if not self.is_running():
            ended.set()
            return
        if self._waiters is None:
            self._waiters = []
        self._waiters.append(ended)

    def _unwatch(self, ended: threading.Event) -> None:
        """On the loop: forget *ended*, whose wait timed out; once the task has
        ended, _finish() has cleared the list already."""
        if self._waiters is not None and ended in self._waiters:
            self._waiters.remove(ended)

    def is_running(self) -> bool:
        """True until the asyncio task has ended."""
        return not self._finished
