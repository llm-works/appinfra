# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Measure what a task on a runtime's event loop costs: bytes per parked task, the
part asyncio takes and the part the runtime adds, the rate tasks spawn and end, the
round-trip rate over channels between two tasks, and tasks parked for an idle
measurement (parked()).

The same coroutines run once as plain asyncio tasks on the runtime's loop and once
spawned as runtime tasks; the difference is the runtime's: its task, the handle, the
child token, the context the call runs in. Each coroutine parks on an event all of
them share, so it holds nothing of its own, as an idle goroutine parks on a channel.

scripts/runtime_bench.py prints these numbers next to appinfra.service.bench's, which
measures services the same way; the performance tests assert on them.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import gc
import threading
import time
import tracemalloc
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TypeVar

from ..log import Logger
from .chan import Chan
from .errors import StoppedError
from .runtime import Runtime
from .task import Task

T = TypeVar("T")


def check_count(count: int) -> None:
    """Reject a count below 1, which no measurement can use.

    Raises:
        ValueError: If *count* is less than 1.
    """
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count}")


class Arrivals:
    """Counts coroutines that have started; set once all *expected* have.
    Updated on the loop thread only."""

    def __init__(self, expected: int) -> None:
        """Wait for *expected* arrivals.

        Raises:
            ValueError: If *expected* is less than 1: no arrival would set ``all``.
        """
        check_count(expected)
        self._left = expected
        self.all = threading.Event()

    def arrive(self) -> None:
        """Count one as started."""
        self._left -= 1
        if self._left == 0:
            self.all.set()


def bytes_per(start: Callable[[], T], count: int) -> tuple[float, T]:
    """Bytes allocated per item while *start* starts *count* of them, and what
    *start* returned.

    Raises:
        ValueError: If *count* is less than 1.
    """
    check_count(count)
    gc.collect()
    # A session the caller started stays theirs: stopping it would discard its traces
    owned = not tracemalloc.is_tracing()
    if owned:
        tracemalloc.start()
    try:
        before = tracemalloc.take_snapshot()
        started = start()
        after = tracemalloc.take_snapshot()
    finally:
        if owned:
            tracemalloc.stop()
    size = sum(d.size_diff for d in after.compare_to(before, "filename"))
    return size / count, started


def bytes_per_warmed(
    start: Callable[[], T], end: Callable[[T], object], count: int
) -> tuple[float, T]:
    """bytes_per() of *start*, after one run of *start* and *end* that is not
    measured. The containers the items go into (asyncio's set of tasks, a
    runtime's table) grow in steps and never shrink: a measured run that pays
    for a step costs tens of bytes more per item than one that does not, and
    which run pays depends on what ran before. Warmed, none does.

    The warm-up is traced too: a table it drains does not shrink, so the
    measured run may still replace it, and the new table is only offset by
    freeing the old one if the old one was traced. A session the caller
    started stays theirs.

    Raises:
        ValueError: If *count* is less than 1.
    """
    check_count(count)
    owned = not tracemalloc.is_tracing()
    if owned:
        tracemalloc.start()
    try:
        end(start())
        return bytes_per(start, count)
    finally:
        if owned:
            tracemalloc.stop()


@dataclass(frozen=True)
class TaskCost:
    """Bytes per parked task: asyncio's part and the runtime's."""

    asyncio: float
    runtime: float

    @property
    def net(self) -> float:
        """What a parked task costs on the runtime, before what it holds."""
        return self.asyncio + self.runtime


async def _event() -> asyncio.Event:
    """An event on the runtime's loop."""
    return asyncio.Event()


async def _set(event: asyncio.Event) -> None:
    """Set *event*, on its loop."""
    event.set()


async def _parked(arrivals: Arrivals, event: asyncio.Event) -> None:
    """Arrive, then park on *event*: for memory, as the tasks then hold nothing
    of their own."""
    arrivals.arrive()
    await event.wait()


async def _parked_alone(arrivals: Arrivals) -> None:
    """Arrive, then park on a future of its own: for rates. A cancelled waiter
    of an asyncio.Event is removed from the event's waiters by a linear scan;
    a loop's shutdown cancels its tasks in no particular order, so with one
    event shared by all, each cancel scans half of them, which times asyncio,
    not the runtime. A future's cancel is O(1)."""
    arrivals.arrive()
    await asyncio.get_running_loop().create_future()


@dataclass(frozen=True)
class _Parked:
    """The tasks of one run, and the event they park on."""

    event: asyncio.Event
    plain: list[asyncio.Task[None]]
    spawned: list[Task]


def _start_plain(tasks: Runtime, count: int) -> _Parked:
    """*count* coroutines as plain asyncio tasks on the loop of *tasks*, each
    parked by the time this returns."""
    arrivals = Arrivals(count)
    event: asyncio.Event = tasks.spawn(_event).wait(timeout=60.0)

    async def spawn() -> list[asyncio.Task[None]]:
        return [asyncio.create_task(_parked(arrivals, event)) for _ in range(count)]

    plain: list[asyncio.Task[None]] = tasks.spawn(spawn).wait(timeout=60.0)
    if not arrivals.all.wait(timeout=60.0):
        raise TimeoutError(f"{count:,} asyncio tasks did not all start in 60 s")
    return _Parked(event, plain, [])


def _start_tasks(tasks: Runtime, count: int) -> _Parked:
    """*count* coroutines spawned as runtime tasks, each parked by the time
    this returns."""
    arrivals = Arrivals(count)
    event: asyncio.Event = tasks.spawn(_event).wait(timeout=60.0)
    spawned = [tasks.spawn(_parked, arrivals, event) for _ in range(count)]
    if not arrivals.all.wait(timeout=60.0):
        raise TimeoutError(f"{count:,} runtime tasks did not all start in 60 s")
    return _Parked(event, [], spawned)


def _end(tasks: Runtime, parked: _Parked) -> None:
    """Release the tasks of *parked* and wait until each has ended."""

    async def ended() -> None:
        await asyncio.gather(*parked.plain)

    tasks.spawn(_set, parked.event).wait(timeout=60.0)
    tasks.spawn(ended).wait(timeout=60.0)
    for task in parked.spawned:
        task.wait(timeout=60.0)


def _spawn_parked(tasks: Runtime, count: int) -> tuple[list[Task], float]:
    """Spawn *count* tasks parked alone on the loop of *tasks*; returns them,
    and how many per second were spawned and running. Timed until each runs,
    not until the last spawn() returns: how much of the loop's share falls
    before that depends on how the GIL switches between the threads."""
    arrivals = Arrivals(count)
    began = time.perf_counter()
    spawned = [tasks.spawn(_parked_alone, arrivals) for _ in range(count)]
    if not arrivals.all.wait(timeout=60.0):
        raise TimeoutError(f"{count:,} runtime tasks did not all start in 60 s")
    return spawned, count / (time.perf_counter() - began)


async def _receiving(arrivals: Arrivals, inbox: Chan[int]) -> None:
    """Arrive, then park in arecv() on *inbox*, which nothing sends to."""
    arrivals.arrive()
    await inbox.arecv()


def _cancel_all(spawned: list[Task]) -> None:
    """Cancel *spawned* and wait until each has ended."""
    for task in spawned:
        task.cancel()
        with contextlib.suppress(StoppedError):  # Its stop ended it: no result
            task.wait(timeout=60.0)


@contextlib.contextmanager
def parked(tasks: Runtime, count: int, *, receiving: bool = False) -> Iterator[None]:
    """*count* tasks parked on the loop of *tasks* while the block runs, each on
    a future of its own, or with *receiving*, in arecv() on a channel of its
    own that nothing sends to; they are cancelled and ended after it.

    Raises:
        ValueError: If *count* is less than 1.
    """
    arrivals = Arrivals(count)
    if receiving:
        spawned = [
            tasks.spawn(_receiving, arrivals, Chan[int](1)) for _ in range(count)
        ]
    else:
        spawned = [tasks.spawn(_parked_alone, arrivals) for _ in range(count)]
    try:
        if not arrivals.all.wait(timeout=60.0):
            raise TimeoutError(f"{count:,} runtime tasks did not all start in 60 s")
        yield
    finally:
        _cancel_all(spawned)


def task_rates(tasks: Runtime, count: int) -> tuple[float, float]:
    """Tasks per second spawned and running, over *count* parked tasks on the
    loop of *tasks*, and tasks per second that cancel() and wait() then end,
    one task after the other.

    Raises:
        ValueError: If *count* is less than 1.
    """
    spawned, spawn = _spawn_parked(tasks, count)
    began = time.perf_counter()
    _cancel_all(spawned)
    return spawn, count / (time.perf_counter() - began)


def runtime_rates(lg: Logger, count: int) -> tuple[float, float]:
    """Tasks per second spawned and running, over *count* parked tasks on a
    runtime of its own, and tasks per second its one stop() then ends: it
    stops every task's token, cancels the tasks and shuts the loop down.

    Raises:
        ValueError: If *count* is less than 1.
    """
    with Runtime(lg) as rt:
        _, spawn = _spawn_parked(rt, count)
        began = time.perf_counter()
        rt.stop(timeout=60.0)
        stop = count / (time.perf_counter() - began)
    return spawn, stop


async def _doubler(inbox: Chan[int], outbox: Chan[int]) -> None:
    """Answer each value on *inbox* with it doubled, until *inbox* is closed."""
    async for value in inbox:
        await outbox.asend(value * 2)


async def _round_trips(inbox: Chan[int], outbox: Chan[int], count: int) -> float:
    """*count* round trips to a doubler; returns how many per second."""
    began = time.perf_counter()
    for i in range(count):
        await inbox.asend(i)
        await outbox.arecv()
    return count / (time.perf_counter() - began)


def round_trip_rate(tasks: Runtime, count: int) -> float:
    """Round trips per second, *count* of them, from a task on the loop of
    *tasks* to a doubler task and back, over two channels.

    Raises:
        ValueError: If *count* is less than 1.
    """
    check_count(count)
    inbox, outbox = Chan[int](1), Chan[int](1)
    doubler = tasks.spawn(_doubler, inbox, outbox)
    try:
        rate: float = tasks.spawn(_round_trips, inbox, outbox, count).wait(
            timeout=300.0
        )
        return rate
    finally:
        inbox.close()
        doubler.wait(timeout=60.0)


def task_cost(tasks: Runtime, count: int) -> TaskCost:
    """The cost of a parked task on the loop of *tasks*, over *count* coroutines
    run once as plain asyncio tasks and once as runtime tasks, each measured
    warmed (bytes_per_warmed()).

    Raises:
        ValueError: If *count* is less than 1.
    """
    end = functools.partial(_end, tasks)
    plain, parked = bytes_per_warmed(lambda: _start_plain(tasks, count), end, count)
    end(parked)
    net, parked = bytes_per_warmed(lambda: _start_tasks(tasks, count), end, count)
    end(parked)
    return TaskCost(asyncio=plain, runtime=net - plain)
