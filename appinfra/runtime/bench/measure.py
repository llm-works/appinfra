# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""What the benches of each task kind measure with: a count check, arrivals of
started tasks, bytes allocated per item, ending tasks, and the rates tasks spawn
and end at."""

from __future__ import annotations

import gc
import threading
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from ...log import Logger
from ..errors import StoppedError
from ..runtime import Runtime
from ..task import Task

T = TypeVar("T")

# Spawns *count* tasks of one kind on a runtime, each parked until it is stopped;
# returns them, and how many per second were spawned and running
SpawnParked = Callable[[Runtime, int], tuple[list[Task], float]]


@dataclass(frozen=True)
class TaskCost:
    """Bytes per parked task: what the same work costs without the runtime (a
    plain asyncio task, or a plain thread), and what the runtime adds."""

    base: float
    runtime: float

    @property
    def net(self) -> float:
        """What a parked task costs on the runtime, before what it holds."""
        return self.base + self.runtime


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


class ThreadArrivals(Arrivals):
    """Arrivals counted from any thread."""

    def __init__(self, expected: int) -> None:
        """Wait for *expected* arrivals.

        Raises:
            ValueError: If *expected* is less than 1: no arrival would set ``all``.
        """
        super().__init__(expected)
        self._lock = threading.Lock()

    def arrive(self) -> None:
        """Count one as started."""
        with self._lock:
            super().arrive()


def cancel_all(spawned: list[Task]) -> None:
    """Cancel every task of *spawned*, then wait until each has ended. A wait
    that raises does not keep the others from running: the first error is
    raised once all have."""
    for task in spawned:
        task.cancel()
    first: BaseException | None = None
    for task in spawned:
        try:
            task.wait(timeout=60.0)
        except StoppedError:  # Its stop ended it: no result
            pass
        except BaseException as e:
            first = first or e
    if first is not None:
        raise first


def spawn_parked(
    spawn: Callable[[], Task], count: int, arrived: Callable[[], None]
) -> list[Task]:
    """*count* tasks from *spawn*, each parked once *arrived* returns. If a
    spawn or *arrived* fails, the tasks already spawned are cancelled and ended
    before the error leaves: nothing else holds them.

    Raises:
        ValueError: If *count* is less than 1.
    """
    check_count(count)
    spawned: list[Task] = []
    try:
        # One at a time: a spawn that raises leaves the earlier ones listed
        for _ in range(count):
            spawned.append(spawn())  # noqa: PERF401
        arrived()
    except BaseException:
        cancel_all(spawned)
        raise
    return spawned


def spawn_and_cancel_rates(
    tasks: Runtime, count: int, spawn_parked: SpawnParked
) -> tuple[float, float]:
    """Tasks per second spawned and running, over *count* that *spawn_parked*
    parks on *tasks*, and tasks per second that cancel_all() ends: a cancel()
    of each, then a wait() of each.

    Raises:
        ValueError: If *count* is less than 1.
    """
    spawned, spawn = spawn_parked(tasks, count)
    began = time.perf_counter()
    cancel_all(spawned)
    return spawn, count / (time.perf_counter() - began)


def spawn_and_stop_rates(
    lg: Logger, count: int, spawn_parked: SpawnParked, timeout: float
) -> tuple[float, float]:
    """Tasks per second spawned and running, over *count* that *spawn_parked*
    parks on a runtime of its own, and tasks per second its one stop(), given
    *timeout*, then ends.

    Raises:
        ValueError: If *count* is less than 1.
    """
    with Runtime(lg) as rt:
        _, spawn = spawn_parked(rt, count)
        began = time.perf_counter()
        rt.stop(timeout=timeout)
        stop = count / (time.perf_counter() - began)
    return spawn, stop


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
