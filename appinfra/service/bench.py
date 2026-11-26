# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Measure what services on a LoopHost cost: memory per service, start and stop rate of
their runners and of a Runtime's spawn() and stop(), and the submit/reply rate through
an async channel.

The memory figure is the net cost of a service: a service holding nothing of its own,
idle on the loop, as an idle goroutine parks on a channel. It is asyncio's part (the
task, the coroutine, the instance, its wait) plus the framework's (the runner and its
bookkeeping); what a real service holds comes on top. The same services run once as
plain asyncio tasks and once under runners, and the difference is the framework's.

scripts/runtime_bench.py prints these numbers next to appinfra.runtime.bench's; the
performance tests assert on them.
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..log import Logger
from ..runtime.bench import Arrivals, bytes_per_warmed, check_count
from .base import AsyncService
from .channel import AsyncChannel, Message
from .factory import AsyncQueueChannelFactory
from .runtime import LoopHost, Runtime, TaskRunner

ServiceMaker = Callable[[int, Arrivals], AsyncService]
"""Makes the i-th service of a run, which calls arrive() once its run() has started."""


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
    """A maker of Minimal services sharing one event: for memory, as they then
    hold nothing of their own."""
    return functools.partial(Minimal, lg, shared=asyncio.Event())


def parked_maker(lg: Logger) -> ServiceMaker:
    """A maker of Minimal services each parked on an event of its own: for rates.
    Cancelling a waiter of an asyncio.Event removes it from the event's waiters
    by a linear scan; a stop in reverse start order, as a Runtime's, scans all
    of one shared event's waiters each time, which would time asyncio, not the
    framework."""

    def make(i: int, arrivals: Arrivals) -> AsyncService:
        return Minimal(lg, i, arrivals, asyncio.Event())

    return make


def start_runners(
    host: LoopHost, make: ServiceMaker, count: int
) -> tuple[list[TaskRunner], float]:
    """Start *count* services made by *make* and wait until each run() has started.

    Returns:
        The runners, and how many services per second started and ran: timed
        until each run() has started, not until the last start() returns, as
        how much of the loop's share falls before that depends on how the GIL
        switches between the threads.
    """
    arrivals = Arrivals(count)
    runners = [host.runner(make(i, arrivals)) for i in range(count)]
    began = time.perf_counter()
    for runner in runners:
        runner.start()
    if not arrivals.all.wait(timeout=60.0):
        raise TimeoutError(f"{count:,} services did not all start in 60 s")
    return runners, count / (time.perf_counter() - began)


def stop_runners(runners: list[TaskRunner]) -> float:
    """Stop *runners*; returns how many stop() calls per second that took."""
    began = time.perf_counter()
    for runner in runners:
        runner.stop()
    return len(runners) / (time.perf_counter() - began)


def runtime_rates(lg: Logger, make: ServiceMaker, count: int) -> tuple[float, float]:
    """spawn() and stop() rates of a Runtime over *count* services made by *make*,
    independent of each other: it picks each a runner on its own loop and tracks
    it for ordering, restarts and stop.

    Returns:
        Services per second spawned and running (timed until each run() has
        started, as start_runners() is), and services stopped per second by
        one stop(), which stops them in reverse start order and then the
        runtime's loop.

    Raises:
        ValueError: If *count* is less than 1.
    """
    arrivals = Arrivals(count)
    with Runtime(lg, name="bench-runtime") as rt:
        began = time.perf_counter()
        for i in range(count):
            rt.spawn(make(i, arrivals))
        if not arrivals.all.wait(timeout=60.0):
            raise TimeoutError(f"{count:,} spawned services did not all start in 60 s")
        spawn = count / (time.perf_counter() - began)
        began = time.perf_counter()
        rt.stop(timeout=60.0)
        stop = count / (time.perf_counter() - began)
    return spawn, stop


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


def service_cost(host: LoopHost, lg: Logger, count: int) -> Cost:
    """The net cost of an idle service, over *count* Minimal services run once as
    plain tasks and once under runners, each measured warmed
    (bytes_per_warmed())."""
    make = minimal_maker(lg)
    plain, tasks = bytes_per_warmed(
        lambda: start_plain(host, make, count),
        lambda started: end_plain(host, started),
        count,
    )
    end_plain(host, tasks)
    del tasks
    net, (runners, _) = bytes_per_warmed(
        lambda: start_runners(host, make, count),
        lambda started: stop_runners(started[0]),
        count,
    )
    stop_runners(runners)
    return Cost(asyncio=plain, framework=net - plain)


def round_trip_rate(host: LoopHost, lg: Logger, count: int) -> float:
    """Round trips per second, *count* of them, from a caller on the loop to a
    Doubler and back.

    Raises:
        ValueError: If *count* is less than 1.
    """
    check_count(count)
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
