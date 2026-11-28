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
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import time
from collections.abc import Iterator
from dataclasses import dataclass

from ...log import Logger
from ..chan import Chan
from ..runtime import Runtime
from ..task import Task
from .measure import (
    Arrivals,
    TaskCost,
    bytes_per_warmed,
    cancel_all,
    check_count,
    spawn_and_cancel_rates,
    spawn_and_stop_rates,
    spawn_parked,
)


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

    def arrived() -> None:
        """Wait until every task runs.

        Raises:
            TimeoutError: If they did not all start in 60 s.
        """
        if not arrivals.all.wait(timeout=60.0):
            raise TimeoutError(f"{count:,} runtime tasks did not all start in 60 s")

    began = time.perf_counter()
    spawned = spawn_parked(lambda: tasks.spawn(_parked_alone, arrivals), count, arrived)
    return spawned, count / (time.perf_counter() - began)


async def _receiving(arrivals: Arrivals, inbox: Chan[int]) -> None:
    """Arrive, then park in arecv() on *inbox*, which nothing sends to."""
    arrivals.arrive()
    await inbox.arecv()


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
        cancel_all(spawned)


def loop_rates(tasks: Runtime, count: int) -> tuple[float, float]:
    """Tasks per second spawned and running, over *count* parked tasks on the
    loop of *tasks*, and tasks per second that cancel() and wait() then end,
    one task after the other.

    Raises:
        ValueError: If *count* is less than 1.
    """
    return spawn_and_cancel_rates(tasks, count, _spawn_parked)


def loop_runtime_rates(lg: Logger, count: int) -> tuple[float, float]:
    """Tasks per second spawned and running, over *count* parked tasks on a
    runtime of its own, and tasks per second its one stop() then ends: it
    stops every task's token, cancels the tasks and shuts the loop down.

    Raises:
        ValueError: If *count* is less than 1.
    """
    return spawn_and_stop_rates(lg, count, _spawn_parked, timeout=60.0)


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


def loop_round_trip_rate(tasks: Runtime, count: int) -> float:
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


def loop_cost(tasks: Runtime, count: int) -> TaskCost:
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
    return TaskCost(base=plain, runtime=net - plain)
