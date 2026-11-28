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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Allow running from a source checkout without installing the package.
# Walk upward from the script to find the directory containing appinfra/.
_script_dir = Path(__file__).resolve().parent
for _ancestor in (_script_dir, *_script_dir.parents):
    if (_ancestor / "appinfra").is_dir():
        sys.path.insert(0, str(_ancestor))
        break

from appinfra import size_str  # noqa: E402
from appinfra.app import App, AppBuilder  # noqa: E402
from appinfra.log import Logger  # noqa: E402
from appinfra.runtime import Chan, Runtime, TaskDone, this_task  # noqa: E402
from appinfra.runtime.bench import (  # noqa: E402
    loop_cost,
    loop_rates,
    loop_round_trip_rate,
    loop_runtime_rates,
    process_cost,
    process_rates,
    process_round_trip_rate,
    process_runtime_rates,
    thread_cost,
    thread_rates,
    thread_round_trip_rate,
    thread_runtime_rates,
)
from appinfra.service import Runtime as ServiceRuntime  # noqa: E402
from appinfra.service.bench import (  # noqa: E402
    parked_maker,
    round_trip_rate,
    runtime_rates,
    service_cost,
    spawn_services,
    stop_services,
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
    ("net cost", "a process: what its child alone holds (Linux), or its resident"),
    ("", "set, shared pages too; the fork server is paid once, not per task"),
    ("base", "a plain asyncio task, or a plain thread, parked the same way"),
    ("", "a thread's stack, mapped by the OS, is not counted"),
    ("start", "spawn() of a task or a service, until each runs"),
    ("stop", "cancel() of each task, then wait(); stop_service() of a service"),
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


class Bench(App):
    """The benchmark, as the app's one command: it has no tools, so it takes
    no subcommand."""

    def add_args(self) -> None:
        """The standard arguments, and how many items to measure."""
        super().add_args()
        self.parser.add_argument(
            "-n",
            "--count",
            type=_positive,
            default=20_000,
            help="loop tasks and services to run, and round trips for every column",
        )
        self.parser.add_argument(
            "-t", "--threads", type=_positive, default=1_000, help="thread tasks to run"
        )
        self.parser.add_argument(
            "-p", "--processes", type=_positive, default=20, help="process tasks to run"
        )
        self.parser.add_argument(
            "-c",
            "--cores",
            type=_positive,
            default=1,
            help="measurements to run at once, each in a process of its own: "
            "faster, but ones sharing the machine read lower rates",
        )

    def run_no_tool(self) -> int:
        """Run the measurements, each a process task of its own and at most
        --cores at once, and print their numbers."""
        a = self.args
        sizes = {"process": (a.processes, a.count), "thread": (a.threads, a.count)}
        sizes |= {"loop": (a.count, a.count), "service": (a.count, a.count)}
        jobs = [(name, *sizes[name.split()[0]]) for name in _JOBS]
        results = _run_jobs(self.lg, jobs, a.cores)
        if results is None:
            return 1
        self.lg.info("done")
        columns = [_column(head, sizes, results) for head in _KINDS]
        _report(a.count, columns)
        return 0


# A measurement's fields of its column, by name
JobResult = dict[str, float | None]
# A measurement: from a logger, the number of items and the number of round trips
Job = Callable[[Logger, int, int], JobResult]


def _on_runtime(lg: Logger, measure: Callable[[Runtime, int], Any], n: int) -> Any:
    """*measure*(runtime, *n*), on a runtime of its own."""
    with Runtime(lg) as rt:
        return measure(rt, n)


def _pair(first: str, second: str, values: tuple[float, float]) -> JobResult:
    """Two rates, as the fields *first* and *second*."""
    return {first: values[0], second: values[1]}


def _task_memory(
    lg: Logger, cost_of: Callable[[Runtime, int], Any], n: int
) -> JobResult:
    """Memory per loop or thread task: net, and its part without appinfra and
    appinfra's."""
    cost = _on_runtime(lg, cost_of, n)
    return {"net": cost.net, "base": cost.base, "appinfra": cost.runtime}


def _process_memory(lg: Logger, n: int, trips: int) -> JobResult:
    """Memory per process task: what each more one costs, its child's private
    memory where the OS tells it apart (Linux), else its resident set."""
    cost = _on_runtime(lg, process_cost, n)
    return {"net": cost.resident if cost.private is None else cost.private}


def _service_memory(lg: Logger, n: int, trips: int) -> JobResult:
    """Memory per service, run on a service runtime's loop."""
    with Runtime(lg) as tasks, ServiceRuntime(lg) as rt:
        cost = service_cost(tasks, rt, lg, n)
    return {"net": cost.net, "base": cost.asyncio, "appinfra": cost.framework}


def _service_rates(lg: Logger, n: int, trips: int) -> JobResult:
    """Services spawned and stopped per second, by spawn() and stop_service()."""
    with ServiceRuntime(lg) as rt:
        runners, start = spawn_services(rt, parked_maker(lg), n)
        stop = stop_services(rt, runners)
    return {"start": start, "stop": stop}


# The measurements by name, the longest first, so the short ones fill in
# around them instead of the long ones starting last
_JOBS: dict[str, Job] = {
    "process runtime": lambda lg, n, _: _pair(
        "rt_spawn", "rt_stop", process_runtime_rates(lg, n)
    ),
    "process rates": lambda lg, n, _: _pair(
        "start", "stop", _on_runtime(lg, process_rates, n)
    ),
    "service runtime": lambda lg, n, _: _pair(
        "rt_spawn", "rt_stop", runtime_rates(lg, parked_maker(lg), n)
    ),
    "service rates": _service_rates,
    "service memory": _service_memory,
    "loop runtime": lambda lg, n, _: _pair(
        "rt_spawn", "rt_stop", loop_runtime_rates(lg, n)
    ),
    "process memory": _process_memory,
    "thread runtime": lambda lg, n, _: _pair(
        "rt_spawn", "rt_stop", thread_runtime_rates(lg, n)
    ),
    "thread rates": lambda lg, n, _: _pair(
        "start", "stop", _on_runtime(lg, thread_rates, n)
    ),
    "loop rates": lambda lg, n, _: _pair(
        "start", "stop", _on_runtime(lg, loop_rates, n)
    ),
    "loop memory": lambda lg, n, _: _task_memory(lg, loop_cost, n),
    "thread memory": lambda lg, n, _: _task_memory(lg, thread_cost, n),
    "service trips": lambda lg, _, t: {"trips": round_trip_rate(lg, t)},
    "process trips": lambda lg, _, t: {
        "trips": _on_runtime(lg, process_round_trip_rate, t)
    },
    "thread trips": lambda lg, _, t: {
        "trips": _on_runtime(lg, thread_round_trip_rate, t)
    },
    "loop trips": lambda lg, _, t: {"trips": _on_runtime(lg, loop_round_trip_rate, t)},
}
# The kinds, by column, in the order printed
_KINDS = ["process", "thread", "loop", "service"]


def _job(name: str, count: int, trips: int) -> JobResult:
    """In a process task's child: run the measurement *name*, logging through
    the task's logger, whose records the bench's handlers emit."""
    lg = this_task().lg
    if name.startswith("process"):
        # The fork server starts with this process's first process task: a
        # cost paid once, not by every task, so not in what is measured
        with Runtime(lg) as rt:
            rt.spawn(int, process=True).wait(timeout=120.0)
    lg.info(f"measuring {name}...", extra={"items": count, "round_trips": trips})
    return _JOBS[name](lg, count, trips)


def _run_jobs(
    lg: Logger, jobs: list[tuple[str, int, int]], cores: int
) -> dict[str, JobResult] | None:
    """Run each of *jobs* as a process task, at most *cores* at once, and
    return their results by name; None, logged, if one failed."""
    results: dict[str, JobResult] = {}
    pending = list(jobs)
    ends: Chan[TaskDone] = Chan(None)
    with Runtime(lg) as rt:
        for _ in range(min(cores, len(pending))):
            _spawn_job(rt, pending.pop(0), ends)
        while len(results) < len(jobs):
            end = ends.recv()
            if end.error is not None:
                lg.error(
                    "measurement failed",
                    extra={"job": end.name, "exception": end.error},
                )
                return None
            results[str(end.name)] = end.result
            if pending:
                _spawn_job(rt, pending.pop(0), ends)
    return results


def _spawn_job(rt: Runtime, job: tuple[str, int, int], ends: Chan[TaskDone]) -> None:
    """Spawn *job* on *rt* as a process task, its end sent on *ends*; it
    logs under a logger named after it."""
    name, count, trips = job
    rt.spawn(
        _job,
        name,
        count,
        trips,
        name=name,
        done=ends,
        process=True,
        derive_lg=name.replace(" ", "-"),
    )


def _column(
    kind: str, sizes: dict[str, tuple[int, int]], results: dict[str, JobResult]
) -> _Column:
    """The column of *kind*, from its measurements' results."""
    fields: JobResult = {"base": None, "appinfra": None}
    for name, result in results.items():
        if name.split()[0] == kind:
            fields |= result
    return _Column(count=sizes[kind][0], **fields)  # type: ignore[arg-type]


def _cell(value: float | None, unit: str) -> str:
    """A value as printed, or a dash for none. Bytes in binary units; a part
    measured as a difference can come out below zero, which size_str() refuses."""
    if value is None:
        return "—"
    if unit == "B":
        size = round(value)  # A mean per item: a fraction of a byte says nothing
        shown = size_str(abs(size), precise=True)
        return f"-{shown}" if size < 0 else shown
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


app = (
    AppBuilder("runtime_bench")
    .with_main_cls(Bench)
    .with_description("What idle tasks of each kind and services cost")
    .logging(level="info")
    .cli(log_level=True, quiet=True)
    .build()
)


if __name__ == "__main__":
    sys.exit(app.main())
