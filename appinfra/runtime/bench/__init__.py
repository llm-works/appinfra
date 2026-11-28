# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Measure what a runtime task costs, for each kind of task: on the event loop
(loop), on a thread of its own, and in a process of its own.

scripts/runtime_bench.py prints these numbers next to appinfra.service.bench's, which
measures services the same way; the performance tests assert on them.
"""

from .loop import parked, round_trip_rate, runtime_rates, task_cost, task_rates
from .measure import (
    Arrivals,
    TaskCost,
    ThreadArrivals,
    bytes_per,
    bytes_per_warmed,
    cancel_all,
    check_count,
)
from .process import (
    process_cost,
    process_rates,
    process_round_trip_rate,
    process_runtime_rates,
)
from .thread import (
    thread_cost,
    thread_rates,
    thread_round_trip_rate,
    thread_runtime_rates,
)

__all__ = [
    "Arrivals",
    "TaskCost",
    "ThreadArrivals",
    "bytes_per",
    "bytes_per_warmed",
    "cancel_all",
    "check_count",
    "parked",
    "process_cost",
    "process_rates",
    "process_round_trip_rate",
    "process_runtime_rates",
    "round_trip_rate",
    "runtime_rates",
    "task_cost",
    "task_rates",
    "thread_cost",
    "thread_rates",
    "thread_round_trip_rate",
    "thread_runtime_rates",
]
