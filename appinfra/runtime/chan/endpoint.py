# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""One process's end of a link, open: the objects it homes for the other
side, and the calls it makes on objects homed there.

One reader thread takes every frame from the other side: a Result goes to
the caller waiting for it, the rest to the home. This side's frames (calls,
and the cancels, returns and releases of its proxies) go through one outbox
that never blocks, in the order posted, and one pump thread puts them on the
link: a caller is never held by the link, on a thread or on the loop, and a
frame posted after another by one thread never overtakes it. The home's
Results go through the same outbox. Each caller encodes its own payload, so
a value that cannot cross fails there; a process Chan in it crosses as a
reference to its home (codec.py). Every frame from the other side is decoded
on the reader, in the order frames come.

A stop of the caller's task ends only a wait, as on a local Chan: the call
posts a Cancel and waits on for the home's answer, the value of a call the
home decided first, or cancelled, raised as StoppedError. A caller that
leaves before its Result (a cancel, an interrupt) posts a Cancel too; a
Result that still comes, with a value received, goes back to the home as a
Return, to be received again in its send order: no value is lost."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import queue
import threading
from dataclasses import dataclass
from typing import Any

from ...log import Logger
from ..errors import StoppedError
from .chan import _on_stop
from .codec import LinkCodec
from .errors import ClosedError
from .home import Home
from .link import (
    Call,
    Cancel,
    Frame,
    LinkEnd,
    Push,
    Release,
    Result,
    Return,
    describe,
)
from .waiter import LoopWaiter, Outcome, ThreadWaiter, Waiter


@dataclass(frozen=True, slots=True)
class _Answer:
    """A Result, decoded on the reader: the *value* received, or the *error*
    its caller raises; *received* when a value was, numbered *seq*; *lost*
    when one was but could not be decoded; *cancelled* when the home ended
    the call on a Cancel."""

    value: Any = None
    error: BaseException | None = None
    received: bool = False
    lost: bool = False
    cancelled: bool = False
    seq: int = 0


class _Pending:
    """A call waiting for its Result: where it goes, how its caller waits,
    and what to do with a value if its caller left."""

    __slots__ = ("object_id", "op", "waiter", "answer", "stopped", "abandoned")

    def __init__(self, object_id: int, op: str, waiter: Waiter) -> None:
        """A call of *op* on *object_id*, its caller woken through *waiter*,
        which watches no stop token: a stop is handled by the endpoint."""
        self.object_id = object_id
        self.op = op
        self.waiter = waiter
        self.answer = _Answer()  # set before the waiter is woken
        self.stopped = False  # the Cancel of a stop posted: answer awaited
        self.abandoned = False  # the caller left: no one takes the answer


class Endpoint:
    """This process's end of one link: the Home of the objects it hands
    across, and the calls on objects homed on the other side. Made per link
    and process, from the end of the link this process uses."""

    def __init__(self, lg: Logger, end: LinkEnd) -> None:
        """Open *end* and start the reader and the pump."""
        self._lg = lg
        self._link = end.open()
        # Every frame this side sends, the home's Results too, in the order
        # posted; None ends the pump. Never blocks, and put() is safe from a
        # finalizer at any point (a proxy's Release)
        self._outbox: queue.SimpleQueue[Frame | None] = queue.SimpleQueue()
        self._codec = LinkCodec(self)  # process Chans in payloads as references
        self.home = Home(lg, self._post, self._codec)
        # Guards _pending and _closed; held only for table changes
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending: dict[int, _Pending] = {}
        self._closed = False
        for target, name in ((self._read, "link-read"), (self._pump, "link-pump")):
            threading.Thread(target=target, name=name, daemon=True).start()

    def call(
        self, object_id: int, op: str, args: tuple[Any, ...], timeout: float | None
    ) -> Any:
        """Run *op* with *args* on the object *object_id* homed on the other
        side, and return its value, waiting for its Result; the *timeout* is
        kept at the home. A stop of the caller's task cancels the call at
        the home and waits on for its answer. A call left with an exception
        (an interrupt) is abandoned, its value given back.

        Raises:
            ClosedError: If the link is closed, or the call raised it there.
            StoppedError: If the task's token is stopped and the home ended
                the call, waiting, on its Cancel.
            Exception: As *op* raised it at the home, and as the codec does
                for arguments that cannot be encoded or a value that cannot
                be decoded here.
        """
        waiter = ThreadWaiter()
        call_id, pending = self._start(object_id, op, args, timeout, waiter)
        try:
            remove = _on_stop(lambda: self._stop(call_id, pending))
            try:
                waiter.wait(None)
            finally:
                remove()
        except BaseException:
            self._abandon(call_id, pending)
            raise
        return _outcome(pending.answer)

    async def acall(
        self, object_id: int, op: str, args: tuple[Any, ...], timeout: float | None
    ) -> Any:
        """call(), awaited on the loop; a cancelled call is abandoned."""
        waiter = LoopWaiter(asyncio.get_running_loop())
        call_id, pending = self._start(object_id, op, args, timeout, waiter)
        try:
            remove = _on_stop(lambda: self._stop(call_id, pending))
            try:
                await waiter.future
            finally:
                remove()
        except BaseException:
            self._abandon(call_id, pending)
            raise
        return _outcome(pending.answer)

    def post(self, object_id: int, op: str, args: tuple[Any, ...]) -> None:
        """Run *op* with *args* on the object *object_id* homed on the other
        side, without waiting: its Result is dropped as it comes. Posted in
        order with this side's calls, so a call made after it runs after it.
        Nothing once the link is closed.

        Raises:
            Exception: As the codec does for arguments that cannot be encoded.
        """
        data = self._codec.encode(args)
        with self._lock:
            if self._closed:
                return
            call_id = next(self._ids)  # no pending call: _settle() drops it
        self._post(Call(call_id, object_id, op, data, None))

    def release(self, object_id: int, count: int) -> None:
        """Post a Release of *count* handings over of *object_id*, homed on
        the other side: its proxy here is gone. Called by the proxy's
        finalizer, at any point of any thread: takes no lock, and once the
        link is closed the frame goes nowhere."""
        self._post(Release(object_id, count))

    def close(self) -> None:
        """End this side of the link: the waiting calls raise ClosedError,
        the home drops its objects; idempotent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pending = list(self._pending.values())
            self._pending.clear()
            for call in pending:
                call.answer = _Answer(error=ClosedError("link closed"))
                call.waiter.settle(Outcome.DONE)
        self.home.close()
        self._outbox.put(None)
        self._link.close()

    def _start(
        self,
        object_id: int,
        op: str,
        args: tuple[Any, ...],
        timeout: float | None,
        waiter: Waiter,
    ) -> tuple[int, _Pending]:
        """Post the Call; its id, and the pending call its Result goes to,
        its caller woken through *waiter*.

        Raises:
            ClosedError: If the link is closed.
        """
        data = self._codec.encode(args)  # here: what cannot cross fails here
        pending = _Pending(object_id, op, waiter)
        with self._lock:
            if self._closed:
                raise ClosedError("link closed")
            call_id = next(self._ids)
            self._pending[call_id] = pending
        self._post(Call(call_id, object_id, op, data, timeout))
        return call_id, pending

    def _stop(self, call_id: int, pending: _Pending) -> None:
        """The token of *call_id*'s caller stopped: cancel the call at the
        home, whose answer the caller waits for. On the stopping thread, or
        the caller's for a token stopped already: posted after the Call, the
        Cancel ends only a call that parked."""
        with self._lock:
            if self._pending.get(call_id) is not pending or pending.stopped:
                return
            pending.stopped = True
        self._post(Cancel(call_id))

    def _abandon(self, call_id: int, pending: _Pending) -> None:
        """The caller of *call_id* left: cancel the call if its Result has
        not come, else give back the value the Result holds."""
        with self._lock:
            waiting = self._pending.get(call_id) is pending
            if waiting:
                pending.abandoned = True
        if not waiting:  # answered before the caller left
            self._give_back(pending, pending.answer)
        elif not pending.stopped:  # else a stop's Cancel is on its way
            self._post(Cancel(call_id))

    def _decoded(self, result: Result) -> _Answer:
        """Reader: *result* decoded, in the order frames come, so a Chan it
        refers to is resolved before a Release behind it is read. A payload
        that cannot be decoded is its caller's error."""
        if result.cancelled:
            return _Answer(cancelled=True)
        if result.error is not None:
            try:
                error = self._codec.decode(result.error)
            except Exception as e:
                error = RuntimeError(
                    f"error at the home cannot be decoded here: {describe(e)}"
                )
                error.__cause__ = e
            return _Answer(error=error)
        try:
            value = self._codec.decode(result.value)
        except Exception as e:
            return _Answer(error=e, lost=True)
        return _Answer(value, received=True, seq=result.seq)

    def _settle(self, result: Result) -> None:
        """Reader: hand *result*, decoded, to its caller; give back its value
        if the caller left. Under the lock, so an abandon sees it delivered
        or not."""
        answer = self._decoded(result)
        with self._lock:
            pending = self._pending.pop(result.call_id, None)
            if pending is None:
                return
            if not pending.abandoned:
                pending.answer = answer
                pending.waiter.settle(Outcome.DONE)  # wakes, waits for nothing
                return
        self._give_back(pending, answer)

    def _give_back(self, pending: _Pending, answer: _Answer) -> None:
        """Return the value *answer* received for a caller that left, to be
        received again at the home in its send order: encoded anew, its
        Chans as this side holds them. One that could not be decoded here,
        or decoded but cannot be encoded again, is lost, and logged."""
        if pending.op != "recv":
            return
        if answer.lost:
            self._lg.warning(
                "received value dropped: cannot be decoded",
                extra={"object_id": pending.object_id, "exception": answer.error},
            )
            return
        if not answer.received:
            return
        try:
            data = self._codec.encode(answer.value)
        except Exception as e:
            self._lg.warning(
                "given-back value dropped: cannot be encoded again",
                extra={"object_id": pending.object_id, "exception": e},
            )
            return
        self._post(Return(pending.object_id, data, answer.seq))

    def _post(self, frame: Frame) -> None:
        """Queue *frame* for the pump; never waits, never raises, and takes
        no lock. Once the link is closed the frame goes nowhere (a plain read
        of the flag: one posted as it closes is dropped with the queue)."""
        if not self._closed:
            self._outbox.put(frame)

    def _read(self) -> None:
        """Reader thread: each frame from the other side to its caller or the
        home, until the link closes; then this side closes."""
        try:
            for frame in self._link:
                if isinstance(frame, Result):
                    self._settle(frame)
                elif not isinstance(frame, Push):
                    self.home.handle(frame)
                del frame  # not kept, with its payload, until the next one
        finally:
            self.close()

    def _pump(self) -> None:
        """Pump thread: each frame from the outbox onto the link, until the
        endpoint closes or the link does."""
        with contextlib.suppress(ClosedError):
            while (frame := self._outbox.get()) is not None:
                self._link.send(frame)
                del frame  # not kept, with its payload, until the next one


def _outcome(answer: _Answer) -> Any:
    """The value of *answer*.

    Raises:
        StoppedError: If the home ended the call on a stop's Cancel.
        Exception: The error the call raised at the home, or the codec's for
            a payload that cannot be decoded here.
    """
    if answer.error is not None:
        raise answer.error
    if answer.cancelled:
        raise StoppedError("task stopped")
    return answer.value
