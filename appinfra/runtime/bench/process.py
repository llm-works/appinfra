# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Measure what a task in a process of its own costs: the resident memory of its
child, the rate tasks spawn and end, and the round-trip rate over process Chans
between a task in the parent and one in a child.

A child's memory is measured twice once it runs. Its private memory, on Linux,
is what each more task costs: the pages it alone holds, its own objects and the
link to the parent, while the interpreter and the modules the fork server
imported stay shared. Its resident set, as ps reports it on Linux and macOS,
counts those shared pages in every child, so it is more than each child adds.
Not the child's own getrusage(): its peak resident set starts from the process
it was forked from. The functions the children run are at module level, as the
child imports them by name.

The runtime the tasks are spawned on needs a real logger: it is carried into each
child its Chans cross to, which a mock cannot be.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass

from ...log import Logger
from ..chan import Chan
from ..runtime import Runtime
from ..task import Task, stopping
from .measure import (
    cancel_all,
    check_count,
    spawn_and_cancel_rates,
    spawn_and_stop_rates,
    spawn_parked,
)
from .thread import doubler, round_trips

# Seconds a child may take to start, or a call on a process Chan to end: a fresh
# interpreter starts in tens of milliseconds, far more on a loaded runner
DUE = 120.0


def parked(arrived: Chan[bool]) -> None:
    """Say on *arrived* that this child runs, then park until the task is
    stopped."""
    arrived.send(True, timeout=DUE)
    stopping().wait()


def _spawn_parked(tasks: Runtime, count: int) -> tuple[list[Task], float]:
    """Spawn *count* process tasks parked until stopped on *tasks*; returns them,
    and how many per second were spawned and running.

    Raises:
        ValueError: If *count* is less than 1.
    """
    check_count(count)
    arrivals: Chan[bool] = Chan(count, process=True)

    def arrived() -> None:
        """Wait until every child has said it runs.

        Raises:
            TimeoutError: If one did not within DUE seconds.
        """
        for _ in range(count):
            arrivals.recv(timeout=DUE)

    began = time.perf_counter()
    spawned = spawn_parked(
        lambda: tasks.spawn(parked, arrivals, process=True), count, arrived
    )
    return spawned, count / (time.perf_counter() - began)


def _resident(spawned: list[Task]) -> float:
    """The mean resident set, in bytes, of the children of *spawned*: ps prints
    it in KiB, on Linux and macOS alike.

    Raises:
        subprocess.CalledProcessError: If ps fails, as for a child already gone.
    """
    details = [t.process.detail() for t in spawned if t.process is not None]
    pids = ",".join(str(d.pid) for d in details if d.pid is not None)
    out = subprocess.run(
        ["ps", "-o", "rss=", "-p", pids], capture_output=True, text=True, check=True
    ).stdout
    sizes = [int(line) for line in out.split()]
    return 1024 * sum(sizes) / len(sizes)


def _private(spawned: list[Task]) -> float | None:
    """The mean private memory, in bytes, of the children of *spawned*: the
    pages each holds that no other process shares, from /proc's smaps_rollup.
    None off Linux, which has no such file.

    Raises:
        FileNotFoundError: If a child is already gone.
    """
    if not sys.platform.startswith("linux"):
        return None
    details = [t.process.detail() for t in spawned if t.process is not None]
    sizes = [_private_of(d.pid) for d in details if d.pid is not None]
    return sum(sizes) / len(sizes)


def _private_of(pid: int) -> int:
    """The private memory, in bytes, of process *pid*: its clean and dirty
    private pages, which smaps_rollup gives in KiB."""
    total = 0
    with open(f"/proc/{pid}/smaps_rollup") as rollup:
        for line in rollup:
            if line.startswith(("Private_Clean:", "Private_Dirty:")):
                total += int(line.split()[1])
    return 1024 * total


@dataclass(frozen=True)
class ProcessCost:
    """What a parked process task's child holds, in bytes: its resident set,
    pages it shares with other processes too, and its private memory, what it
    alone holds (None off Linux)."""

    resident: float
    private: float | None


def process_cost(tasks: Runtime, count: int) -> ProcessCost:
    """The mean memory of the children of *count* parked process tasks on
    *tasks*.

    Raises:
        ValueError: If *count* is less than 1.
    """
    spawned, _ = _spawn_parked(tasks, count)
    try:
        return ProcessCost(_resident(spawned), _private(spawned))
    finally:
        cancel_all(spawned)


def process_rates(tasks: Runtime, count: int) -> tuple[float, float]:
    """Process tasks per second spawned and running, over *count* parked on
    *tasks*, and tasks per second that a cancel() of each, then a wait() of
    each, ends.

    Raises:
        ValueError: If *count* is less than 1.
    """
    return spawn_and_cancel_rates(tasks, count, _spawn_parked)


def process_runtime_rates(lg: Logger, count: int) -> tuple[float, float]:
    """Process tasks per second spawned and running, over *count* parked on a
    runtime of its own, and tasks per second its one stop() then ends: it stops
    every task's token and waits for each child to exit.

    Raises:
        ValueError: If *count* is less than 1.
    """
    return spawn_and_stop_rates(lg, count, _spawn_parked, timeout=DUE)


def process_round_trip_rate(tasks: Runtime, count: int) -> float:
    """Round trips per second, *count* of them, from a thread task on *tasks* to
    a doubler in a process task and back, over two process Chans homed here.

    Raises:
        ValueError: If *count* is less than 1.
    """
    check_count(count)
    inbox: Chan[int] = Chan(1, process=True)
    outbox: Chan[int] = Chan(1, process=True)
    doubling = tasks.spawn(doubler, inbox, outbox, process=True)
    try:
        rate: float = tasks.spawn(round_trips, inbox, outbox, count).wait(timeout=600.0)
        return rate
    finally:
        inbox.close()
        doubling.wait(timeout=DUE)
