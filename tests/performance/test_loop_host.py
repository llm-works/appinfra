# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
LoopHost benchmark: what many async services on one event loop thread cost.

Memory per idle service, start and stop rate, idle CPU, and the submit/reply rate
through an async channel. Each test prints its numbers; run with
``make test.perf.v`` to see them.

By default the benchmark runs 1,000 services, as a regression check that fits
``make check``. ``APPINFRA_SERVICE_BENCH=full`` runs 100,000.
"""

from __future__ import annotations

import asyncio
import gc
import os
import threading
import time
import tracemalloc
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.service import (
    AsyncChannel,
    AsyncQueueChannelFactory,
    AsyncService,
    LoopHost,
    Message,
    TaskRunner,
)

SERVICES = 100_000 if os.environ.get("APPINFRA_SERVICE_BENCH") == "full" else 1_000
# Seconds of wall time over which idle CPU is measured: two of the channel's
# 0.1 s polls, enough to show their cost
IDLE_WINDOW = 0.2
LG = MagicMock()


class Arrivals:
    """Counts services whose run() has started; set once all *expected* have.
    Updated on the loop thread only."""

    def __init__(self, expected: int) -> None:
        self._left = expected
        self.all = threading.Event()

    def arrive(self) -> None:
        self._left -= 1
        if self._left == 0:
            self.all.set()


class OnEvent(AsyncService):
    """Parks on an asyncio.Event nothing sets."""

    def __init__(self, i: int, arrivals: Arrivals) -> None:
        self._lg = LG
        self._i = i
        self._arrivals = arrivals

    @property
    def name(self) -> str:
        return f"event-{self._i}"

    async def run(self) -> None:
        self._arrivals.arrive()
        await asyncio.Event().wait()


class OnChannel(OnEvent):
    """Parks in recv() on an async channel nothing sends to."""

    def __init__(self, i: int, arrivals: Arrivals) -> None:
        super().__init__(i, arrivals)
        self._inbox = AsyncQueueChannelFactory().create_pair().child

    async def run(self) -> None:
        self._arrivals.arrive()
        await self._inbox.recv()


class Doubler(AsyncService):
    def __init__(self, inbox: AsyncChannel) -> None:
        self._lg = LG
        self._inbox = inbox

    @property
    def name(self) -> str:
        return "doubler"

    async def run(self) -> None:
        while True:
            msg = await self._inbox.recv()
            await self._inbox.send(Message(id=msg.id, payload=msg.payload * 2))


@pytest.fixture
def host() -> Iterator[LoopHost]:
    host = LoopHost(name="bench-loop")
    host.start()
    yield host
    host.stop(timeout=60.0)


def _start_all(
    host: LoopHost, cls: type[OnEvent], count: int
) -> tuple[list[TaskRunner], float]:
    """Start *count* services and wait until each run() has started.

    Returns:
        The runners, and how many start() calls per second the loop took.
    """
    arrivals = Arrivals(count)
    runners = [host.runner(cls(i, arrivals)) for i in range(count)]
    began = time.perf_counter()
    for runner in runners:
        runner.start()
    rate = count / (time.perf_counter() - began)
    assert arrivals.all.wait(timeout=60.0)
    return runners, rate


def _idle_cpu(window: float) -> float:
    """This process's CPU time over *window* seconds of wall time, as a fraction
    of one core."""
    cpu, wall = time.process_time(), time.monotonic()
    time.sleep(window)
    return (time.process_time() - cpu) / (time.monotonic() - wall)


class TestLoopHostCost:
    def test_memory_per_idle_service(self, host):
        """An idle service on a host costs its runner, its task and itself."""
        gc.collect()
        tracemalloc.start()
        try:
            before = tracemalloc.take_snapshot()
            runners, _ = _start_all(host, OnEvent, SERVICES)
            after = tracemalloc.take_snapshot()
        finally:
            tracemalloc.stop()
        per_service = sum(d.size_diff for d in after.compare_to(before, "filename"))
        per_service /= SERVICES
        for runner in runners:
            runner.stop()

        print(f"\nidle service on a LoopHost: {per_service:,.0f} B each ({SERVICES:,})")
        assert per_service < 6_000, f"{per_service:,.0f} B per idle service"

    def test_start_and_stop_rate(self, host):
        runners, start_rate = _start_all(host, OnEvent, SERVICES)
        began = time.perf_counter()
        for runner in runners:
            runner.stop()
        stop_rate = SERVICES / (time.perf_counter() - began)

        print(f"\nstart: {start_rate:,.0f}/s  stop: {stop_rate:,.0f}/s ({SERVICES:,})")
        assert start_rate > 5_000, f"start: {start_rate:,.0f}/s"
        assert stop_rate > 5_000, f"stop: {stop_rate:,.0f}/s"

    def test_idle_services_use_no_cpu(self, host):
        """Services parked on an await leave the loop asleep."""
        runners, _ = _start_all(host, OnEvent, SERVICES)
        cpu = _idle_cpu(IDLE_WINDOW)
        for runner in runners:
            runner.stop()

        print(f"\n{SERVICES:,} idle services: {cpu:.1%} of a core")
        assert cpu < 0.02, f"{cpu:.1%} of a core while idle"

    @pytest.mark.xfail(
        strict=True,
        reason="AsyncBufferedChannel.recv() wakes every 0.1 s to check for close",
    )
    def test_idle_channel_receivers_use_no_cpu(self, host):
        """Services parked in recv() on an async channel leave the loop asleep."""
        runners, _ = _start_all(host, OnChannel, SERVICES)
        cpu = _idle_cpu(IDLE_WINDOW)
        for runner in runners:
            runner.stop()

        print(f"\n{SERVICES:,} idle channel receivers: {cpu:.1%} of a core")
        assert cpu < 0.02, f"{cpu:.1%} of a core while idle"

    def test_submit_reply_rate(self, host):
        """Round trips from a caller on the loop to a service and back."""
        pair = AsyncQueueChannelFactory().create_pair()
        runner = host.runner(Doubler(pair.child))
        runner.start()
        runner.wait_healthy(timeout=5.0)

        async def round_trips(count: int) -> float:
            began = time.perf_counter()
            for i in range(count):
                await pair.parent.submit(Message(payload=i), timeout=5.0)
            return count / (time.perf_counter() - began)

        rate = asyncio.run_coroutine_threadsafe(round_trips(SERVICES), host.loop)
        trips = rate.result(timeout=120.0)
        runner.stop()

        print(f"\nsubmit/reply: {trips:,.0f} round trips/s")
        assert trips > 10_000, f"{trips:,.0f} round trips/s"
