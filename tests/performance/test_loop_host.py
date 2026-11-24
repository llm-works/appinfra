# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
LoopHost benchmark: what many async services on one event loop thread cost.

The net memory cost of an idle service and the part of it the framework adds over
plain asyncio tasks, start and stop rate, idle CPU, and the submit/reply rate through
an async channel, measured with appinfra.service.bench. Each test prints its numbers;
run with ``make test.perf.v`` to see them.

By default the benchmark runs 1,000 services, as a regression check that fits
``make check``. ``APPINFRA_SERVICE_BENCH=full`` runs 100,000.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.service import AsyncQueueChannelFactory, AsyncService, LoopHost
from appinfra.service.bench import (
    Arrivals,
    round_trip_rate,
    service_cost,
    start_runners,
    stop_runners,
)

SERVICES = 100_000 if os.environ.get("APPINFRA_SERVICE_BENCH") == "full" else 1_000
# Seconds of wall time over which idle CPU is measured: long enough to catch two
# wakeups of a recv() that polled every 0.1 s
IDLE_WINDOW = 0.2
# Share of the rate floors enforced on macOS: its CI runners measure start and stop
# rates just under the Linux floor; the full floor applies on Linux
RATE_SHARE = 0.5 if sys.platform == "darwin" else 1.0
LG = MagicMock()


class OnEvent(AsyncService):
    """Parks on an asyncio.Event of its own that nothing sets."""

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


@pytest.fixture
def host() -> Iterator[LoopHost]:
    host = LoopHost(name="bench-loop")
    host.start()
    yield host
    host.stop(timeout=60.0)


def _idle_cpu(window: float) -> float:
    """This process's CPU time over *window* seconds of wall time, as a fraction
    of one core."""
    cpu, wall = time.process_time(), time.monotonic()
    time.sleep(window)
    return (time.process_time() - cpu) / (time.monotonic() - wall)


class TestLoopHostCost:
    def test_memory_per_idle_service(self, host):
        """Only the framework's part of the net cost is bounded: asyncio's part
        varies with the Python version."""
        cost = service_cost(host, LG, SERVICES)

        print(
            f"\nnet cost of an idle service on a LoopHost ({SERVICES:,}): "
            f"{cost.net:,.0f} B each: asyncio {cost.asyncio:,.0f} B, "
            f"framework {cost.framework:,.0f} B"
        )
        assert cost.framework < 1_200, f"{cost.framework:,.0f} B per service"

    def test_start_and_stop_rate(self, host):
        runners, start_rate = start_runners(host, OnEvent, SERVICES)
        stop_rate = stop_runners(runners)

        print(f"\nstart: {start_rate:,.0f}/s  stop: {stop_rate:,.0f}/s ({SERVICES:,})")
        assert start_rate > 5_000 * RATE_SHARE, f"start: {start_rate:,.0f}/s"
        assert stop_rate > 5_000 * RATE_SHARE, f"stop: {stop_rate:,.0f}/s"

    def test_idle_services_use_no_cpu(self, host):
        """Services parked on an await leave the loop asleep."""
        runners, _ = start_runners(host, OnEvent, SERVICES)
        cpu = _idle_cpu(IDLE_WINDOW)
        stop_runners(runners)

        print(f"\n{SERVICES:,} idle services: {cpu:.1%} of a core")
        assert cpu < 0.02, f"{cpu:.1%} of a core while idle"

    def test_idle_channel_receivers_use_no_cpu(self, host):
        """Services parked in recv() on an async channel leave the loop asleep."""
        runners, _ = start_runners(host, OnChannel, SERVICES)
        cpu = _idle_cpu(IDLE_WINDOW)
        stop_runners(runners)

        print(f"\n{SERVICES:,} idle channel receivers: {cpu:.1%} of a core")
        assert cpu < 0.02, f"{cpu:.1%} of a core while idle"

    @pytest.mark.skipif(
        sys.platform == "darwin",
        reason="macOS CI runners run this an order of magnitude slower than Linux; "
        "the floor is enforced on Linux only",
    )
    def test_submit_reply_rate(self, host):
        """Round trips from a caller on the loop to a service and back."""
        trips = round_trip_rate(host, LG, SERVICES)

        print(f"\nsubmit/reply: {trips:,.0f} round trips/s")
        assert trips > 10_000, f"{trips:,.0f} round trips/s"
