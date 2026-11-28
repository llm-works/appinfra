#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tasks: concurrency patterns for the lifecycle of tasks.

Each example is one pattern, from spawning and joining one task to a
supervisor that watches a worker's heartbeat; main() runs them in order.
"""

import asyncio
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.log import LogConfig, Logger, LoggerFactory
from appinfra.runtime import (
    Chan,
    ChanRecv,
    Runtime,
    StoppedError,
    StopToken,
    Task,
    TaskDone,
    select,
    this_task,
)


def checksum(data: bytes) -> int:
    """A plain function: a task on a thread of its own."""
    return sum(data) % 65521


async def fetch(url: str) -> str:
    """An async function, a task on the runtime's loop: a stand-in for an
    HTTP fetch."""
    await asyncio.sleep(0.01)
    return f"<html>{url}</html>"


def nap(seconds: float) -> float:
    """Sleep *seconds*, then return them."""
    time.sleep(seconds)
    return seconds


def spawn_and_join(lg: Logger, rt: Runtime) -> None:
    """Spawn and join: start a task, then wait for its result."""
    t = rt.spawn(checksum, b"appinfra")
    lg.info("joined", extra={"result": t.wait(timeout=5.0)})


def wait_for_all(lg: Logger, rt: Runtime) -> None:
    """Wait for all: start several tasks, then wait for each. Here a
    coroutine does it, with await."""

    async def fetch_all(urls: list[str]) -> list[int]:
        """Start a fetch per URL, then await each in turn."""
        pages = [rt.spawn(fetch, url) for url in urls]
        return [len(await page) for page in pages]

    urls = ["https://a.example", "https://b.example", "https://c.example"]
    sizes = rt.spawn(fetch_all, urls).wait(timeout=5.0)
    lg.info("all fetched", extra={"sizes": sizes})


def done_channel(lg: Logger, rt: Runtime) -> None:
    """Done channel: every task reports its end on one channel, in the order
    the tasks end, not the order they started."""
    done = Chan[TaskDone](3)
    for seconds in (0.03, 0.01, 0.02):
        rt.spawn(nap, seconds, name=f"nap-{seconds}", done=done)
    for _ in range(3):
        end = done.recv(timeout=5.0)
        lg.info("ended", extra={"task": end.name, "result": end.result})


def error_group(lg: Logger, rt: Runtime) -> None:
    """Error group: run tasks under one token; the first error stops the rest."""
    hosts = ["api.local", "db.local", "cache.local"]
    group, done = StopToken(), Chan[TaskDone](len(hosts))

    def check(host: str) -> str:
        """Fail at once for the database, else run until stopped."""
        if host == "db.local":
            raise ConnectionError(f"{host}: connection refused")
        this_task().token.wait(timeout=5.0)
        return host

    for host in hosts:
        rt.spawn(check, host, name=host, token=group, done=done)
    first_error = None
    for _ in hosts:
        end = done.recv(timeout=5.0)
        if end.error is not None and first_error is None:
            first_error = end.error
            group.stop()  # the others see their tokens stop and return
        lg.info("ended", extra={"task": end.name, "failed": end.error is not None})
    lg.warning("group failed (expected)", extra={"error": str(first_error)})


def cancellation_tree(lg: Logger, rt: Runtime) -> None:
    """Cancellation tree: the tasks a task spawns derive from its token, so
    cancelling it stops them all."""
    spawned = threading.Event()

    def child() -> None:
        """Run until stopped."""
        this_task().token.wait()

    def parent() -> list[Task]:
        """Spawn three children, then run until stopped."""
        children = [rt.spawn(child) for _ in range(3)]
        spawned.set()
        this_task().token.wait()
        return children

    p = rt.spawn(parent)
    spawned.wait(5.0)  # cancelled before it started, its call would be skipped
    p.cancel()
    children = p.wait(timeout=5.0)
    for c in children:
        try:
            c.wait(timeout=5.0)
        except StoppedError:
            pass  # cancelled before it started: no result
    lg.info("children stopped with it", extra={"alive": [c.alive() for c in children]})


def deadline(lg: Logger, rt: Runtime) -> None:
    """Deadline: a timer task stops the work's token when time runs out; the
    work returns what it got done."""
    budget = StopToken()

    async def timer(seconds: float, token: StopToken) -> None:
        """Stop *token* after *seconds*."""
        await asyncio.sleep(seconds)
        token.stop()

    def crawl() -> int:
        """Count pages until the budget's token stops."""
        pages = 0
        while not this_task().token.wait(timeout=0.01):
            pages += 1
        return pages

    work = rt.spawn(crawl, token=budget)
    rt.spawn(timer, 0.1, budget)
    lg.info("deadline reached", extra={"pages": work.wait(timeout=5.0)})


def for_select_loop(lg: Logger, rt: Runtime) -> None:
    """For-select loop: a worker waits on its jobs and on a quit channel at
    once, and returns on quit."""
    jobs, quit = Chan[int](0), Chan[None](0)

    def worker() -> int:
        """Handle jobs until quit; return how many."""
        handled = 0
        while True:
            case, _ = select(ChanRecv(jobs), ChanRecv(quit))
            if case == 1:
                return handled
            handled += 1

    w = rt.spawn(worker)
    for job in range(5):
        jobs.send(job, timeout=5.0)
    quit.send(None, timeout=5.0)
    lg.info("worker quit", extra={"handled": w.wait(timeout=5.0)})


def heartbeat(lg: Logger, rt: Runtime) -> None:
    """Heartbeat: a worker reports progress while it works; the supervisor
    selects over heartbeats, the result and a timeout, and so tells a slow
    worker from a stuck one."""
    beats, results = Chan[int](1), Chan[int](1)

    def work(steps: int) -> None:
        """Do *steps* steps, beating after each; a beat nobody took is dropped."""
        total = 0
        for step in range(steps):
            time.sleep(0.01)
            total += step
            try:
                beats.send(step, timeout=0)
            except TimeoutError:
                pass
        results.send(total)

    rt.spawn(work, 5)
    heard = 0
    while True:
        try:
            case, value = select(ChanRecv(beats), ChanRecv(results), timeout=1.0)
        except TimeoutError:
            lg.warning("worker stuck: no heartbeat")
            return
        if case == 0:
            heard += 1
            continue
        lg.info("worker done", extra={"total": value, "heartbeats": heard})
        return


EXAMPLES: list[Callable[[Logger, Runtime], None]] = [
    spawn_and_join,
    wait_for_all,
    done_channel,
    error_group,
    cancellation_tree,
    deadline,
    for_select_loop,
    heartbeat,
]


def main() -> int:
    """Run every example in order, on one runtime."""
    lg = LoggerFactory.create_root(LogConfig.from_params(level="info"))
    with Runtime(lg) as rt:
        for n, example in enumerate(EXAMPLES, 1):
            lg.info("example", extra={"n": n, "example": example.__name__})
            example(lg, rt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
