# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Runtime benchmark: what tasks of each kind cost, on the event loop, on a thread of
their own and in a process of their own.

The part of a parked task's memory the runtime adds over a plain asyncio task or a
plain thread (and a process task's resident set), the rate tasks spawn and end,
alone and by a runtime's stop(), idle CPU, and round trips over channels, measured
with appinfra.runtime.bench; run with ``make test.perf.v`` to see the numbers.

By default the benchmark runs 1,000 loop tasks, 100 thread tasks and 4 process
tasks, as a regression check that fits ``make check``: the memory measurement
varies by tens of bytes there, well within its ceiling.
``APPINFRA_RUNTIME_BENCH=full`` runs 100,000, 1,000 and 20.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.log import LogConfig, LoggerFactory
from appinfra.runtime import Runtime
from appinfra.runtime.bench import (
    loop_cost,
    loop_rates,
    loop_round_trip_rate,
    loop_runtime_rates,
    parked,
    process_cost,
    process_rates,
    process_round_trip_rate,
    process_runtime_rates,
    thread_cost,
    thread_rates,
    thread_round_trip_rate,
    thread_runtime_rates,
)
from tests.helpers.perf import RATE_SHARE, rates_over

FULL = os.environ.get("APPINFRA_RUNTIME_BENCH") == "full"
TASKS = 100_000 if FULL else 1_000
THREADS = 1_000 if FULL else 100
PROCESSES = 20 if FULL else 4
# What the runtime may add per parked task over a plain asyncio task: its task,
# the handle, the child token, the context the call runs in. 1 KiB, as for a
# service: macOS measures more than Linux
CEILING = 1024
# The same over a plain thread: Linux measures 0.9 to 1.1 KiB
THREAD_CEILING = 2048
# What a process task's child may hold resident: the interpreter, appinfra and
# pytest's main module, about 40 MiB on Linux
PROCESS_CEILING = 256 * 2**20
# Seconds of wall time over which idle CPU is measured: long enough to catch two
# wakeups of a receive that polled every 0.1 s
IDLE_WINDOW = 0.2
LG = MagicMock()


@pytest.fixture
def rt() -> Iterator[Runtime]:
    rt = Runtime(LG)
    rt.start()
    yield rt
    rt.stop(timeout=60.0)


@pytest.fixture
def real_lg():
    """A real logger: a runtime carries it into each child its Chans cross to,
    which a mock cannot be."""
    return LoggerFactory.create_root(LogConfig.from_params(level="warning"))


@pytest.fixture
def prt(real_lg) -> Iterator[Runtime]:
    """A runtime for process tasks."""
    rt = Runtime(real_lg)
    rt.start()
    yield rt
    rt.stop(timeout=60.0)


def _idle_cpu(window: float) -> float:
    """This process's CPU time over *window* seconds of wall time, as a fraction
    of one core."""
    cpu, wall = time.process_time(), time.monotonic()
    time.sleep(window)
    return (time.process_time() - cpu) / (time.monotonic() - wall)


class TestTaskCost:
    def test_memory_per_parked_task(self, rt):
        cost = loop_cost(rt, TASKS)

        print(
            f"\nnet cost of a parked loop task ({TASKS:,}): {cost.net:,.0f} B each: "
            f"asyncio {cost.base:,.0f} B, runtime {cost.runtime:,.0f} B"
        )
        assert cost.runtime <= CEILING, f"{cost.runtime:,.0f} B per task"

    def test_spawn_and_cancel_rate(self, rt):
        """spawn() until each runs, then a cancel() of each and a wait() of each."""
        floor = 5_000 * RATE_SHARE
        spawn, cancel = rates_over(floor, lambda: loop_rates(rt, TASKS))

        print(f"\nspawn: {spawn:,.0f}/s  cancel: {cancel:,.0f}/s ({TASKS:,})")
        assert spawn > floor, f"spawn: {spawn:,.0f}/s"
        assert cancel > floor, f"cancel: {cancel:,.0f}/s"

    def test_runtime_spawn_and_stop_rate(self):
        """spawn() into a runtime of its own, then one stop() of it."""
        floor = 5_000 * RATE_SHARE
        spawn, stop = rates_over(floor, lambda: loop_runtime_rates(LG, TASKS))

        print(f"\nruntime spawn: {spawn:,.0f}/s  stop: {stop:,.0f}/s ({TASKS:,})")
        assert spawn > floor, f"spawn: {spawn:,.0f}/s"
        assert stop > floor, f"stop: {stop:,.0f}/s"

    @pytest.mark.parametrize("receiving", [False, True], ids=["future", "arecv"])
    def test_idle_tasks_use_no_cpu(self, rt, receiving):
        """Tasks parked on an await, a future's or a channel's arecv(), leave
        the loop asleep."""
        with parked(rt, TASKS, receiving=receiving):
            cpu = _idle_cpu(IDLE_WINDOW)

        print(f"\n{TASKS:,} idle tasks: {cpu:.1%} of a core")
        assert cpu < 0.02, f"{cpu:.1%} of a core while idle"

    @pytest.mark.skipif(
        sys.platform == "darwin",
        reason="macOS CI runners run this an order of magnitude slower than Linux; "
        "the floor is enforced on Linux only",
    )
    def test_round_trip_rate(self, rt):
        """Round trips from a task to a doubler task and back, over channels."""
        trips = loop_round_trip_rate(rt, TASKS)

        print(f"\nround trips: {trips:,.0f}/s")
        assert trips > 10_000, f"{trips:,.0f} round trips/s"


class TestThreadCost:
    def test_memory_per_parked_thread_task(self, rt):
        cost = thread_cost(rt, THREADS)

        print(
            f"\nnet cost of a parked thread task ({THREADS:,}): {cost.net:,.0f} B "
            f"each: thread {cost.base:,.0f} B, runtime {cost.runtime:,.0f} B"
        )
        assert cost.runtime <= THREAD_CEILING, f"{cost.runtime:,.0f} B per task"

    def test_spawn_and_cancel_rate(self, rt):
        """spawn() until each runs, then a cancel() of each and a wait() of each."""
        floor = 2_000 * RATE_SHARE
        spawn, cancel = rates_over(floor, lambda: thread_rates(rt, THREADS))

        print(f"\nspawn: {spawn:,.0f}/s  cancel: {cancel:,.0f}/s ({THREADS:,})")
        assert spawn > floor, f"spawn: {spawn:,.0f}/s"
        assert cancel > floor, f"cancel: {cancel:,.0f}/s"

    def test_runtime_spawn_and_stop_rate(self):
        """spawn() into a runtime of its own, then one stop() of it."""
        floor = 2_000 * RATE_SHARE
        spawn, stop = rates_over(floor, lambda: thread_runtime_rates(LG, THREADS))

        print(f"\nruntime spawn: {spawn:,.0f}/s  stop: {stop:,.0f}/s ({THREADS:,})")
        assert spawn > floor, f"spawn: {spawn:,.0f}/s"
        assert stop > floor, f"stop: {stop:,.0f}/s"

    @pytest.mark.skipif(
        sys.platform == "darwin",
        reason="macOS CI runners run this an order of magnitude slower than Linux; "
        "the floor is enforced on Linux only",
    )
    def test_round_trip_rate(self, rt):
        """Round trips from a thread task to a doubler thread task and back."""
        trips = thread_round_trip_rate(rt, TASKS)

        print(f"\nround trips: {trips:,.0f}/s")
        assert trips > 10_000, f"{trips:,.0f} round trips/s"


class TestProcessCost:
    """No floors on rates: a child's start is the interpreter's and the OS's,
    not the runtime's. The measurements run to their end."""

    def test_resident_memory_per_process_task(self, prt):
        rss = process_cost(prt, PROCESSES)

        print(f"\nresident set of a process task's child: {rss / 2**20:,.1f} MiB")
        assert 0 < rss <= PROCESS_CEILING, f"{rss / 2**20:,.1f} MiB per child"

    def test_spawn_and_cancel_rate(self, prt):
        spawn, cancel = process_rates(prt, PROCESSES)

        print(f"\nspawn: {spawn:,.1f}/s  cancel: {cancel:,.1f}/s ({PROCESSES:,})")
        assert spawn > 0 and cancel > 0

    def test_runtime_spawn_and_stop_rate(self, real_lg):
        spawn, stop = process_runtime_rates(real_lg, PROCESSES)

        print(f"\nruntime spawn: {spawn:,.1f}/s  stop: {stop:,.1f}/s ({PROCESSES:,})")
        assert spawn > 0 and stop > 0

    def test_round_trip_rate(self, prt):
        """Round trips from a thread task to a doubler in a child and back."""
        trips = process_round_trip_rate(prt, TASKS)

        print(f"\nround trips: {trips:,.0f}/s")
        assert trips > 0
