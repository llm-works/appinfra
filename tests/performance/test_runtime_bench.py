# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Runtime benchmark: what a task parked on the runtime's event loop costs.

The part of a parked task's memory the runtime adds over a plain asyncio task,
measured with appinfra.runtime.bench; run with ``make test.perf.v`` to see it.

By default the benchmark runs 10,000 tasks, where the warmed measurement comes
out the same on every run; 1,000 still varies by tens of bytes.
``APPINFRA_RUNTIME_BENCH=full`` runs 100,000.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Runtime
from appinfra.runtime.bench import task_cost

TASKS = 100_000 if os.environ.get("APPINFRA_RUNTIME_BENCH") == "full" else 10_000
# What the service layer's own TaskRunner adds per AsyncService over a plain
# asyncio task, state machine, hooks and stop token included, measured the same
# way: a bare task does less and costs no more
CEILING = 740


@pytest.fixture
def rt() -> Iterator[Runtime]:
    rt = Runtime(MagicMock())
    rt.start()
    yield rt
    rt.stop(timeout=60.0)


class TestTaskCost:
    def test_memory_per_parked_task(self, rt):
        cost = task_cost(rt, TASKS)

        print(
            f"\nnet cost of a parked loop task ({TASKS:,}): {cost.net:,.0f} B each: "
            f"asyncio {cost.asyncio:,.0f} B, runtime {cost.runtime:,.0f} B"
        )
        assert cost.runtime <= CEILING, f"{cost.runtime:,.0f} B per task"
