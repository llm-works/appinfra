# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Measure what services on a LoopHost cost: memory per service, start and stop rate,
and the submit/reply rate through an async channel.

The memory figure is the net cost of a service: a service holding nothing of its own,
idle on the loop, as an idle goroutine parks on a channel. It is asyncio's part (the
task, the coroutine, the instance, its wait) plus the framework's (the runner and its
bookkeeping); what a real service holds comes on top. The same services run once as
plain asyncio tasks and once under runners, and the difference is the framework's.

scripts/service_bench.py prints these numbers; the performance tests assert on them.
"""

from __future__ import annotations

import asyncio
import functools
import gc
import threading
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from ..log import Logger
from .base import AsyncService
from .channel import AsyncChannel, Message
from .factory import AsyncQueueChannelFactory
from .runner import LoopHost, TaskRunner

T = TypeVar("T")

ServiceMaker = Callable[[int, "Arrivals"], AsyncService]
"""Makes the i-th service of a run, which calls arrive() once its run() has started."""


class Arrivals:
    """Counts services whose run() has started; set once all *expected* have.
    Updated on the loop thread only."""

    def __init__(self, expected: int) -> None:
        """Wait for *expected* services.

        Raises:
            ValueError: If *expected* is less than 1: no arrival would set ``all``.
        """
        if expected < 1:
            raise ValueError(f"expected must be at least 1, got {expected}")
        self._left = expected
        self.all = threading.Event()

    def arrive(self) -> None:
        """Count one service as started."""
        self._left -= 1
        if self._left == 0:
            self.all.set()


class Minimal(AsyncService):
    """Holds nothing of its own: parks on an event all services share."""

    def __init__(
        self, lg: Logger, i: int, arrivals: Arrivals, shared: asyncio.Event
    ) -> None:
        """The *i*-th service, counted in *arrivals*, parking on *shared*."""
        self._lg = lg
        self._i = i
        self._arrivals = arrivals
        self._shared = shared

    @property
    def name(self) -> str:
        """``minimal-<i>``."""
        return f"minimal-{self._i}"

    async def run(self) -> None:  # type: ignore[override]
        """Arrive, then park on the shared event."""
        self._arrivals.arrive()
        await self._shared.wait()


class Doubler(AsyncService):
    """Replies to each request with its payload doubled."""

    def __init__(self, lg: Logger, inbox: AsyncChannel) -> None:
        """Answer the requests arriving on *inbox*."""
        self._lg = lg
        self._inbox = inbox

    @property
    def name(self) -> str:
        """``doubler``."""
        return "doubler"

    async def run(self) -> None:  # type: ignore[override]
        """Answer requests until cancelled."""
        while True:
            msg = await self._inbox.recv()
            await self._inbox.send(Message(id=msg.id, payload=msg.payload * 2))


@dataclass(frozen=True)
class Cost:
    """Bytes per idle service: asyncio's part and the framework's."""

    asyncio: float
    framework: float

    @property
    def net(self) -> float:
        """What a service costs on a LoopHost, before what it holds."""
        return self.asyncio + self.framework


def minimal_maker(lg: Logger) -> ServiceMaker:
    """A maker of Minimal services sharing one event."""
    return functools.partial(Minimal, lg, shared=asyncio.Event())


def start_runners(
    host: LoopHost, make: ServiceMaker, count: int
) -> tuple[list[TaskRunner], float]:
    """Start *count* services made by *make* and wait until each run() has started.

    Returns:
        The runners, and how many start() calls per second the loop took.
    """
    arrivals = Arrivals(count)
    runners = [host.runner(make(i, arrivals)) for i in range(count)]
    began = time.perf_counter()
    for runner in runners:
        runner.start()
    rate = count / (time.perf_counter() - began)
    if not arrivals.all.wait(timeout=60.0):
        raise TimeoutError(f"{count:,} services did not all start in 60 s")
    return runners, rate


def stop_runners(runners: list[TaskRunner]) -> float:
    """Stop *runners*; returns how many stop() calls per second that took."""
    began = time.perf_counter()
    for runner in runners:
        runner.stop()
    return len(runners) / (time.perf_counter() - began)


def start_plain(
    host: LoopHost, make: ServiceMaker, count: int
) -> list[asyncio.Task[None]]:
    """Run the run() of *count* services made by *make* as plain tasks on the
    host's loop, with no runner, and wait until each has started."""
    arrivals = Arrivals(count)
    services = [make(i, arrivals) for i in range(count)]
    tasks: list[asyncio.Task[None]] = []

    def spawn() -> None:
        tasks.extend(host.loop.create_task(s.run()) for s in services)

    host.loop.call_soon_threadsafe(spawn)
    if not arrivals.all.wait(timeout=60.0):
        raise TimeoutError(f"{count:,} tasks did not all start in 60 s")
    return tasks


def end_plain(host: LoopHost, tasks: list[asyncio.Task[None]]) -> None:
    """Cancel *tasks* on the host's loop and wait until they have ended."""

    async def end() -> None:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run_coroutine_threadsafe(end(), host.loop).result(timeout=60.0)


def bytes_per_service(start: Callable[[], T], count: int) -> tuple[float, T]:
    """Bytes allocated per service while *start* starts *count* of them, and what
    *start* returned."""
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.take_snapshot()
        started = start()
        after = tracemalloc.take_snapshot()
    finally:
        tracemalloc.stop()
    size = sum(d.size_diff for d in after.compare_to(before, "filename"))
    return size / count, started


def service_cost(host: LoopHost, lg: Logger, count: int) -> Cost:
    """The net cost of an idle service, over *count* Minimal services run once as
    plain tasks and once under runners."""
    make = minimal_maker(lg)
    plain, tasks = bytes_per_service(lambda: start_plain(host, make, count), count)
    end_plain(host, tasks)
    del tasks
    net, (runners, _) = bytes_per_service(
        lambda: start_runners(host, make, count), count
    )
    stop_runners(runners)
    return Cost(asyncio=plain, framework=net - plain)


def round_trip_rate(host: LoopHost, lg: Logger, count: int) -> float:
    """Round trips per second, *count* of them, from a caller on the loop to a
    Doubler and back."""
    pair = AsyncQueueChannelFactory().create_pair()
    runner = host.runner(Doubler(lg, pair.child))
    runner.start()
    runner.wait_healthy(timeout=5.0)

    async def round_trips() -> float:
        began = time.perf_counter()
        for i in range(count):
            await pair.parent.submit(Message(payload=i), timeout=5.0)
        return count / (time.perf_counter() - began)

    try:
        future = asyncio.run_coroutine_threadsafe(round_trips(), host.loop)
        return future.result(timeout=300.0)
    finally:
        runner.stop()
