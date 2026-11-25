# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Chan: a one-way FIFO channel between tasks, on threads or on the loop."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import Callable
from typing import Any, Generic, TypeVar, cast

from ..errors import StoppedError
from ..task import current_task
from .errors import ClosedError
from .waiter import LoopWaiter, Outcome, ThreadWaiter, Waiter

T = TypeVar("T")


class Chan(Generic[T]):
    """A one-way FIFO channel, like Go's chan, for tasks on threads and on the
    runtime's loop alike: a thread task calls ``send()``/``recv()``, a loop task
    awaits ``asend()``/``arecv()``, and either end can be either kind.

    A send waits while the buffer holds *capacity* values; a receive waits
    while it is empty. With capacity 0 there is no buffer: a send waits until a
    receiver takes the value, and a receive until a sender hands one over.
    Values are received in the order sent; waiting senders and receivers are
    served in the order they came.

    ``close()`` ends the channel. A receive still gets the buffered values,
    then raises ClosedError; iteration (``for``, ``async for``) ends there. A
    send raises ClosedError.

    A call that has to wait ends when the token of the task it runs in is
    stopped, with StoppedError. Only waiting is refused: a call that can
    complete at once does, so a stopped task can still drain a channel. A
    *timeout* bounds the wait (TimeoutError); 0 means do not wait.
    """

    __slots__ = ("_capacity", "_lock", "_buffer", "_closed", "_senders", "_receivers")

    def __init__(self, capacity: int) -> None:
        """A channel buffering up to *capacity* values; 0 for none.

        Raises:
            ValueError: If *capacity* is negative.
        """
        if capacity < 0:
            raise ValueError(f"capacity must be 0 or more, not {capacity}")
        self._capacity = capacity
        self._lock = threading.Lock()
        self._buffer: deque[T] = deque()
        self._closed = False
        # Waiters in the order they came. A waiter that leaves early (timeout,
        # stop, cancel) is removed in O(n); handing over pops the first
        self._senders: deque[Waiter] = deque()
        self._receivers: deque[Waiter] = deque()

    def send(self, value: T, timeout: float | None = None) -> None:
        """Send *value*, waiting up to *timeout* seconds for room.

        Raises:
            ClosedError: If the channel is closed, also while waiting.
            StoppedError: If the task's token is stopped while waiting.
            TimeoutError: If there is no room after *timeout*.
            RuntimeError: If it would wait on an event loop's thread.
        """
        with self._lock:
            if self._put(value):
                return
            _check_wait(timeout, "send")
            waiter = ThreadWaiter(value)
            self._senders.append(waiter)
        self._block(waiter, self._senders, timeout)

    def recv(self, timeout: float | None = None) -> T:
        """Receive the next value, waiting up to *timeout* seconds for one.

        Raises:
            ClosedError: If the channel is closed and drained, also while waiting.
            StoppedError: If the task's token is stopped while waiting.
            TimeoutError: If there is no value after *timeout*.
            RuntimeError: If it would wait on an event loop's thread.
        """
        with self._lock:
            ready, value = self._take()
            if ready:
                return cast(T, value)
            _check_wait(timeout, "recv")
            waiter = ThreadWaiter()
            self._receivers.append(waiter)
        return cast(T, self._block(waiter, self._receivers, timeout))

    async def asend(self, value: T, timeout: float | None = None) -> None:
        """Send *value*, awaiting up to *timeout* seconds for room. Raises as
        send(), except RuntimeError."""
        with self._lock:
            if self._put(value):
                return
            _check_timeout(timeout)
            waiter = LoopWaiter(asyncio.get_running_loop(), value)
            self._senders.append(waiter)
        await self._await(waiter, self._senders, timeout)

    async def arecv(self, timeout: float | None = None) -> T:
        """Receive the next value, awaiting up to *timeout* seconds for one.
        Raises as recv(), except RuntimeError."""
        with self._lock:
            ready, value = self._take()
            if ready:
                return cast(T, value)
            _check_timeout(timeout)
            waiter = LoopWaiter(asyncio.get_running_loop())
            self._receivers.append(waiter)
        return cast(T, await self._await(waiter, self._receivers, timeout))

    def close(self) -> None:
        """Close the channel; idempotent. Waiting receivers and senders raise
        ClosedError: the channel is empty while receivers wait, and a waiting
        sender's value is not delivered."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            waiters = [*self._receivers, *self._senders]
            self._receivers.clear()
            self._senders.clear()
            for waiter in waiters:
                waiter.settle(Outcome.CLOSED)

    def __iter__(self) -> Chan[T]:
        """Iterate with recv() until the channel is closed and drained."""
        return self

    def __next__(self) -> T:
        """The next value; StopIteration once closed and drained."""
        try:
            return self.recv()
        except ClosedError:
            raise StopIteration from None

    def __aiter__(self) -> Chan[T]:
        """Iterate with arecv() until the channel is closed and drained."""
        return self

    async def __anext__(self) -> T:
        """The next value; StopAsyncIteration once closed and drained."""
        try:
            return await self.arecv()
        except ClosedError:
            raise StopAsyncIteration from None

    def _put(self, value: T) -> bool:
        """Hand *value* to the first waiting receiver, or buffer it; False if
        the sender has to wait. Under the lock."""
        if self._closed:
            raise ClosedError("send on a closed channel")
        if self._receivers:
            receiver = self._receivers.popleft()
            receiver.value = value
            receiver.settle(Outcome.DONE)
            return True
        if len(self._buffer) < self._capacity:
            self._buffer.append(value)
            return True
        return False

    def _take(self) -> tuple[bool, Any]:
        """The next value: from the buffer, refilled from the first waiting
        sender, or with no buffer from that sender directly; (False, None) if
        the receiver has to wait. Under the lock."""
        if self._buffer:
            value = self._buffer.popleft()
            if self._senders:  # Its slot is free now
                sender = self._senders.popleft()
                self._buffer.append(sender.value)
                sender.settle(Outcome.DONE)
            return True, value
        if self._senders:
            sender = self._senders.popleft()
            sender.settle(Outcome.DONE)
            return True, sender.value
        if self._closed:
            raise ClosedError("receive on a closed channel")
        return False, None

    def _block(
        self, waiter: ThreadWaiter, queue: deque[Waiter], timeout: float | None
    ) -> Any:
        """Block the thread until *waiter* is settled; its value, or the
        error of how it ended."""
        try:
            remove = _on_stop(lambda: self._leave(waiter, queue, Outcome.STOPPED))
            try:
                if not waiter.wait(timeout):
                    self._leave(waiter, queue, Outcome.TIMEOUT)
            finally:
                remove()
        except BaseException:
            self._gone(waiter, queue)
            raise
        return _result(waiter)

    async def _await(
        self, waiter: LoopWaiter, queue: deque[Waiter], timeout: float | None
    ) -> Any:
        """Await until *waiter* is settled; its value, or the error of how it
        ended. The timeout is a timer on the loop, not wait_for(), so nothing
        is cancelled to end the wait."""
        try:
            remove = _on_stop(lambda: self._leave(waiter, queue, Outcome.STOPPED))
            timer = None
            if timeout is not None:
                timer = waiter.loop.call_later(
                    timeout, self._leave, waiter, queue, Outcome.TIMEOUT
                )
            try:
                await waiter.future
            finally:
                remove()
                if timer is not None:
                    timer.cancel()
        except BaseException:
            self._gone(waiter, queue)
            raise
        return _result(waiter)

    def _leave(self, waiter: Waiter, queue: deque[Waiter], outcome: Outcome) -> None:
        """End *waiter*'s wait with *outcome*, unless it is settled already:
        a value handed over at the same time wins."""
        with self._lock:
            if waiter.outcome is Outcome.PENDING:
                queue.remove(waiter)
                waiter.settle(outcome)

    def _gone(self, waiter: Waiter, queue: deque[Waiter]) -> None:
        """The waiting side left with an exception (a cancel, an interrupt).
        Pending, it leaves the queue. A receiver that was handed a value
        already passes it on, so no value is lost: to the next waiting
        receiver, or back to the front of the buffer, past its capacity if
        need be. A sender's value handed over is delivered."""
        with self._lock:
            if waiter.outcome is Outcome.PENDING:
                queue.remove(waiter)
                waiter.settle(Outcome.GONE)
            elif waiter.outcome is Outcome.DONE and queue is self._receivers:
                self._return(waiter.value)

    def _return(self, value: Any) -> None:
        """Put *value* back as the next to receive. Under the lock."""
        if self._receivers:
            receiver = self._receivers.popleft()
            receiver.value = value
            receiver.settle(Outcome.DONE)
        else:
            self._buffer.appendleft(value)


def _check_timeout(timeout: float | None) -> None:
    """Refuse to wait when *timeout* is 0 or less."""
    if timeout is not None and timeout <= 0:
        raise TimeoutError("channel not ready")


def _check_wait(timeout: float | None, call: str) -> None:
    """Refuse a thread wait when *timeout* is 0 or less, or on an event loop's
    thread, which the wait would block."""
    _check_timeout(timeout)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(f"{call}() would block the event loop; await a{call}()")


def _on_stop(fn: Callable[[], None]) -> Callable[[], None]:
    """Call *fn* when the token of the task the caller runs in is stopped;
    returns the function that unregisters it. Outside a task, nothing stops
    the wait."""
    task = current_task()
    if task is None:
        return _noop
    return task.token.on_stop(fn)


def _noop() -> None:
    """Unregisters nothing."""


def _result(waiter: Waiter) -> Any:
    """The value *waiter* was handed, or the error of how its wait ended."""
    outcome = waiter.outcome
    if outcome is Outcome.DONE:
        return waiter.value
    if outcome is Outcome.CLOSED:
        raise ClosedError("channel closed")
    if outcome is Outcome.STOPPED:
        raise StoppedError("task stopped")
    raise TimeoutError("channel not ready")
