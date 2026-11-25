# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The waiting side of a send or receive that has to wait: a thread, or a
coroutine on an event loop."""

from __future__ import annotations

import asyncio
import contextlib
import enum
import threading
from abc import ABC, abstractmethod
from typing import Any


class Outcome(enum.Enum):
    """How a wait ended. Settled once, under the channel's lock."""

    PENDING = enum.auto()
    DONE = enum.auto()  # the value was handed over
    CLOSED = enum.auto()
    STOPPED = enum.auto()  # the task's token was stopped
    TIMEOUT = enum.auto()
    GONE = enum.auto()  # the waiter left: cancelled, or interrupted


class Waiter(ABC):
    """One send or receive waiting on a channel. A sender's waiter carries the
    value to hand over; a receiver's gets it.

    Settled once, under the channel's lock, so exactly one party decides how
    the wait ends. Waking under that lock is safe: it releases a lock or
    schedules a callback, and waits for nothing."""

    __slots__ = ("value", "outcome")

    def __init__(self, value: Any = None) -> None:
        """A pending waiter, carrying *value* if it is a sender's."""
        self.value = value
        self.outcome = Outcome.PENDING

    def settle(self, outcome: Outcome) -> None:
        """Decide how the wait ended and wake the waiting side; under the
        channel's lock, on a pending waiter."""
        self.outcome = outcome
        self.wake()

    @abstractmethod
    def wake(self) -> None:
        """Let the waiting side resume; from any thread, once."""


class ThreadWaiter(Waiter):
    """A thread blocked on a lock held from the start, released by wake():
    cheaper than an Event, which wraps a Condition."""

    __slots__ = ("_lock",)

    def __init__(self, value: Any = None) -> None:
        """A pending waiter, carrying *value* if it is a sender's."""
        super().__init__(value)
        self._lock = threading.Lock()
        self._lock.acquire()

    def wake(self) -> None:
        """Release the thread."""
        self._lock.release()

    def wait(self, timeout: float | None) -> bool:
        """Block until woken or *timeout* seconds pass.

        Returns:
            False on the timeout.
        """
        return self._lock.acquire(timeout=-1 if timeout is None else timeout)


class LoopWaiter(Waiter):
    """A coroutine awaiting a future on its event loop."""

    __slots__ = ("loop", "future")

    def __init__(self, loop: asyncio.AbstractEventLoop, value: Any = None) -> None:
        """A pending waiter on *loop*, carrying *value* if it is a sender's."""
        super().__init__(value)
        self.loop = loop
        self.future: asyncio.Future[None] = loop.create_future()

    def wake(self) -> None:
        """Resolve the future: directly on its loop's thread, through
        call_soon_threadsafe() from any other."""
        try:
            on_loop = asyncio.get_running_loop() is self.loop
        except RuntimeError:
            on_loop = False
        if on_loop:
            self._resolve()
            return
        # RuntimeError: the loop is closed, and the coroutine gone with it
        with contextlib.suppress(RuntimeError):
            self.loop.call_soon_threadsafe(self._resolve)

    def _resolve(self) -> None:
        """On the loop: resolve the future, unless the coroutine was cancelled."""
        if not self.future.done():
            self.future.set_result(None)
