#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Print what services on a LoopHost cost on this machine and Python version: the net
memory cost of an idle service (asyncio's part and appinfra's), start and stop rate,
and the submit/reply rate through an async channel. See appinfra.service.bench.
"""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
# Walk upward from the script to find the directory containing appinfra/.
_script_dir = Path(__file__).resolve().parent
for _ancestor in (_script_dir, *_script_dir.parents):
    if (_ancestor / "appinfra").is_dir():
        sys.path.insert(0, str(_ancestor))
        break

from appinfra.app import AppBuilder, Tool  # noqa: E402
from appinfra.service import LoopHost  # noqa: E402
from appinfra.service.bench import (  # noqa: E402
    Cost,
    minimal_maker,
    round_trip_rate,
    service_cost,
    start_runners,
    stop_runners,
)

app = (
    AppBuilder("service_bench")
    .with_description("What services on a LoopHost cost")
    .logging(level="info")
    .cli(log_level=True, quiet=True)
    .tools.with_main("bench")
    .done()
    .build()
)


def _positive(value: str) -> int:
    """An argparse type: an integer of at least 1."""
    count = int(value)
    if count < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {count}")
    return count


@app.tool(name="bench", help="Measure services on one LoopHost")
@app.argument(
    "-s", "--services", type=_positive, default=100_000, help="services to run"
)
def bench(self: Tool) -> int:
    """Run the measurements and print their numbers."""
    count = self.args.services
    with LoopHost(name="bench") as host:
        self.lg.info("measuring memory per service...", extra={"services": count})
        cost = service_cost(host, self.lg, count)
        self.lg.info("measuring start and stop rate...", extra={"services": count})
        runners, start = start_runners(host, minimal_maker(self.lg), count)
        stop = stop_runners(runners)
        self.lg.info("measuring submit/reply rate...", extra={"round_trips": count})
        trips = round_trip_rate(host, self.lg, count)
    self.lg.info("done")
    _report(count, cost, start, stop, trips)
    return 0


def _report(count: int, cost: Cost, start: float, stop: float, trips: float) -> None:
    """Print the numbers of one run."""
    python = f"{platform.python_implementation()} {platform.python_version()}"
    print(f"\n{count:,} idle services on one LoopHost, {python}\n")
    print(f"  net cost per service  {cost.net:>9,.0f} B")
    print(f"    asyncio             {cost.asyncio:>9,.0f} B")
    print(f"    appinfra            {cost.framework:>9,.0f} B")
    print(f"  start                 {start:>9,.0f} /s")
    print(f"  stop                  {stop:>9,.0f} /s")
    print(f"  submit/reply          {trips:>9,.0f} round trips/s")


if __name__ == "__main__":
    sys.exit(app.main())
