# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Measure what a runtime task costs, for each kind of task: on the event loop
(loop), on a thread of its own, and in a process of its own.

scripts/runtime_bench.py prints these numbers next to appinfra.service.bench's, which
measures services the same way; the performance tests assert on them.
"""

from .loop import (
    loop_cost,
    loop_rates,
    loop_round_trip_rate,
    loop_runtime_rates,
    parked,
)
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
    "loop_cost",
    "loop_rates",
    "loop_round_trip_rate",
    "loop_runtime_rates",
    "parked",
    "process_cost",
    "process_rates",
    "process_round_trip_rate",
    "process_runtime_rates",
    "thread_cost",
    "thread_rates",
    "thread_round_trip_rate",
    "thread_runtime_rates",
]
