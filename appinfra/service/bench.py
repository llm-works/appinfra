# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Measure what async services on one event loop cost: memory per service, the rate a
Runtime spawns and stops them one at a time and all at once, and the request/reply rate
between two of them: each request carries the Chan its reply comes back on. The services
run on the service Runtime's loop.

The memory figure is the net cost of a service: a service holding nothing of its own,
idle on the loop, as an idle goroutine parks on a channel. It is asyncio's part (the
task, the coroutine, the instance, its wait) plus the framework's (the runner, the
service's task and token, the runtime's bookkeeping); what a real service holds comes
on top. The same services run once as plain asyncio tasks and once spawned into a
Runtime, and the difference is the framework's.

scripts/runtime_bench.py prints these numbers next to appinfra.runtime.bench's; the
performance tests assert on them.
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass

from ..log import Logger
from ..runtime import Chan
from ..runtime import Runtime as Tasks
from ..runtime.bench import Arrivals, bytes_per_warmed, check_count
from .base import AsyncService
from .runtime import Runner, Runtime

ServiceMaker = Callable[[int, Arrivals], AsyncService]
"""Makes the i-th service of a run, which calls arrive() once its run() has started."""

Requests = Chan[tuple[int, Chan[int]]]
"""What a Doubler answers: a value, and the Chan its reply goes back on."""


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
    """Replies to each request with its value doubled."""

    def __init__(self, lg: Logger, requests: Requests) -> None:
        """Answer the requests arriving on *requests*."""
        self._lg = lg
        self._requests = requests

    @property
    def name(self) -> str:
        """``doubler``."""
        return "doubler"

    async def run(self) -> None:  # type: ignore[override]
        """Answer requests until stopped."""
        async for value, reply in self._requests:
            await reply.asend(value * 2)


@dataclass(frozen=True)
class Cost:
    """Bytes per idle service: asyncio's part and the framework's."""

    asyncio: float
    framework: float

    @property
    def net(self) -> float:
        """What a service costs on the loop, before what it holds."""
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


def spawn_services(
    rt: Runtime, make: ServiceMaker, count: int
) -> tuple[list[Runner], float]:
    """Spawn *count* services made by *make* into *rt* and wait until each run()
    has started.

    Returns:
        The runners, and how many services per second were spawned and ran:
        timed until each run() has started, not until the last spawn() returns,
        as how much of the loop's share falls before that depends on how the
        GIL switches between the threads.
    """
    arrivals = Arrivals(count)
    services = [make(i, arrivals) for i in range(count)]
    began = time.perf_counter()
    runners = [rt.spawn(service) for service in services]
    if not arrivals.all.wait(timeout=60.0):
        raise TimeoutError(f"{count:,} services did not all start in 60 s")
    return runners, count / (time.perf_counter() - began)


def stop_services(rt: Runtime, runners: list[Runner]) -> float:
    """Stop *runners* in *rt*, one stop_service() each; returns how many per
    second that took."""
    began = time.perf_counter()
    for runner in runners:
        rt.stop_service(runner)
    return len(runners) / (time.perf_counter() - began)


def runtime_rates(lg: Logger, make: ServiceMaker, count: int) -> tuple[float, float]:
    """spawn() and stop() rates of a Runtime of its own over *count* services
    made by *make*, independent of each other.

    Returns:
        Services per second spawned and running (timed until each run() has
        started, as spawn_services() is), and services stopped per second by
        one stop(), which stops them in reverse start order and then the
        runtime's tasks.

    Raises:
        ValueError: If *count* is less than 1.
    """
    arrivals = Arrivals(count)
    with Runtime(lg) as rt:
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
    tasks: Tasks, make: ServiceMaker, count: int
) -> list[asyncio.Task[None]]:
    """Run the run() of *count* services made by *make* as plain asyncio tasks on
    the loop of *tasks*, with no runner, and wait until each has started."""
    arrivals = Arrivals(count)
    services = [make(i, arrivals) for i in range(count)]

    async def spawn() -> list[asyncio.Task[None]]:
        return [asyncio.create_task(s.run()) for s in services]

    plain: list[asyncio.Task[None]] = tasks.spawn(spawn).wait(timeout=60.0)
    if not arrivals.all.wait(timeout=60.0):
        raise TimeoutError(f"{count:,} tasks did not all start in 60 s")
    return plain


def end_plain(tasks: Tasks, plain: list[asyncio.Task[None]]) -> None:
    """Cancel the asyncio tasks *plain* on the loop of *tasks* and wait until they
    have ended."""

    async def end() -> None:
        for task in plain:
            task.cancel()
        await asyncio.gather(*plain, return_exceptions=True)

    tasks.spawn(end).wait(timeout=60.0)


def _check_idle(runners: list[Runner]) -> None:
    """Refuse a measurement of services that ended: what a failed one holds
    (its error and traceback) is not what an idle one costs.

    Raises:
        RuntimeError: If one of *runners* has failed.
    """
    failed = [r for r in runners if r.exception is not None]
    if failed:
        raise RuntimeError(
            f"{len(failed):,} of {len(runners):,} measured services failed, "
            f"first: {failed[0].exception!r}"
        )


def service_cost(tasks: Tasks, rt: Runtime, lg: Logger, count: int) -> Cost:
    """The net cost of an idle service, over *count* Minimal services run once as
    plain asyncio tasks on the loop of *tasks* and once spawned into *rt*, each
    measured warmed (bytes_per_warmed()). Each run has a maker of its own: the
    event its services share binds to the loop that first waits on it."""
    make = minimal_maker(lg)
    plain, aio = bytes_per_warmed(
        lambda: start_plain(tasks, make, count),
        lambda started: end_plain(tasks, started),
        count,
    )
    end_plain(tasks, aio)
    del aio
    make = minimal_maker(lg)
    net, (runners, _) = bytes_per_warmed(
        lambda: spawn_services(rt, make, count),
        lambda started: stop_services(rt, started[0]),
        count,
    )
    _check_idle(runners)
    stop_services(rt, runners)
    return Cost(asyncio=plain, framework=net - plain)


class _Caller(AsyncService):
    """Submits *count* requests to a Doubler on the same loop, one at a time,
    and reports the round trips per second in *rate*."""

    def __init__(
        self, lg: Logger, requests: Requests, count: int, rate: Future[float]
    ) -> None:
        self._lg = lg
        self._requests = requests
        self._count = count
        self._rate = rate

    @property
    def name(self) -> str:
        """``caller``."""
        return "caller"

    @property
    def depends_on(self) -> list[str]:
        """The Doubler it calls."""
        return ["doubler"]

    async def run(self) -> None:  # type: ignore[override]
        """Make the round trips, report their rate, then park until stopped."""
        try:
            began = time.perf_counter()
            for i in range(self._count):
                reply: Chan[int] = Chan(1)
                await self._requests.asend((i, reply), timeout=5.0)
                await reply.arecv(timeout=5.0)
            self._rate.set_result(self._count / (time.perf_counter() - began))
        except Exception as e:
            self._rate.set_exception(e)
        await asyncio.Event().wait()


def round_trip_rate(lg: Logger, count: int) -> float:
    """Round trips per second, *count* of them, from a caller service to a
    Doubler and back, both on the loop of a Runtime of their own.

    Raises:
        ValueError: If *count* is less than 1.
    """
    check_count(count)
    requests: Requests = Chan(1)
    rate: Future[float] = Future()
    with Runtime(lg) as rt:
        rt.spawn(_Caller(lg, requests, count, rate))
        rt.ready(rt.spawn(Doubler(lg, requests)), timeout=5.0)
        return rate.result(timeout=300.0)
