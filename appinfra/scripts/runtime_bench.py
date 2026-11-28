#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Print what idle tasks and services on one event loop cost on this machine and Python
version, side by side: a bare task on appinfra.runtime, and a service under the service
layer. For each, the net memory cost (asyncio's part and appinfra's) and the rate they
start and stop; for services also the spawn() and stop() rate of a service Runtime and
the request/reply rate between two services, each request with its reply Chan. See
appinfra.runtime.bench and
appinfra.service.bench.
"""

from __future__ import annotations

import argparse
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow running from a source checkout without installing the package.
# Walk upward from the script to find the directory containing appinfra/.
_script_dir = Path(__file__).resolve().parent
for _ancestor in (_script_dir, *_script_dir.parents):
    if (_ancestor / "appinfra").is_dir():
        sys.path.insert(0, str(_ancestor))
        break

from appinfra.app import AppBuilder, Tool  # noqa: E402
from appinfra.log import Logger  # noqa: E402
from appinfra.runtime import Runtime  # noqa: E402
from appinfra.runtime.bench import round_trip_rate as task_round_trip_rate  # noqa: E402
from appinfra.runtime.bench import runtime_rates as task_runtime_rates  # noqa: E402
from appinfra.runtime.bench import task_cost, task_rates  # noqa: E402
from appinfra.service import Runtime as ServiceRuntime  # noqa: E402
from appinfra.service.bench import (  # noqa: E402
    parked_maker,
    round_trip_rate,
    runtime_rates,
    service_cost,
    spawn_services,
    stop_services,
)

app = (
    AppBuilder("runtime_bench")
    .with_description("What idle tasks and services on one event loop cost")
    .logging(level="info")
    .cli(log_level=True, quiet=True)
    .tools.with_main("bench")
    .done()
    .build()
)


@dataclass(frozen=True)
class _Column:
    """The numbers of one column: bytes per item, then rates per second."""

    net: float
    asyncio: float
    appinfra: float
    start: float
    stop: float
    rt_spawn: float
    rt_stop: float
    trips: float


# What each rate row times, printed under the table
_NOTES = [
    ("start", "spawn() of a task or a service, until each runs"),
    ("stop", "cancel() and wait() of a task, stop_service() of a service"),
    ("Runtime spawn", "spawn() into a runtime of its own, until each runs"),
    ("Runtime stop", "one stop() of that runtime"),
    ("request/reply", "round trips over Chans between two tasks, or two services"),
]


def _positive(value: str) -> int:
    """An argparse type: an integer of at least 1."""
    count = int(value)
    if count < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {count}")
    return count


@app.tool(name="bench", help="Measure idle tasks and services on one event loop")
@app.argument(
    "-n", "--count", type=_positive, default=20_000, help="tasks and services to run"
)
def bench(self: Tool) -> int:
    """Run the measurements and print their numbers."""
    count = self.args.count
    tasks = _measure_tasks(self.lg, count)
    services = _measure_services(self.lg, count)
    self.lg.info("done")
    _report(count, tasks, services)
    return 0


def _measure_tasks(lg: Logger, count: int) -> _Column:
    """A bare task's numbers, over *count* tasks."""
    with Runtime(lg) as rt:
        lg.info("measuring memory per task...", extra={"tasks": count})
        cost = task_cost(rt, count)
        lg.info("measuring task spawn and cancel...", extra={"tasks": count})
        spawn, cancel = task_rates(rt, count)
        lg.info("measuring channel round trips...", extra={"round_trips": count})
        trips = task_round_trip_rate(rt, count)
    lg.info("measuring runtime spawn and stop...", extra={"tasks": count})
    rt_spawn, rt_stop = task_runtime_rates(lg, count)
    return _Column(
        cost.net, cost.asyncio, cost.runtime, spawn, cancel, rt_spawn, rt_stop, trips
    )


def _measure_services(lg: Logger, count: int) -> _Column:
    """A service's numbers, over *count* services, run on a service runtime's loop."""
    with Runtime(lg) as tasks, ServiceRuntime(lg) as rt:
        lg.info("measuring memory per service...", extra={"services": count})
        cost = service_cost(tasks, rt, lg, count)
        lg.info("measuring spawn and stop_service...", extra={"services": count})
        runners, start = spawn_services(rt, parked_maker(lg), count)
        stop = stop_services(rt, runners)
    lg.info("measuring request/reply rate...", extra={"round_trips": count})
    trips = round_trip_rate(lg, count)
    lg.info("measuring service runtime spawn and stop...", extra={"services": count})
    rt_spawn, rt_stop = runtime_rates(lg, parked_maker(lg), count)
    return _Column(
        cost.net, cost.asyncio, cost.framework, start, stop, rt_spawn, rt_stop, trips
    )


def _rows(tasks: _Column, services: _Column) -> list[tuple[str, str, str]]:
    """The table's rows: a label, the task's value, the service's."""
    rows = [
        ("net cost per item", "net", "B"),
        ("  asyncio", "asyncio", "B"),
        ("  appinfra", "appinfra", "B"),
        ("start", "start", "/s"),
        ("stop", "stop", "/s"),
        ("Runtime spawn", "rt_spawn", "/s"),
        ("Runtime stop", "rt_stop", "/s"),
        ("request/reply", "trips", "/s"),
    ]
    return [
        (
            label,
            f"{getattr(tasks, f):,.0f} {unit}",
            f"{getattr(services, f):,.0f} {unit}",
        )
        for label, f, unit in rows
    ]


def _report(count: int, tasks: _Column, services: _Column) -> None:
    """Print the numbers of one run, a column for tasks and one for services."""
    python = f"{platform.python_implementation()} {platform.python_version()}"
    print(f"\n{count:,} idle tasks and services on one event loop, {python}\n")
    print(f"  {'':<20}{'runtime.Task':>14}{'service':>14}")
    for label, task, service in _rows(tasks, services):
        print(f"  {label:<20}{task:>14}{service:>14}")
    print()
    for label, note in _NOTES:
        print(f"  {label:<16}{note}")


if __name__ == "__main__":
    sys.exit(app.main())
