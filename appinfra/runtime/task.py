# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Task - one call of a function, on the runtime's loop or a thread of its own."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from .loop import LoopHost
from .stop import StopToken

# The task the code runs in. An asyncio task copies the context it is created
# with; a thread task sets it on its own thread.
_current: contextvars.ContextVar[Task] = contextvars.ContextVar("appinfra_runtime_task")


def _running(caller: str) -> Task:
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
    return _running("task_id").task_id


def current_task() -> Task | None:
    """The task the caller runs in, or None outside a task."""
    return _current.get(None)


def _name(task_id: int) -> str:
    """The name of a task's thread or asyncio task: prefixed, so a thread dump
    shows whose it is, and carrying the id the runtime's log records carry."""
    return f"appinfra-task-{task_id}"


class Task(ABC):
    """One call of a function, run once, known by its id. Its token derives
    from the token of the task that spawned it, or from the runtime's; it stops
    when the call ends, and leaves its parent's tree then.

    A failure ends this task only; it is kept in ``exception``. A task is not
    restarted.
    """

    def __init__(
        self,
        task_id: int,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
        on_end: Callable[[Task], None],
    ) -> None:
        """Initialize task.

        Args:
            task_id: The id the runtime assigned.
            fn: The function to call.
            args: Its arguments.
            token: The task's token, derived from its parent's.
            on_end: Called once the call has ended, on the thread that ran it.
        """
        self.task_id = task_id
        self.token = token
        self._fn = fn
        self._args = args
        self._on_end = on_end
        self._result: Any = None
        self._exception: BaseException | None = None
        # Set by the runtime, under its lock
        self.ended = False  # the call has ended
        self.detached = False  # nobody waits: reaped as soon as it ends

    @abstractmethod
    def _launch(self) -> None:
        """Start the call; called once, by the runtime."""

    @abstractmethod
    def cancel(self) -> None:
        """Stop the task's token and, on the loop, cancel it; returns at once."""

    @abstractmethod
    def wait(self, timeout: float | None = None) -> bool:
        """Wait up to *timeout* seconds for the call to end.

        Returns:
            False if it is still running after *timeout*.
        """

    @abstractmethod
    def is_alive(self) -> bool:
        """True while the call has not ended."""

    @property
    def result(self) -> Any:
        """What the call returned; None while it runs, or if it failed."""
        return self._result

    @property
    def exception(self) -> BaseException | None:
        """Exception from the call, if any."""
        return self._exception

    def _end(self) -> None:
        """Once the call has ended: stop the token, so work derived from it is
        told to stop, and leave the parent's tree."""
        self.token.stop()
        self.token.detach()
        self._on_end(self)


class ThreadTask(Task):
    """Calls a function on a daemon thread of its own. A thread cannot be
    interrupted: the function sees its token (``stopping()``) and returns."""

    def __init__(
        self,
        task_id: int,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
        on_end: Callable[[Task], None],
    ) -> None:
        """Initialize task; see Task."""
        super().__init__(task_id, fn, args, token, on_end)
        self._thread: threading.Thread | None = None
        # Set by _run() as its last step. Thread.is_alive() on Python 3.13+
        # stays True until the OS thread handle is marked done, after the GIL
        # is released, so it alone can report an ended call as running
        self._done = False

    def _launch(self) -> None:
        """Start the task's thread."""
        self._thread = threading.Thread(
            target=self._run, name=_name(self.task_id), daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        """Thread target: call the function with the task current."""
        try:
            _current.set(self)
            try:
                self._result = self._fn(*self._args)
            except BaseException as e:
                self._exception = e
            self._end()
        finally:
            # Last, so the outcome is settled before is_alive() reports the end
            self._done = True

    def cancel(self) -> None:
        """Stop the task's token; the function sees it and returns."""
        self.token.stop()

    def wait(self, timeout: float | None = None) -> bool:
        """Join the task's thread for up to *timeout* seconds.

        Raises:
            RuntimeError: If called on the task's own thread, which would wait
                for itself.
        """
        thread = self._thread
        if thread is threading.current_thread():
            raise RuntimeError(f"task {self.task_id} cannot wait for itself")
        if thread is not None:
            thread.join(timeout)
        return not self.is_alive()

    def is_alive(self) -> bool:
        """True while the task's thread has not finished the call."""
        thread = self._thread
        return thread is not None and not self._done and thread.is_alive()


class LoopTask(Task):
    """Runs an async function as a task on a LoopHost's loop, so one waiting on
    an await holds no thread. cancel() raises CancelledError at the await it is
    parked on; a cancel ends it cleanly."""

    def __init__(
        self,
        host: LoopHost,
        task_id: int,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
        on_end: Callable[[Task], None],
    ) -> None:
        """Initialize task on *host*'s loop; see Task for the rest."""
        super().__init__(task_id, fn, args, token, on_end)
        self._host = host
        # Held here: the loop keeps only a weak reference to a task
        self._task: asyncio.Task[None] | None = None
        self._done = False
        # Events of wait() calls waiting for the task to end; loop thread only
        self._waiters: list[threading.Event] | None = None

    def _launch(self) -> None:
        """Schedule the task's creation on the loop.

        Raises:
            RuntimeError: If the host is not running, or is stopping.
        """
        self._host._schedule(self._spawn)

    def _spawn(self) -> None:
        """Create the asyncio task; called on the loop. _finish() runs when it
        ends, however it ends: also when cancelled before its first step, when
        the call never runs."""
        context = contextvars.copy_context()
        context.run(_current.set, self)
        task = asyncio.get_running_loop().create_task(
            self._call(), name=_name(self.task_id), context=context
        )
        task.add_done_callback(self._finish)
        self._task = task

    async def _call(self) -> None:
        """The call, unless a cancel came first. A cancel, from cancel() or the
        host shutting down, ends it cleanly; any other exception is kept."""
        if self.token.is_set():
            return
        try:
            self._result = await self._fn(*self._args)
        except asyncio.CancelledError:
            pass
        except BaseException as e:
            self._exception = e

    def _finish(self, task: asyncio.Task[None]) -> None:
        """On the loop, once the task has ended: end it and wake the wait()
        calls waiting for it."""
        self._task = None
        waiters, self._waiters = self._waiters, None
        self._end()
        # Last, so the outcome is settled before is_alive() reports the end
        self._done = True
        for waiter in waiters or ():
            waiter.set()

    def cancel(self) -> None:
        """Stop the task's token and cancel it on the loop. A task not begun
        yet sees the token and skips the call."""
        self.token.stop()
        # RuntimeError: the host stopped, and its shutdown ended the task
        with contextlib.suppress(RuntimeError):
            self._host.loop.call_soon_threadsafe(self._cancel)

    def _cancel(self) -> None:
        """On the loop: cancel the asyncio task, if it is still running."""
        if self._task is not None:
            self._task.cancel()

    def wait(self, timeout: float | None = None) -> bool:
        """Wait up to *timeout* seconds for the task to end.

        Raises:
            RuntimeError: If called on the loop thread while the task runs,
                which the wait would block.
        """
        if not self.is_alive():
            return True
        if self._host.on_loop_thread():
            raise RuntimeError(
                f"waiting for task {self.task_id} on the loop would block it"
            )
        ended = threading.Event()
        try:
            self._host.loop.call_soon_threadsafe(self._watch, ended)
        except RuntimeError:
            return True  # Host stopped: its shutdown ended the task
        return ended.wait(timeout)

    def _watch(self, ended: threading.Event) -> None:
        """On the loop: set *ended* once the task has ended."""
        if not self.is_alive():
            ended.set()
            return
        if self._waiters is None:
            self._waiters = []
        self._waiters.append(ended)

    def is_alive(self) -> bool:
        """True until the asyncio task has ended."""
        return not self._done
