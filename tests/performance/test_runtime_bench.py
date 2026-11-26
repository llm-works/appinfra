# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Runtime benchmark: what tasks on the runtime's event loop cost.

The part of a parked task's memory the runtime adds over a plain asyncio task, the
rate tasks spawn and end, alone and by a runtime's stop(), idle CPU, and round trips
over channels, measured with appinfra.runtime.bench; run with ``make test.perf.v``
to see the numbers.

By default the benchmark runs 10,000 tasks, where the warmed memory measurement
comes out the same on every run; 1,000 still varies by tens of bytes.
``APPINFRA_RUNTIME_BENCH=full`` runs 100,000.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Runtime
from appinfra.runtime.bench import (
    parked,
    round_trip_rate,
    runtime_rates,
    task_cost,
    task_rates,
)

TASKS = 100_000 if os.environ.get("APPINFRA_RUNTIME_BENCH") == "full" else 10_000
# What the runtime may add per parked task over a plain asyncio task: its task,
# the handle, the child token, the context the call runs in. 1 KiB, as for a
# service: macOS measures more than Linux
CEILING = 1024
# Seconds of wall time over which idle CPU is measured: long enough to catch two
# wakeups of a receive that polled every 0.1 s
IDLE_WINDOW = 0.2
# Share of the rate floors enforced on macOS: its CI runners measure spawn and stop
# rates just under the Linux floor; the full floor applies on Linux
RATE_SHARE = 0.5 if sys.platform == "darwin" else 1.0
LG = MagicMock()


@pytest.fixture
def rt() -> Iterator[Runtime]:
    rt = Runtime(LG)
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
        cost = task_cost(rt, TASKS)

        print(
            f"\nnet cost of a parked loop task ({TASKS:,}): {cost.net:,.0f} B each: "
            f"asyncio {cost.asyncio:,.0f} B, runtime {cost.runtime:,.0f} B"
        )
        assert cost.runtime <= CEILING, f"{cost.runtime:,.0f} B per task"

    def test_spawn_and_cancel_rate(self, rt):
        """spawn() until each runs, then cancel() and wait() one at a time."""
        spawn, cancel = task_rates(rt, TASKS)

        print(f"\nspawn: {spawn:,.0f}/s  cancel: {cancel:,.0f}/s ({TASKS:,})")
        assert spawn > 5_000 * RATE_SHARE, f"spawn: {spawn:,.0f}/s"
        assert cancel > 5_000 * RATE_SHARE, f"cancel: {cancel:,.0f}/s"

    def test_runtime_spawn_and_stop_rate(self):
        """spawn() into a runtime of its own, then one stop() of it."""
        spawn, stop = runtime_rates(LG, TASKS)

        print(f"\nruntime spawn: {spawn:,.0f}/s  stop: {stop:,.0f}/s ({TASKS:,})")
        assert spawn > 5_000 * RATE_SHARE, f"spawn: {spawn:,.0f}/s"
        assert stop > 5_000 * RATE_SHARE, f"stop: {stop:,.0f}/s"

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
        trips = round_trip_rate(rt, TASKS)

        print(f"\nround trips: {trips:,.0f}/s")
        assert trips > 10_000, f"{trips:,.0f} round trips/s"
