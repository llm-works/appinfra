# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The home side of a link: the objects this process hands across it, and
the calls on them that wait.

A call that cannot complete at once is parked in the object as one more
waiter, a _CallWaiter, beside the threads and coroutines of this process: no
thread waits for it. Settled under the object's lock, exactly once, it puts
its Result in an outbox that never blocks; a pump thread puts the outbox on
the link. Its deadline, made as the call arrived, is kept by one timer thread
for all of them. A Cancel ends a pending call as cancelled and changes
nothing for one already settled, whose Result is on its way: a call gets one
Result, so no value is lost or delivered twice."""

from __future__ import annotations

import contextlib
import heapq
import itertools
import threading
import time
from collections import deque
from typing import Any

from .chan import Chan
from .errors import ClosedError
from .link import Call, Cancel, Link, Release, Result
from .waiter import Outcome, Waiter


class _CallWaiter(Waiter):
    """A call parked in a Chan, waiting there as a thread's waiter would. Its
    wake() answers the call: under the Chan's lock, so it only queues."""

    __slots__ = ("call_id", "chan", "queue", "receiving", "_home")

    def __init__(
        self,
        home: Home,
        call: Call,
        chan: Chan[Any],
        queue: deque[Waiter],
        value: Any = None,
    ) -> None:
        """A pending waiter for *call* in *queue* of *chan*, carrying *value*
        if it is a send's."""
        super().__init__(value)
        self.call_id = call.call_id
        self.chan = chan
        self.queue = queue
        self.receiving = call.op == "recv"
        self._home = home

    def wake(self) -> None:
        """Answer the call with how its wait ended."""
        self._home._answer(self)


class Home:
    """The objects this process homes for the other side of one link, and the
    calls of that side parked in them. Made per link and process; handle()
    takes the frames meant for the home, in the order they arrive."""

    def __init__(self, link: Link) -> None:
        """The home side on *link*."""
        self._link = link
        self._ids = itertools.count(1)
        self._objects: dict[int, Chan[Any]] = {}
        self._parked: dict[int, _CallWaiter] = {}
        # Guards _objects, _parked and _closed. Taken after a Chan's lock,
        # never before: a waker holds the Chan's when it answers, so a path
        # holding this one drops it before taking a Chan's (_cancel, close)
        self._lock = threading.Lock()
        self._closed = False
        self._outbox: Chan[Result] = Chan(None)  # never blocks a waker
        self._deadlines = _Deadlines()
        self._pump = threading.Thread(target=self._send, name="link-home", daemon=True)
        self._pump.start()

    def register(self, obj: Chan[Any]) -> int:
        """Hand *obj* across the link: its id, by which the other side's proxy
        calls it. The home holds it until the proxy releases it or the link
        ends."""
        with self._lock:
            object_id = next(self._ids)
            self._objects[object_id] = obj
            return object_id

    def handle(self, frame: Call | Cancel | Release) -> None:
        """Act on a frame from the other side, without waiting."""
        if isinstance(frame, Call):
            self._call(frame)
        elif isinstance(frame, Cancel):
            self._cancel(frame.call_id)
        else:
            with self._lock:
                self._objects.pop(frame.object_id, None)

    def close(self) -> None:
        """The link ended: drop the objects, and end the parked calls without
        an answer, as no one is left to read it."""
        with self._lock:
            self._closed = True
            self._objects.clear()
            parked = list(self._parked.values())
        for waiter in parked:
            waiter.chan._leave(waiter, waiter.queue, Outcome.GONE)
        self._deadlines.close()
        self._outbox.close()

    def _call(self, call: Call) -> None:
        """Run *call* on its object: answered at once if it completes, else
        parked until its object is ready, its deadline, or a Cancel."""
        with self._lock:
            chan = self._objects.get(call.object_id)
        if chan is None:
            self._post(_error(call, ClosedError("channel released or closed")))
            return
        if call.op == "close":
            chan.close()
            self._post(Result(call.call_id))
            return
        try:
            waiter = self._park(call, chan)
        except ClosedError as e:
            self._post(_error(call, e))
            return
        if waiter is not None and call.timeout is not None:
            self._deadlines.add(time.monotonic() + call.timeout, waiter)

    def _park(self, call: Call, chan: Chan[Any]) -> _CallWaiter | None:
        """Complete *call* on *chan* at once, answering it, or leave a waiter
        for it there: returned, to be given its deadline. Both under one hold
        of *chan*'s lock, as Chan's own send() and recv(): a hand-over cannot
        slip between the call finding it not ready and its waiter queueing.

        Raises:
            ClosedError: If *chan* is closed (and, receiving, drained).
        """
        sending = call.op == "send"
        queue = chan._senders if sending else chan._receivers
        with chan._lock:
            if sending:
                done, value = chan._put(call.args[0]), None
            else:
                done, value = chan._take()
            if done:
                self._post(Result(call.call_id, value=value))
                return None
            if call.timeout == 0:
                self._post(_error(call, TimeoutError("channel not ready")))
                return None
            waiter = _CallWaiter(
                self, call, chan, queue, call.args[0] if sending else None
            )
            with self._lock:
                self._parked[call.call_id] = waiter
            queue.append(waiter)
        return waiter

    def _cancel(self, call_id: int) -> None:
        """End the parked call *call_id* as cancelled; nothing for one settled
        or answered already. _leave(), not _gone(): a value handed to a
        parked receive is in its Result, not to be given back as well."""
        with self._lock:
            waiter = self._parked.get(call_id)
        if waiter is not None:
            waiter.chan._leave(waiter, waiter.queue, Outcome.GONE)

    def _answer(self, waiter: _CallWaiter) -> None:
        """Queue the Result of a settled waiter; under its Chan's lock."""
        with self._lock:
            self._parked.pop(waiter.call_id, None)
            if self._closed:
                return
        self._post(_result(waiter))

    def _post(self, result: Result) -> None:
        """Queue *result* for the pump; never waits and never raises. Closed,
        the link has ended: the answer has no one to go to. A waker calls this
        under its Chan's lock, where an error would fail an unrelated call."""
        with contextlib.suppress(ClosedError):
            self._outbox.send(result)

    def _send(self) -> None:
        """Pump thread: each Result from the outbox onto the link, until the
        outbox closes or the link does."""
        try:
            for result in self._outbox:
                self._link.send(result)
        except ClosedError:
            pass  # the link closed: the other side is gone


class _Deadlines:
    """One timer thread for the deadlines of all parked calls of a home: a
    call still parked at its deadline leaves with TIMEOUT."""

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, _CallWaiter]] = []
        self._order = itertools.count()  # ties: waiters do not compare
        self._cond = threading.Condition()
        self._closed = False
        threading.Thread(target=self._run, name="link-deadlines", daemon=True).start()

    def add(self, deadline: float, waiter: _CallWaiter) -> None:
        """Time *waiter* out at *deadline*, a monotonic time."""
        with self._cond:
            heapq.heappush(self._heap, (deadline, next(self._order), waiter))
            self._cond.notify()

    def close(self) -> None:
        """Stop the timer thread."""
        with self._cond:
            self._closed = True
            self._cond.notify()

    def _run(self) -> None:
        """Timer thread: leave each waiter whose deadline passed."""
        with self._cond:
            while not self._closed:
                if not self._heap:
                    self._cond.wait()
                    continue
                deadline, _, waiter = self._heap[0]
                left = deadline - time.monotonic()
                if left > 0:
                    self._cond.wait(left)
                    continue
                heapq.heappop(self._heap)
                # Outside the condition: _leave takes the Chan's lock, and a
                # waker holding it may be adding a deadline
                self._cond.release()
                try:
                    waiter.chan._leave(waiter, waiter.queue, Outcome.TIMEOUT)
                finally:
                    self._cond.acquire()


def _result(waiter: _CallWaiter) -> Result:
    """The Result of a settled waiter."""
    outcome = waiter.outcome
    if outcome is Outcome.DONE:
        return Result(waiter.call_id, value=waiter.value if waiter.receiving else None)
    if outcome is Outcome.GONE:
        return Result(waiter.call_id, cancelled=True)
    if outcome is Outcome.CLOSED:
        return Result(waiter.call_id, error=ClosedError("channel closed"))
    return Result(waiter.call_id, error=TimeoutError("channel not ready"))


def _error(call: Call, error: BaseException) -> Result:
    """The Result of *call* failing with *error* before it waited."""
    return Result(call.call_id, error=error)
