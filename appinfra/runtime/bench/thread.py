# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Measure what a task on a thread of its own costs: bytes per parked task, the part
a plain thread takes and the part the runtime adds, the rate tasks spawn and end,
and the round-trip rate over channels between two tasks, sync on both sides.

The same function runs once on plain threads and once spawned as runtime tasks;
the difference is the runtime's: its task, the handle, the child token, the
context the call runs in. tracemalloc sees Python's allocations only: a thread's
stack, which the OS maps for it, is not counted in either.
"""

from __future__ import annotations

import functools
import threading
import time
from dataclasses import dataclass

from ...log import Logger
from ..chan import Chan
from ..runtime import Runtime
from ..task import Task, stopping
from .measure import (
    TaskCost,
    ThreadArrivals,
    bytes_per_warmed,
    check_count,
    spawn_and_cancel_rates,
    spawn_and_stop_rates,
    spawn_parked,
)


def _parked(arrivals: ThreadArrivals, event: threading.Event) -> None:
    """Arrive, then park on *event*: for memory, as the tasks then hold nothing
    of their own."""
    arrivals.arrive()
    event.wait()


def _parked_alone(arrivals: ThreadArrivals) -> None:
    """Arrive, then park until the task is stopped: for rates."""
    arrivals.arrive()
    stopping().wait()


@dataclass(frozen=True)
class _Parked:
    """The threads or tasks of one run, and the event they park on."""

    event: threading.Event
    plain: list[threading.Thread]
    spawned: list[Task]


def _arrived(arrivals: ThreadArrivals, count: int, what: str) -> None:
    """Wait until *count* of *what* have arrived.

    Raises:
        TimeoutError: If they did not all arrive in 60 s.
    """
    if not arrivals.all.wait(timeout=60.0):
        raise TimeoutError(f"{count:,} {what} did not all start in 60 s")


def _start_plain(count: int) -> _Parked:
    """*count* plain threads, each parked by the time this returns. If they do
    not all start, those that did are released: nothing else sets their event."""
    arrivals, event = ThreadArrivals(count), threading.Event()
    plain = [
        threading.Thread(target=_parked, args=(arrivals, event), daemon=True)
        for _ in range(count)
    ]
    try:
        for thread in plain:
            thread.start()
        _arrived(arrivals, count, "threads")
    except BaseException:
        event.set()
        raise
    return _Parked(event, plain, [])


def _start_tasks(tasks: Runtime, count: int) -> _Parked:
    """*count* thread tasks on *tasks*, each parked by the time this returns. If
    they do not all start, those that did are released: they park on the event,
    not on their token, so a stop of *tasks* would not."""
    arrivals, event = ThreadArrivals(count), threading.Event()
    try:
        spawned = [tasks.spawn(_parked, arrivals, event) for _ in range(count)]
        _arrived(arrivals, count, "thread tasks")
    except BaseException:
        event.set()
        raise
    return _Parked(event, [], spawned)


def _end(parked: _Parked) -> None:
    """Release the threads or tasks of *parked* and wait until each has ended."""
    parked.event.set()
    for thread in parked.plain:
        thread.join(timeout=60.0)
    for task in parked.spawned:
        task.wait(timeout=60.0)


def _spawn_parked(tasks: Runtime, count: int) -> tuple[list[Task], float]:
    """Spawn *count* thread tasks parked until stopped on *tasks*; returns them,
    and how many per second were spawned and running."""
    arrivals = ThreadArrivals(count)
    began = time.perf_counter()
    spawned = spawn_parked(
        lambda: tasks.spawn(_parked_alone, arrivals),
        count,
        lambda: _arrived(arrivals, count, "thread tasks"),
    )
    return spawned, count / (time.perf_counter() - began)


def thread_cost(tasks: Runtime, count: int) -> TaskCost:
    """The cost of a parked thread task on *tasks*, over *count* threads run
    once as plain threads and once as runtime tasks, each measured warmed
    (bytes_per_warmed()).

    Raises:
        ValueError: If *count* is less than 1.
    """
    plain, parked = bytes_per_warmed(lambda: _start_plain(count), _end, count)
    _end(parked)
    start = functools.partial(_start_tasks, tasks, count)
    net, parked = bytes_per_warmed(start, _end, count)
    _end(parked)
    return TaskCost(base=plain, runtime=net - plain)


def thread_rates(tasks: Runtime, count: int) -> tuple[float, float]:
    """Thread tasks per second spawned and running, over *count* parked on
    *tasks*, and tasks per second that cancel() and wait() then end, one task
    after the other.

    Raises:
        ValueError: If *count* is less than 1.
    """
    return spawn_and_cancel_rates(tasks, count, _spawn_parked)


def thread_runtime_rates(lg: Logger, count: int) -> tuple[float, float]:
    """Thread tasks per second spawned and running, over *count* parked on a
    runtime of its own, and tasks per second its one stop() then ends: it stops
    every task's token and waits for each thread to return.

    Raises:
        ValueError: If *count* is less than 1.
    """
    return spawn_and_stop_rates(lg, count, _spawn_parked, timeout=60.0)


def doubler(inbox: Chan[int], outbox: Chan[int]) -> None:
    """Answer each value on *inbox* with it doubled, until *inbox* is closed.
    Sync, and at module level: a thread task, or a process task."""
    for value in inbox:
        outbox.send(value * 2, timeout=60.0)


def round_trips(inbox: Chan[int], outbox: Chan[int], count: int) -> float:
    """*count* round trips to a doubler, sync; returns how many per second."""
    began = time.perf_counter()
    for i in range(count):
        inbox.send(i, timeout=60.0)
        outbox.recv(timeout=60.0)
    return count / (time.perf_counter() - began)


def thread_round_trip_rate(tasks: Runtime, count: int) -> float:
    """Round trips per second, *count* of them, from a thread task on *tasks* to
    a doubler thread task and back, over two channels.

    Raises:
        ValueError: If *count* is less than 1.
    """
    check_count(count)
    inbox, outbox = Chan[int](1), Chan[int](1)
    doubling = tasks.spawn(doubler, inbox, outbox)
    try:
        rate: float = tasks.spawn(round_trips, inbox, outbox, count).wait(timeout=300.0)
        return rate
    finally:
        inbox.close()
        doubling.wait(timeout=60.0)
