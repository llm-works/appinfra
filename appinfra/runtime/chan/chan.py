# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Chan: a one-way FIFO channel between tasks, on threads or on the loop."""

from __future__ import annotations

import asyncio
import bisect
import io
import pickle
import threading
from collections import deque
from collections.abc import Callable
from typing import Any, Generic, TypeVar, cast

from ..errors import StoppedError
from ..task import _current_token
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
    With capacity None the buffer has no bound and a send never waits, for
    senders that must not: a callback, or sync code on the loop. Nothing then
    holds a fast sender back; its values pile up until received. Values are
    received in the order sent; waiting senders and receivers are served in
    the order they came.

    ``close()`` ends the channel. A receive still gets the buffered values,
    then raises ClosedError; iteration (``for``, ``async for``) ends there. A
    send raises ClosedError.

    A call that has to wait ends when the token of the task it runs in is
    stopped, with StoppedError. Only waiting is refused: a call that can
    complete at once does, so a stopped task can still drain a channel. A
    *timeout* bounds the wait (TimeoutError); 0 means do not wait, and a
    negative one, which Python gives no one meaning, is refused (ValueError).

    On an event loop's thread, ``send()`` and ``recv()`` take only
    ``timeout=0``, whatever the channel holds: a wait there would block the
    loop, and refusing only the calls that happen to wait would make the error
    depend on timing. Coroutines await ``asend()``/``arecv()``; sync code the
    loop runs uses ``timeout=0``. A send on an unbounded channel is the
    exception: it never waits, so it is allowed with any timeout.

    ``Chan(n, process=True)`` can also be handed to a process task, and used
    there as here. Every send stores a copy of its value, pickled at the
    sender, so a value that cannot cross fails there, and every receiver,
    wherever it runs, gets a value of its own. A process channel inside the
    value stays itself, a reference as in Go; a local one is refused, as it
    could not cross. A channel is pickled only on its way to a process task:
    any other pickling raises TypeError.
    """

    __slots__ = (
        "_process",
        "_capacity",
        "_lock",
        "_buffer",
        "_given_back",
        "_sent",
        "_closed",
        "_senders",
        "_receivers",
    )

    def __init__(self, capacity: int | None, *, process: bool = False) -> None:
        """A channel buffering up to *capacity* values; 0 for none, None for
        no bound. A *process* channel can be handed to a process task.

        Raises:
            ValueError: If *capacity* is negative.
        """
        if capacity is not None and capacity < 0:
            raise ValueError(f"capacity must be 0 or more, or None, not {capacity}")
        self._process = process
        self._capacity = capacity
        self._lock = threading.Lock()
        # Each value with its number in the send order, as for the values
        # given back
        self._buffer: deque[tuple[int, T]] = deque()
        # Values taken by receivers that left before having them, by their
        # number: received before the buffer, in send order. A value is taken
        # only from the front of the buffer, or handed over while it is empty,
        # so every value given back was sent before all the buffer holds
        self._given_back: list[tuple[int, T]] = []
        self._sent = 0  # values put so far, numbering them in send order
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
            ValueError: If *timeout* is negative.
            RuntimeError: If called on an event loop's thread with a timeout
                other than 0, on a bounded channel.
            TypeError: On a process channel, if *value* holds a local channel;
                and as pickle.dumps() for a value it cannot pickle.
        """
        if self._capacity is None:
            _check_valid(timeout)  # Never waits: allowed on the loop as well
        else:
            _check_off_loop(timeout, "send")
        if self._process:
            value = _copied(value)
        with self._lock:
            if self._put(value):
                return
            _check_timeout(timeout)
            waiter = ThreadWaiter(value)
            self._senders.append(waiter)
        self._block(waiter, self._senders, timeout)

    def recv(self, timeout: float | None = None) -> T:
        """Receive the next value, waiting up to *timeout* seconds for one.

        Raises:
            ClosedError: If the channel is closed and drained, also while waiting.
            StoppedError: If the task's token is stopped while waiting.
            TimeoutError: If there is no value after *timeout*.
            ValueError: If *timeout* is negative.
            RuntimeError: If called on an event loop's thread with a timeout
                other than 0.
        """
        _check_off_loop(timeout, "recv")
        with self._lock:
            ready, value, _ = self._take()
            if ready:
                return cast(T, value)
            _check_timeout(timeout)
            waiter = ThreadWaiter()
            self._receivers.append(waiter)
        return cast(T, self._block(waiter, self._receivers, timeout))

    async def asend(self, value: T, timeout: float | None = None) -> None:
        """Send *value*, awaiting up to *timeout* seconds for room. Raises as
        send(), except RuntimeError."""
        _check_valid(timeout)
        if self._process:
            value = _copied(value)
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
        _check_valid(timeout)
        with self._lock:
            ready, value, _ = self._take()
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
                if waiter.claim():
                    waiter.settle(Outcome.CLOSED)

    def __len__(self) -> int:
        """The values waiting to be received, as Go's len(ch): what the buffer
        holds, not the values of senders still waiting. Information for the
        owner, which decides what a depth means; nothing is enforced, and the
        number may change as soon as it is read."""
        with self._lock:
            return len(self._buffer) + len(self._given_back)

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

    def __reduce__(self) -> tuple[Any, ...]:
        """A process channel in a process task's arguments, as the runtime
        starts its child: a reference to it, given by the start under way on
        this thread (crossing.py). Refused anywhere else.

        Raises:
            TypeError: For a local channel, or with no start under way.
        """
        if not self._process:
            raise TypeError(_LOCAL_ONLY)
        reference = getattr(_starting, "reference", None)
        if reference is not None:
            return cast(tuple[Any, ...], reference(self))
        raise TypeError(
            "a process Chan crosses to another process only over a link: in a "
            "process task's arguments, or inside a value sent on a process Chan"
        )

    # The internals below, with _lock, _senders and _receivers, are also used
    # by home.py: a call from another process parks there as one more Waiter.
    # It relies on _put() and _take() completing at once or reporting that the
    # caller has to wait, on a Waiter being settled once under _lock, and on
    # _leave() ending a pending waiter without giving a handed value back.

    def _put(self, value: T) -> bool:
        """Hand *value* to the first waiting receiver, or buffer it; False if
        the sender has to wait. Under the lock."""
        if self._closed:
            raise ClosedError("send on a closed channel")
        receiver = _first(self._receivers)
        if receiver is not None:
            _hand(receiver, value, self._number())
            return True
        if self._capacity is None or len(self._buffer) < self._capacity:
            self._buffer.append((self._number(), value))
            return True
        return False

    def _take(self) -> tuple[bool, Any, int]:
        """The next value and its number in the send order: one given back,
        then from the buffer, refilled from the first waiting sender, or with
        no buffer from that sender directly; (False, None, 0) if the receiver
        has to wait. Under the lock."""
        if self._given_back:
            # Frees no buffer slot: a waiting sender still waits
            seq, value = self._given_back.pop(0)
            return True, value, seq
        if self._buffer:
            seq, value = self._buffer.popleft()
            # Its slot is free now. The buffer never holds more than the
            # capacity; the refill relies on that, so it checks. Unbounded,
            # no sender ever waits
            if self._capacity is not None and len(self._buffer) < self._capacity:
                sender = _first(self._senders)
                if sender is not None:
                    self._buffer.append((self._number(), sender.value))
                    sender.settle(Outcome.DONE)
            return True, value, seq
        sender = _first(self._senders)
        if sender is not None:
            sender.settle(Outcome.DONE)
            return True, sender.value, self._number()
        if self._closed:
            raise ClosedError("receive on a closed channel")
        return False, None, 0

    def _number(self) -> int:
        """The number of the value being put, in the send order. Under the
        lock."""
        self._sent += 1
        return self._sent

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
        receiver, or given back, ahead of the buffer in send order. A sender's
        value handed over is delivered."""
        with self._lock:
            if waiter.outcome is Outcome.PENDING:
                queue.remove(waiter)
                waiter.settle(Outcome.GONE)
            elif waiter.outcome is Outcome.DONE and queue is self._receivers:
                self._return(waiter.value, waiter.seq)

    def _return(self, value: Any, seq: int) -> None:
        """Put *value*, number *seq* in the send order, back to be received
        in that order. Under the lock."""
        receiver = _first(self._receivers)
        if receiver is not None:
            # Receivers wait only while nothing is given back: it is next
            _hand(receiver, value, seq)
        else:
            at = bisect.bisect_right(self._given_back, seq, key=lambda e: e[0])
            self._given_back.insert(at, (seq, value))


# The start of a process task's child under way on this thread, if any: its
# `reference(chan)` gives the reduction of a process Chan in the arguments
_starting = threading.local()

_LOCAL_ONLY = (
    "a Chan(n) stays in the process that made it; make it Chan(n, process=True) "
    "to hand it to a process task"
)


def _copied(value: Any) -> Any:
    """A copy of *value*, as a process channel stores it: pickled and
    unpickled, the process channels in it kept as themselves.

    Raises:
        TypeError: If *value* holds a local channel; and as pickle.dumps()
            for a value it cannot pickle.
    """
    return _snapshot(value).restore()


def _snapshot(value: Any) -> _Snapshot:
    """*value* pickled, the process channels in it kept aside, from which a
    copy is restored as often as needed.

    Raises:
        TypeError: If *value* holds a local channel; and as pickle.dumps()
            for a value it cannot pickle.
    """
    refs: list[Chan[Any]] = []
    buffer = io.BytesIO()
    _Copier(buffer, refs).dump(value)
    return _Snapshot(buffer.getvalue(), refs)


class _Snapshot:
    """A value pickled for copies, and the process channels it holds."""

    __slots__ = ("_data", "_refs")

    def __init__(self, data: bytes, refs: list[Chan[Any]]) -> None:
        """The pickled *data*, its channels in *refs*."""
        self._data = data
        self._refs = refs

    def restore(self) -> Any:
        """A copy of the value, a new one each call, its channels themselves."""
        return _Restorer(io.BytesIO(self._data), self._refs).load()


class _Copier(pickle.Pickler):
    """Pickles a value for _copied(): each process channel in it as its index
    in *refs*, which the unpickling side resolves back to the channel."""

    def __init__(self, file: io.BytesIO, refs: list[Chan[Any]]) -> None:
        """Pickle into *file*, the channels found appended to *refs*."""
        super().__init__(file, pickle.HIGHEST_PROTOCOL)
        self._refs = refs

    def persistent_id(self, obj: Any) -> int | None:
        """A channel's index in refs; None, pickled as usual, for the rest.

        Raises:
            TypeError: If *obj* is a local channel.
        """
        if not isinstance(obj, Chan):
            return None
        if not obj._process:
            raise TypeError(_LOCAL_ONLY)
        self._refs.append(obj)
        return len(self._refs) - 1


class _Restorer(pickle.Unpickler):
    """Unpickles what _Copier pickled, each channel back from *refs*."""

    def __init__(self, file: io.BytesIO, refs: list[Chan[Any]]) -> None:
        """Unpickle from *file*, the channels taken from *refs*."""
        super().__init__(file)
        self._refs = refs

    def persistent_load(self, pid: Any) -> Chan[Any]:
        """The channel at index *pid*."""
        return self._refs[int(pid)]


def _first(queue: deque[Waiter]) -> Waiter | None:
    """Pop the first waiter of *queue* that may still be settled, or None. A
    select's case whose select another channel completed is dropped. Under
    the channel's lock."""
    while queue:
        waiter = queue.popleft()
        if waiter.claim():
            return waiter
    return None


def _hand(receiver: Waiter, value: Any, seq: int) -> None:
    """Hand *value*, number *seq* in the send order, to a waiting *receiver*.
    Under the channel's lock."""
    receiver.value = value
    receiver.seq = seq
    receiver.settle(Outcome.DONE)


def _check_valid(timeout: float | None) -> None:
    """Refuse a negative *timeout*: Python gives it no one meaning (queue
    refuses it, threading waits for ever on -1), so none is guessed."""
    if timeout is not None and timeout < 0:
        raise ValueError(f"timeout must be 0 or more, or None, not {timeout}")


def _check_timeout(timeout: float | None) -> None:
    """Refuse to wait when *timeout* is 0."""
    if timeout == 0:
        raise TimeoutError("channel not ready")


def _check_off_loop(timeout: float | None, call: str) -> None:
    """Refuse a negative *timeout*, and a blocking call that may wait on an
    event loop's thread, whether or not it would: only timeout=0 is sure not to
    block the loop.

    _get_running_loop() returns None off a loop, where get_running_loop()
    raises: thread tasks, the common case, pay no exception. It is private, but
    exported in asyncio.__all__ and used by anyio and uvloop; should it go,
    get_running_loop() in a try gives the same answer at the cost of an
    exception."""
    _check_valid(timeout)
    if timeout == 0:
        return
    if asyncio._get_running_loop() is not None:
        raise RuntimeError(
            f"{call}() may block the event loop; await a{call}(), or pass timeout=0"
        )


def _on_stop(fn: Callable[[], None]) -> Callable[[], None]:
    """Call *fn* when the token of the task the caller runs in is stopped;
    returns the function that unregisters it. Outside a task, nothing stops
    the wait."""
    token = _current_token()
    if token is None:
        return _noop
    return token._on_stop(fn)


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
