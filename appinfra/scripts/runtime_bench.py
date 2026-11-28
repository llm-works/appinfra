#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Print what idle tasks and services cost on this machine and Python version, side by
side: a task of each kind on appinfra.runtime (on the event loop, on a thread of its
own, in a process of its own), and a service under the service layer. For each, the
net memory cost (and for loop tasks, threads and services, the part without appinfra
and appinfra's), the rate they start and stop, alone and by one stop() of a runtime of
their own, and the request/reply rate between two of them over Chans. See
appinfra.runtime.bench and appinfra.service.bench.
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

from appinfra import size_str  # noqa: E402
from appinfra.app import AppBuilder, Tool  # noqa: E402
from appinfra.log import Logger  # noqa: E402
from appinfra.runtime import Runtime  # noqa: E402
from appinfra.runtime.bench import (  # noqa: E402
    process_cost,
    process_rates,
    process_round_trip_rate,
    process_runtime_rates,
    task_cost,
    task_rates,
    thread_cost,
    thread_rates,
    thread_round_trip_rate,
    thread_runtime_rates,
)
from appinfra.runtime.bench import round_trip_rate as task_round_trip_rate  # noqa: E402
from appinfra.runtime.bench import runtime_rates as task_runtime_rates  # noqa: E402
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
    .with_description("What idle tasks of each kind and services cost")
    .logging(level="info")
    .cli(log_level=True, quiet=True)
    .tools.with_main("bench")
    .done()
    .build()
)


@dataclass(frozen=True)
class _Column:
    """The numbers of one column: bytes per item, then rates per second. A
    process has no part without appinfra to tell apart: None, printed as a
    dash."""

    count: int
    net: float
    base: float | None
    appinfra: float | None
    start: float
    stop: float
    rt_spawn: float
    rt_stop: float
    trips: float


# What each row measures, printed under the table
_NOTES = [
    ("net cost", "a process: its child's resident set, shared pages too"),
    ("base", "a plain asyncio task, or a plain thread, parked the same way"),
    ("", "a thread's stack, mapped by the OS, is not counted"),
    ("start", "spawn() of a task or a service, until each runs"),
    ("stop", "cancel() and wait() of a task, stop_service() of a service"),
    ("Runtime spawn", "spawn() into a runtime of its own, until each runs"),
    ("Runtime stop", "one stop() of that runtime"),
    ("request/reply", "round trips over Chans between two tasks, or two services"),
]
# The columns, in the order printed
_HEADS = ["process task", "thread task", "loop task", "service"]


def _positive(value: str) -> int:
    """An argparse type: an integer of at least 1."""
    count = int(value)
    if count < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {count}")
    return count


@app.tool(name="bench", help="Measure idle tasks of each kind and services")
@app.argument(
    "-n",
    "--count",
    type=_positive,
    default=20_000,
    help="loop tasks and services to run, and round trips for every column",
)
@app.argument(
    "-t", "--threads", type=_positive, default=1_000, help="thread tasks to run"
)
@app.argument(
    "-p", "--processes", type=_positive, default=20, help="process tasks to run"
)
def bench(self: Tool) -> int:
    """Run the measurements and print their numbers."""
    count = self.args.count
    # Slowest task kind first, services last
    columns = [
        _measure_processes(self.lg, self.args.processes, count),
        _measure_threads(self.lg, self.args.threads, count),
        _measure_tasks(self.lg, count),
        _measure_services(self.lg, count),
    ]
    self.lg.info("done")
    _report(count, columns)
    return 0


def _measure_tasks(lg: Logger, count: int) -> _Column:
    """A loop task's numbers, over *count* tasks."""
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
        count,
        cost.net,
        cost.base,
        cost.runtime,
        spawn,
        cancel,
        rt_spawn,
        rt_stop,
        trips,
    )


def _measure_threads(lg: Logger, count: int, trips: int) -> _Column:
    """A thread task's numbers, over *count* tasks and *trips* round trips."""
    with Runtime(lg) as rt:
        lg.info("measuring memory per thread task...", extra={"tasks": count})
        cost = thread_cost(rt, count)
        lg.info("measuring thread spawn and cancel...", extra={"tasks": count})
        spawn, cancel = thread_rates(rt, count)
        lg.info("measuring thread round trips...", extra={"round_trips": trips})
        rate = thread_round_trip_rate(rt, trips)
    lg.info("measuring thread runtime spawn and stop...", extra={"tasks": count})
    rt_spawn, rt_stop = thread_runtime_rates(lg, count)
    return _Column(
        count, cost.net, cost.base, cost.runtime, spawn, cancel, rt_spawn, rt_stop, rate
    )


def _measure_processes(lg: Logger, count: int, trips: int) -> _Column:
    """A process task's numbers, over *count* tasks and *trips* round trips."""
    with Runtime(lg) as rt:
        lg.info("measuring memory per process task...", extra={"tasks": count})
        rss = process_cost(rt, count)
        lg.info("measuring process spawn and cancel...", extra={"tasks": count})
        spawn, cancel = process_rates(rt, count)
        lg.info("measuring process round trips...", extra={"round_trips": trips})
        rate = process_round_trip_rate(rt, trips)
    lg.info("measuring process runtime spawn and stop...", extra={"tasks": count})
    rt_spawn, rt_stop = process_runtime_rates(lg, count)
    return _Column(count, rss, None, None, spawn, cancel, rt_spawn, rt_stop, rate)


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
        count,
        cost.net,
        cost.asyncio,
        cost.framework,
        start,
        stop,
        rt_spawn,
        rt_stop,
        trips,
    )


def _cell(value: float | None, unit: str) -> str:
    """A value as printed, or a dash for none. Bytes in binary units; a part
    measured as a difference can come out below zero, which size_str() refuses."""
    if value is None:
        return "—"
    if unit == "B":
        size = round(value)  # A mean per item: a fraction of a byte says nothing
        return f"-{size_str(-size)}" if size < 0 else size_str(size)
    return f"{value:,.0f} {unit}"


def _rows(columns: list[_Column]) -> list[tuple[str, list[str]]]:
    """The table's rows: a label, and the value of each column."""
    rows = [
        ("net cost per item", "net", "B"),
        ("  base", "base", "B"),
        ("  appinfra", "appinfra", "B"),
        ("start", "start", "/s"),
        ("stop", "stop", "/s"),
        ("Runtime spawn", "rt_spawn", "/s"),
        ("Runtime stop", "rt_stop", "/s"),
        ("request/reply", "trips", "/s"),
    ]
    return [
        (label, [_cell(getattr(c, f), unit) for c in columns])
        for label, f, unit in rows
    ]


def _report(trips: int, columns: list[_Column]) -> None:
    """Print the numbers of one run, a column for each task kind and one for
    services."""
    python = f"{platform.python_implementation()} {platform.python_version()}"
    counts = ", ".join(f"{c.count:,} {h}s" for h, c in zip(_HEADS, columns))
    print(f"\nIdle {counts}; {trips:,} round trips each; {python}\n")
    print(f"  {'':<20}" + "".join(f"{h:>15}" for h in _HEADS))
    for label, cells in _rows(columns):
        print(f"  {label:<20}" + "".join(f"{cell:>15}" for cell in cells))
    print()
    for label, note in _NOTES:
        print(f"  {label:<16}{note}")


if __name__ == "__main__":
    sys.exit(app.main())
