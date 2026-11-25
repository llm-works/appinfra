# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Task - one call of a function, on the runtime's loop or a thread of its own."""

from __future__ import annotations

import asyncio
import contextvars
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from .loop import LoopHost
from .stop import StopToken

# The token of the task the code runs in. An asyncio task copies the context it
# is created with; a thread task sets it on its own thread.
_current: contextvars.ContextVar[StopToken] = contextvars.ContextVar(
    "appinfra_runtime_task_token"
)


def stopping() -> StopToken:
    """The token of the task the caller runs in: stopped when the task is
    stopped or the runtime stops.

    Raises:
        RuntimeError: If called outside a task.
    """
    try:
        return _current.get()
    except LookupError:
        raise RuntimeError("stopping() called outside a task") from None


def current_token() -> StopToken | None:
    """The token of the task the caller runs in, or None outside a task."""
    return _current.get(None)


class Task(ABC):
    """One call of a function, run once. Its token derives from the token of
    the task that spawned it, or from the runtime's; it stops when the call
    ends, and leaves its parent's tree then.

    A failure ends this task only; it is kept in ``exception``. A task is not
    restarted.
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
        on_end: Callable[[Task], None],
    ) -> None:
        """Initialize task.

        Args:
            fn: The function to call.
            args: Its arguments.
            token: The task's token, derived from its parent's.
            on_end: Called once the call has ended, on the thread that ran it.
        """
        self.name: str = getattr(fn, "__name__", type(fn).__name__)
        self.token = token
        self._fn = fn
        self._args = args
        self._on_end = on_end
        self._result: Any = None
        self._exception: BaseException | None = None

    @abstractmethod
    def _launch(self) -> None:
        """Start the call; called once, by the runtime."""

    @abstractmethod
    def stop(self, timeout: float = 5.0) -> bool:
        """Stop the task's token and wait up to *timeout* seconds for the call
        to end.

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
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
        on_end: Callable[[Task], None],
    ) -> None:
        """Initialize task; see Task."""
        super().__init__(fn, args, token, on_end)
        self._thread: threading.Thread | None = None
        # Set by _run() as its last step. Thread.is_alive() on Python 3.13+
        # stays True until the OS thread handle is marked done, after the GIL
        # is released, so it alone can report an ended call as running
        self._ended = False

    def _launch(self) -> None:
        """Start the task's thread."""
        self._thread = threading.Thread(
            target=self._run, name=f"task-{self.name}", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        """Thread target: call the function with the task's token current."""
        try:
            _current.set(self.token)
            try:
                self._result = self._fn(*self._args)
            except BaseException as e:
                self._exception = e
            self._end()
        finally:
            # Last, so the outcome is settled before is_alive() reports the end
            self._ended = True

    def stop(self, timeout: float = 5.0) -> bool:
        """Stop the task's token and join its thread for up to *timeout*
        seconds; on the task's own thread, nothing is joined."""
        self.token.stop()
        thread = self._thread
        if thread is None or thread is threading.current_thread():
            return not self.is_alive()
        thread.join(timeout)
        return not self.is_alive()

    def is_alive(self) -> bool:
        """True while the task's thread has not finished the call."""
        thread = self._thread
        return thread is not None and not self._ended and thread.is_alive()


class LoopTask(Task):
    """Runs an async function as a task on a LoopHost's loop, so one waiting on
    an await holds no thread. stop() cancels it, raising CancelledError at the
    await it is parked on; a cancel ends it cleanly."""

    def __init__(
        self,
        host: LoopHost,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        token: StopToken,
        on_end: Callable[[Task], None],
    ) -> None:
        """Initialize task on *host*'s loop; see Task for the rest."""
        super().__init__(fn, args, token, on_end)
        self._host = host
        # Held here: the loop keeps only a weak reference to a task
        self._task: asyncio.Task[None] | None = None
        self._ended = False
        # Events of stop() calls waiting for the task to end; loop thread only
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
        context.run(_current.set, self.token)
        task = asyncio.get_running_loop().create_task(
            self._call(), name=f"task-{self.name}", context=context
        )
        task.add_done_callback(self._finish)
        self._task = task
        self._host._tokens.add(self.token)

    async def _call(self) -> None:
        """The call, unless a stop came first. A cancel, from stop() or the
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
        """On the loop, once the task has ended: end it and wake the stop()
        calls waiting for it."""
        self._host._tokens.discard(self.token)
        self._task = None
        waiters, self._waiters = self._waiters, None
        self._end()
        self._ended = True
        for waiter in waiters or ():
            waiter.set()

    def stop(self, timeout: float = 5.0) -> bool:
        """Cancel the task and wait up to *timeout* seconds for it to end.

        Raises:
            RuntimeError: If called on the loop thread while the task runs,
                which the wait would block.
        """
        # Before the cancel: a task not begun yet sees it and skips the call
        self.token.stop()
        if not self.is_alive():
            return True
        if self._host.on_loop_thread():
            raise RuntimeError("LoopTask.stop() on the loop thread would block it")
        ended = threading.Event()
        try:
            self._host.loop.call_soon_threadsafe(self._cancel, ended)
        except RuntimeError:
            return True  # Host stopped: its shutdown ended the task
        return ended.wait(timeout)

    def _cancel(self, ended: threading.Event) -> None:
        """On the loop: set *ended* once the task has ended, and cancel it. A
        task not created yet sees the stopped token and skips the call."""
        if not self.is_alive():
            ended.set()
            return
        if self._waiters is None:
            self._waiters = []
        self._waiters.append(ended)
        if self._task is not None:
            self._task.cancel()

    def is_alive(self) -> bool:
        """True until the asyncio task has ended."""
        return not self._ended
