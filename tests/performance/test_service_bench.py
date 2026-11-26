# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Service benchmark: the memory an idle async service costs over a plain asyncio task.

Rates, idle CPU and channel round trips are appinfra.runtime's, measured by its own
performance tests; scripts/runtime_bench.py prints them for services too. Run with
``make test.perf.v`` to see the numbers.

By default the benchmark runs 1,000 services, as a regression check that fits
``make check``. ``APPINFRA_SERVICE_BENCH=full`` runs 100,000.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Runtime as Tasks
from appinfra.service import Runtime
from appinfra.service.bench import service_cost

SERVICES = 100_000 if os.environ.get("APPINFRA_SERVICE_BENCH") == "full" else 1_000
# What the framework may add per idle service over a plain asyncio task: the runtime
# task it runs as (bounded at 1 KiB by test_runtime_bench.py), its runner, token and
# names, and its share of the tables holding them. About 1,000 B on Linux, measured
# alone; half again for macOS and the tables other tests in this process have grown
CEILING = 1536
LG = MagicMock()


@pytest.fixture
def tasks() -> Iterator[Tasks]:
    tasks = Tasks(LG)
    tasks.start()
    yield tasks
    tasks.stop(timeout=60.0)


@pytest.fixture
def rt() -> Iterator[Runtime]:
    rt = Runtime(LG)
    rt.start()
    yield rt
    rt.stop(timeout=60.0)


def test_memory_per_idle_service(tasks: Tasks, rt: Runtime) -> None:
    """Only the framework's part of the net cost is bounded: asyncio's part
    varies with the Python version."""
    cost = service_cost(tasks, rt, LG, SERVICES)

    print(
        f"\nnet cost of an idle service on the loop ({SERVICES:,}): "
        f"{cost.net:,.0f} B each: asyncio {cost.asyncio:,.0f} B, "
        f"framework {cost.framework:,.0f} B"
    )
    assert cost.framework <= CEILING, f"{cost.framework:,.0f} B per service"
