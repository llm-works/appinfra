# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""select(): wait until one of several channel operations can complete, and
complete exactly that one, like Go's select."""

from __future__ import annotations

import asyncio
import contextlib
import random
import threading
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from ..errors import StoppedError
from .chan import Chan, _check_off_loop, _check_timeout, _check_valid, _on_stop
from .errors import ClosedError
from .waiter import LoopWaiter, Outcome, ThreadWaiter, Waiter


@dataclass(frozen=True)
class Recv:
    """A select case: receive from *chan*."""

    chan: Chan[Any]


@dataclass(frozen=True)
class Send:
    """A select case: send *value* on *chan*."""

    chan: Chan[Any]
    value: Any


def select(*cases: Recv | Send, timeout: float | None = None) -> tuple[int, Any]:
    """Wait until one of *cases* can complete, complete it alone, and return
    its position and the value received (None for a send). Among cases ready
    at once one is chosen at random, so none starves the others.

    *timeout* bounds the wait as for Chan.recv(); 0 means do not wait, as
    Go's default case. On an event loop's thread, only timeout=0 is accepted.

    Raises:
        ClosedError: If the chosen case's channel is closed (drained, for a
            receive); its index names the case.
        StoppedError: If the task's token is stopped while waiting.
        TimeoutError: If no case can complete within *timeout*.
        ValueError: If there is no case, or *timeout* is negative.
        RuntimeError: If called on an event loop's thread with a timeout
            other than 0.
    """
    _check_off_loop(timeout, "select")
    sel = _Select(ThreadWaiter(), cases)
    done = sel.start(timeout)
    return done if done is not None else sel.block(timeout)


async def aselect(*cases: Recv | Send, timeout: float | None = None) -> tuple[int, Any]:
    """select(), awaiting on the loop. Raises as select(), except RuntimeError."""
    _check_valid(timeout)
    sel = _Select(LoopWaiter(asyncio.get_running_loop()), cases)
    done = sel.start(timeout)
    return done if done is not None else await sel.wait(timeout)


class _Entry(Waiter):
    """A case of a waiting select, queued in its channel. All of a select's
    entries share its waiter; the first channel to claim one completes it."""

    __slots__ = ("select", "index", "chan", "queue")

    def __init__(self, select: _Select, index: int, case: Recv | Send) -> None:
        """The entry of case *index* of *select*."""
        super().__init__(case.value if isinstance(case, Send) else None)
        self.select = select
        self.index = index
        self.chan = case.chan
        recv = isinstance(case, Recv)
        self.queue: deque[Waiter] = case.chan._receivers if recv else case.chan._senders

    def claim(self) -> bool:
        """Win the select for this case, unless it was won or ended already."""
        return self.select.claim(self)

    def wake(self) -> None:
        """Wake the select's waiting side."""
        self.select.waiter.wake()


class _Select:
    """One select: who completed it, its entries, and the waiter they share."""

    __slots__ = ("_lock", "waiter", "cases", "entries", "fired")

    def __init__(self, waiter: Waiter, cases: Sequence[Recv | Send]) -> None:
        """A select of *cases*, waiting with *waiter*."""
        if not cases:
            raise ValueError("select needs a case")
        self._lock = threading.Lock()  # taken under a channel's lock, or alone
        self.waiter = waiter
        self.cases = cases
        self.entries: list[_Entry] = []
        # The entry whose channel completed it, or how it ended otherwise
        self.fired: _Entry | Outcome | None = None

    def claim(self, by: _Entry | Outcome) -> bool:
        """Record *by* as the select's end, if it has none yet."""
        with self._lock:
            if self.fired is not None:
                return False
            self.fired = by
            return True

    def start(self, timeout: float | None) -> tuple[int, Any] | None:
        """Complete a ready case, chosen at random, or queue an entry for each
        case. All the channels are locked meanwhile, in one order for every
        select, so no value slips past between the check and the queueing,
        and no entry of this select is queued while it checks."""
        chans = {id(case.chan): case.chan for case in self.cases}
        with contextlib.ExitStack() as locks:
            for key in sorted(chans):
                locks.enter_context(chans[key]._lock)
            order = list(range(len(self.cases)))
            random.shuffle(order)
            for index in order:
                ready, value = _try(self.cases[index], index)
                if ready:
                    return index, value
            _check_timeout(timeout)
            for index in order:
                entry = _Entry(self, index, self.cases[index])
                entry.queue.append(entry)
                self.entries.append(entry)
        return None

    def block(self, timeout: float | None) -> tuple[int, Any]:
        """Block the thread until a case completes or the wait ends."""
        waiter = cast(ThreadWaiter, self.waiter)
        try:
            remove = _on_stop(lambda: self.leave(Outcome.STOPPED))
            try:
                if not waiter.wait(timeout):
                    self.leave(Outcome.TIMEOUT)
            finally:
                remove()
        except BaseException:
            self.gone()
            raise
        finally:
            self.unqueue()
        return self.result()

    async def wait(self, timeout: float | None) -> tuple[int, Any]:
        """Await until a case completes or the wait ends; the timeout is a
        timer on the loop, as for Chan.arecv()."""
        waiter = cast(LoopWaiter, self.waiter)
        try:
            remove = _on_stop(lambda: self.leave(Outcome.STOPPED))
            timer = None
            if timeout is not None:
                timer = waiter.loop.call_later(timeout, self.leave, Outcome.TIMEOUT)
            try:
                await waiter.future
            finally:
                remove()
                if timer is not None:
                    timer.cancel()
        except BaseException:
            self.gone()
            raise
        finally:
            self.unqueue()
        return self.result()

    def leave(self, outcome: Outcome) -> None:
        """End the wait with *outcome*, unless a case completed first."""
        if self.claim(outcome):
            self.waiter.wake()

    def gone(self) -> None:
        """The waiting side left with an exception (a cancel, an interrupt).
        A case completed meanwhile stands, except that a value received is
        passed on, as Chan.arecv() does, so none is lost."""
        if self.claim(Outcome.GONE):
            return
        fired = self.fired
        if isinstance(fired, _Entry) and fired.queue is fired.chan._receivers:
            with fired.chan._lock:  # the claim and the hand-over hold it
                if fired.outcome is Outcome.DONE:
                    fired.chan._return(fired.value, fired.seq)

    def unqueue(self) -> None:
        """Take every entry still queued out of its channel: a select in a
        loop over an idle channel leaves nothing behind."""
        for entry in self.entries:
            with entry.chan._lock, contextlib.suppress(ValueError):
                entry.queue.remove(entry)

    def result(self) -> tuple[int, Any]:
        """The completed case's position and value, or the error of how the
        wait ended."""
        fired = self.fired
        if fired is Outcome.STOPPED:
            raise StoppedError("task stopped")
        if fired is Outcome.TIMEOUT:
            raise TimeoutError("no case ready")
        entry = cast(_Entry, fired)
        with entry.chan._lock:  # claimed and settled under it: settled now
            outcome = entry.outcome
        if outcome is Outcome.CLOSED:
            error = ClosedError("channel closed")
            error.index = entry.index
            raise error
        received = entry.queue is entry.chan._receivers
        return entry.index, entry.value if received else None


def _try(case: Recv | Send, index: int) -> tuple[bool, Any]:
    """Complete *case*, case *index* of a select, if it can be at once; under
    its channel's lock."""
    try:
        if isinstance(case, Recv):
            return case.chan._take()
        return case.chan._put(case.value), None
    except ClosedError as e:
        e.index = index
        raise
