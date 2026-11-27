# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The home side of a link: the objects this process hands across it, and
the calls on them that wait.

A call that cannot complete at once is parked in the object as one more
waiter, a _CallWaiter, beside the threads and coroutines of this process: no
thread waits for it. Settled under the object's lock, exactly once, it puts
its Result in an outbox that never blocks; a pump thread encodes each and
posts it to the endpoint's outbox, in order with every other frame this side
sends. Its deadline, made as the call arrived, is kept by one timer thread
for all of them. A Cancel ends a pending call as cancelled and changes
nothing for one already settled, whose Result is on its way: a call gets one
Result, so no value is lost or delivered twice."""

from __future__ import annotations

import contextlib
import heapq
import itertools
import pickle
import threading
import time
import weakref
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ...log import Logger
from .chan import Chan, _check_valid
from .errors import ClosedError
from .link import Call, Cancel, Codec, Frame, Release, Result, Return, describe
from .waiter import Outcome, Waiter


class _Export:
    """An object handed across the link, and how many times: a release
    counts down the handings over its proxy received."""

    __slots__ = ("chan", "count")

    def __init__(self, chan: Chan[Any]) -> None:
        """*chan*, handed over once."""
        self.chan = chan
        self.count = 1


class _CallWaiter(Waiter):
    """A call parked in a Chan, waiting there as a thread's waiter would. Its
    wake() answers the call: under the Chan's lock, so it only queues."""

    # __weakref__: the deadline timer refers to it weakly, so a settled call
    # is freed at once, not when its deadline would have passed
    __slots__ = ("call_id", "chan", "queue", "receiving", "_home", "__weakref__")

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

    def __init__(self, lg: Logger, post: Callable[[Frame], None], codec: Codec) -> None:
        """The home side of a link: its Results go out through *post*, the
        payloads of its frames encoded and decoded with *codec*."""
        self._lg = lg
        self._post_frame = post
        self._codec = codec
        self._ids = itertools.count(1)
        self._objects: dict[int, _Export] = {}
        self._by_object: dict[int, int] = {}  # id() of an object: its id here
        self._parked: dict[int, _CallWaiter] = {}
        # Guards the tables and _closed. Taken after a Chan's lock,
        # never before: a waker holds the Chan's when it answers, so a path
        # holding this one drops it before taking a Chan's (_cancel, close)
        self._lock = threading.Lock()
        self._closed = False
        self._outbox: Chan[Result] = Chan(None)  # never blocks a waker
        self._deadlines = _Deadlines()
        self._pump = threading.Thread(target=self._send, name="link-home", daemon=True)
        self._pump.start()

    def register(self, obj: Chan[Any]) -> int:
        """Hand *obj* across the link: its id, the same each time, by which
        the other side's proxy calls it. The home holds it until the proxy
        has released every handing over, or the link ends."""
        with self._lock:
            object_id = self._by_object.get(id(obj))
            if object_id is not None:
                self._objects[object_id].count += 1
                return object_id
            object_id = next(self._ids)
            self._objects[object_id] = _Export(obj)
            self._by_object[id(obj)] = object_id
            return object_id

    def handle(self, frame: Call | Cancel | Return | Release) -> None:
        """Act on a frame from the other side, without waiting."""
        if isinstance(frame, Call):
            self._call(frame)
        elif isinstance(frame, Cancel):
            self._cancel(frame.call_id)
        elif isinstance(frame, Return):
            self._give_back(frame)
        else:
            self._release(frame)

    def close(self) -> None:
        """The link is ending: drop the objects, and end the parked calls
        without an answer, as no one is left to read it. The Results decided
        before are posted first: returns once the pump is done."""
        with self._lock:
            self._closed = True
            self._objects.clear()
            self._by_object.clear()
            parked = list(self._parked.values())
        for waiter in parked:
            waiter.chan._leave(waiter, waiter.queue, Outcome.GONE)
        self._deadlines.close()
        self._outbox.close()  # the pump drains what it holds, then ends
        self._pump.join()

    def _call(self, call: Call) -> None:
        """Run *call* on its object: answered at once if it completes, else
        parked until its object is ready, its deadline, or a Cancel."""
        try:
            _check_valid(call.timeout)  # as the Chan's own calls, before anything
            args = self._codec.decode(call.args)
        except Exception as e:  # its arguments, undecodable here, fail the call alone
            self._post(_error(call, e))
            return
        chan = self.exported(call.object_id)
        if chan is None:
            self._post(_error(call, ClosedError("channel released or closed")))
            return
        if call.op == "close":
            chan.close()
            self._post(Result(call.call_id))
            return
        if call.op == "len":
            self._post(Result(call.call_id, value=len(chan)))
            return
        try:
            waiter = self._park(call, chan, args)
        except ClosedError as e:
            self._post(_error(call, e))
            return
        if waiter is not None and call.timeout is not None:
            self._deadlines.add(time.monotonic() + call.timeout, waiter)

    def _park(
        self, call: Call, chan: Chan[Any], args: tuple[Any, ...]
    ) -> _CallWaiter | None:
        """Complete *call*, with its decoded *args*, on *chan* at once,
        answering it, or leave a waiter for it there: returned, to be given
        its deadline. Both under one hold
        of *chan*'s lock, as Chan's own send() and recv(): a hand-over cannot
        slip between the call finding it not ready and its waiter queueing.

        Raises:
            ClosedError: If *chan* is closed (and, receiving, drained), or the
                home is, before the call would park.
        """
        sending = call.op == "send"
        queue = chan._senders if sending else chan._receivers
        with chan._lock:
            if sending:
                done, value, seq = chan._put(args[0]), None, 0
            else:
                done, value, seq = chan._take()
            if done:
                self._post(Result(call.call_id, value=value, seq=seq))
                return None
            if call.timeout == 0:
                self._post(_error(call, TimeoutError("channel not ready")))
                return None
            waiter = _CallWaiter(self, call, chan, queue, args[0] if sending else None)
            with self._lock:
                # A close since _call() found the Chan: parked, the call would
                # take a value whose Result no one reads
                if self._closed:
                    raise ClosedError("home closed")
                self._parked[call.call_id] = waiter
            queue.append(waiter)
        return waiter

    def exported(self, object_id: int) -> Chan[Any] | None:
        """The object *object_id*, or None once released or the link ended."""
        with self._lock:
            export = self._objects.get(object_id)
        return None if export is None else export.chan

    def _release(self, frame: Release) -> None:
        """Count *frame*'s handings over as released; drop the object once
        all are. A release counts only the handings over that reached its
        proxy: one still on its way keeps the object."""
        self.release(frame.object_id, frame.count)

    def release(self, object_id: int, count: int) -> None:
        """Count *count* handings over of *object_id* as released, also for
        ones that never reached a proxy (an encoding that failed); drop the
        object once all are."""
        with self._lock:
            export = self._objects.get(object_id)
            if export is None:
                return
            export.count -= count
            if export.count <= 0:
                del self._objects[object_id]
                del self._by_object[id(export.chan)]

    def _give_back(self, frame: Return) -> None:
        """Put the value of *frame* back in its object, received again in its
        send order, as a local receive that left after the hand-over does.
        Dropped with the object: released, no proxy is left to receive it.
        Decoded even then: the Chans the other side handed over in it are
        released by the proxies decoding makes, once the value is dropped.

        Dropped too if it cannot be decoded: it can fail to be rebuilt (a
        __reduce__ whose constructor raises), and the failure stays with it:
        raised here, it would end the reader, and the link with it."""
        try:
            value = self._codec.decode(frame.value)
        except Exception as e:
            self._lg.warning(
                "returned value dropped: cannot be decoded",
                extra={"object_id": frame.object_id, "exception": e},
            )
            return
        chan = self.exported(frame.object_id)
        if chan is None:
            return
        with chan._lock:
            chan._return(value, frame.seq)

    def _cancel(self, call_id: int) -> None:
        """End the parked call *call_id* as cancelled; nothing for one settled
        or answered already. _leave(), not _gone(): a value handed to a
        parked receive is in its Result; the proxy gives it back, with a
        Return, if its caller left."""
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
        self._deadlines.settled()
        self._post(_result(waiter))

    def _post(self, result: Result) -> None:
        """Queue *result* for the pump; never waits and never raises. Closed,
        the link has ended: the answer has no one to go to. A waker calls this
        under its Chan's lock, where an error would fail an unrelated call."""
        with contextlib.suppress(ClosedError):
            self._outbox.send(result)

    def _send(self) -> None:
        """Pump thread: each Result from the outbox, encoded and posted, until
        the outbox closes or the link does."""
        try:
            for result in self._outbox:
                self._deliver(result)
                # Not kept until the next one: a proxy in its value would live
                # on, and its Chan with it, at the other side
                del result
        except ClosedError:
            pass  # the link closed: the other side is gone

    def _deliver(self, result: Result) -> None:
        """Post *result*, its payload encoded here, outside every lock
        (encoding runs the payload's own code). Whatever fails in making it
        ready fails its call alone: the pump goes on with the rest.

        *result* holds its value until it is posted: a proxy in it lives on
        at least until then, so its Release is posted after it, and the other
        side decodes the reference before it releases the Chan.

        Raises:
            ClosedError: If the link is closed.
        """
        try:
            ready = self._encoded(result)
        except Exception as e:
            error = RuntimeError(f"result could not be sent: {describe(e)}")
            ready = Result(result.call_id, error=self._codec.encode(error))
        self._post_frame(ready)

    def _encoded(self, result: Result) -> Result:
        """*result* with its value or its error encoded. A value that cannot
        be pickled fails its call in its place, so the results after it still
        go; the value is lost: the call took it, and it could never cross the
        link. An error that cannot be pickled crosses as a RuntimeError
        naming it."""
        if result.error is not None:
            try:
                return replace(result, error=self._codec.encode(result.error))
            except Exception as e:  # pickle.dumps() raises what a reduce does
                name = type(result.error).__qualname__
                error: BaseException = RuntimeError(
                    f"error not picklable: {name}: {describe(e)}"
                )
        elif result.cancelled:
            return result
        else:
            try:
                return replace(result, value=self._codec.encode(result.value))
            except Exception as e:
                error = pickle.PicklingError(f"result not picklable: {describe(e)}")
        return Result(result.call_id, error=self._codec.encode(error))


class _Deadlines:
    """One timer thread for the deadlines of all parked calls of a home: a
    call still parked at its deadline leaves with TIMEOUT.

    The heap refers to its waiters weakly: a settled one is freed at once,
    with its Chan and value, and its entry is dropped lazily. Once settled
    calls are half the heap, it is rebuilt without their entries, so it
    holds at most about twice the calls still parked."""

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, weakref.ref[_CallWaiter]]] = []
        self._order = itertools.count()  # ties: waiters do not compare
        self._settled = 0  # calls settled since the heap was last rebuilt
        self._cond = threading.Condition()
        self._closed = False
        threading.Thread(target=self._run, name="link-deadlines", daemon=True).start()

    def add(self, deadline: float, waiter: _CallWaiter) -> None:
        """Time *waiter* out at *deadline*, a monotonic time."""
        with self._cond:
            entry = (deadline, next(self._order), weakref.ref(waiter))
            heapq.heappush(self._heap, entry)
            self._cond.notify()

    def settled(self) -> None:
        """A parked call settled, with a deadline or without: rebuild the
        heap once such calls are half of it. Under the Chan's lock, which the
        timer thread never takes while holding the condition."""
        with self._cond:
            self._settled += 1
            if self._settled * 2 >= len(self._heap):
                self._heap = [e for e in self._heap if _pending(e[2]) is not None]
                heapq.heapify(self._heap)
                self._settled = 0

    def close(self) -> None:
        """Stop the timer thread, and drop every entry."""
        with self._cond:
            self._closed = True
            self._heap.clear()
            self._cond.notify()

    def _run(self) -> None:
        """Timer thread: leave each waiter whose deadline passed."""
        with self._cond:
            while not self._closed:
                if not self._heap:
                    self._cond.wait()
                    continue
                deadline, _, ref = self._heap[0]
                left = deadline - time.monotonic()
                if left > 0:
                    # In slices of at most TIMEOUT_MAX, which a longer wait
                    # (an unbounded timeout) overflows; left is recomputed
                    self._cond.wait(min(left, threading.TIMEOUT_MAX))
                    continue
                heapq.heappop(self._heap)
                waiter = _pending(ref)
                if waiter is None:
                    continue  # settled before its deadline
                # Outside the condition: _leave takes the Chan's lock, and a
                # waker holding it may be adding a deadline
                self._cond.release()
                try:
                    waiter.chan._leave(waiter, waiter.queue, Outcome.TIMEOUT)
                finally:
                    # Not kept while the timer waits for the next deadline: a
                    # send's waiter holds its value
                    del waiter
                    self._cond.acquire()


def _pending(ref: weakref.ref[_CallWaiter]) -> _CallWaiter | None:
    """The waiter *ref* refers to, if it is still pending. Read without the
    Chan's lock: one seen settled stays settled, and one that settles after
    this is left alone by _leave()."""
    waiter = ref()
    if waiter is None or waiter.outcome is not Outcome.PENDING:
        return None
    return waiter


def _result(waiter: _CallWaiter) -> Result:
    """The Result of a settled waiter."""
    outcome = waiter.outcome
    if outcome is Outcome.DONE:
        if waiter.receiving:
            return Result(waiter.call_id, value=waiter.value, seq=waiter.seq)
        return Result(waiter.call_id)
    if outcome is Outcome.GONE:
        return Result(waiter.call_id, cancelled=True)
    if outcome is Outcome.CLOSED:
        return Result(waiter.call_id, error=ClosedError("channel closed"))
    return Result(waiter.call_id, error=TimeoutError("channel not ready"))


def _error(call: Call, error: BaseException) -> Result:
    """The Result of *call* failing with *error* before it waited."""
    return Result(call.call_id, error=error)
