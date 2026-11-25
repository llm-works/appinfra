#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Channels: concurrency patterns built on Chan and select.

Each example is one pattern, from a hand-over between two tasks to rate
limiting; main() runs them in order.
"""

import asyncio
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.log import LogConfig, Logger, LoggerFactory
from appinfra.runtime import (
    Chan,
    ChanClosedError,
    ChanRecv,
    ChanSend,
    Runtime,
    select,
)


def merge(*inputs: Chan[int]) -> Iterator[int]:
    """Yield from every input until each one is closed: a closed input's case
    raises ChanClosedError, which names it, and is dropped."""
    cases = [ChanRecv(ch) for ch in inputs]
    while cases:
        try:
            _, value = select(*cases, timeout=5.0)
        except ChanClosedError as e:
            assert e.index is not None
            del cases[e.index]
            continue
        yield value


def ping_pong(lg: Logger, rt: Runtime) -> None:
    """Unbuffered hand-over: two sides pass a value back and forth; each send
    waits until the other side receives."""
    ping, pong = Chan[int](0), Chan[int](0)

    def player(rounds: int) -> None:
        """Receive the ball, return it one higher."""
        for _ in range(rounds):
            pong.send(ping.recv() + 1)

    rt.spawn(player, 3)
    ball = 0
    for _ in range(3):
        ping.send(ball, timeout=5.0)
        ball = pong.recv(timeout=5.0)
    lg.info("rallies done", extra={"ball": ball})


def queue(lg: Logger, rt: Runtime) -> None:
    """Buffered channel as a queue: a send returns while there is room; values
    come out in the order sent."""
    q = Chan[str](3)
    for item in ("a", "b", "c"):
        q.send(item)
    lg.info("dequeued", extra={"items": [q.recv(), q.recv(), q.recv()]})


def generator(lg: Logger, rt: Runtime) -> None:
    """Generator: a task produces values on a channel and closes it; the
    caller ranges over it."""

    def fibonacci(out: Chan[int], n: int) -> None:
        """Send the first *n* Fibonacci numbers, then close."""
        a, b = 0, 1
        for _ in range(n):
            out.send(a)
            a, b = b, a + b
        out.close()

    numbers = Chan[int](0)
    rt.spawn(fibonacci, numbers, 10)
    lg.info("generated", extra={"values": list(numbers)})


def pipeline(lg: Logger, rt: Runtime) -> None:
    """Pipeline: stages joined by channels; each stage closes its output when
    its input ends. Stages can be thread tasks or loop tasks alike."""

    def numbers(out: Chan[int]) -> None:
        """First stage: send 1..5, then close."""
        for i in range(1, 6):
            out.send(i)
        out.close()

    async def squares(inp: Chan[int], out: Chan[int]) -> None:
        """Second stage: square each value."""
        async for n in inp:
            await out.asend(n * n)
        out.close()

    raw, squared = Chan[int](0), Chan[int](0)
    rt.spawn(numbers, raw)
    rt.spawn(squares, raw, squared)
    lg.info("sum of squares", extra={"total": sum(squared)})


def fan_out_fan_in(lg: Logger, rt: Runtime) -> None:
    """Fan-out, fan-in: several workers read one input; their outputs merge
    into one stream with select."""
    jobs = Chan[int](0)

    def produce() -> None:
        """Send the jobs, then close."""
        for job in range(10):
            jobs.send(job)
        jobs.close()

    def square(out: Chan[int]) -> None:
        """Read jobs until they end; close this worker's output."""
        for job in jobs:
            out.send(job * job)
        out.close()

    outputs = [Chan[int](0) for _ in range(3)]
    rt.spawn(produce)
    for out in outputs:
        rt.spawn(square, out)
    lg.info("merged", extra={"results": sorted(merge(*outputs))})


def worker_pool(lg: Logger, rt: Runtime) -> None:
    """Worker pool: a fixed number of workers share a jobs channel; results
    come back on another, closed once every worker is done."""
    jobs, results = Chan[int](0), Chan[int](10)

    def worker() -> None:
        """Take jobs until the channel is closed; send each result back."""
        for job in jobs:
            results.send(job * 10)

    pool = [rt.spawn(worker, name=f"worker-{i}") for i in range(3)]
    for job in range(10):
        jobs.send(job)
    jobs.close()
    for w in pool:
        w.wait(timeout=5.0)
    results.close()
    lg.info("pool done", extra={"results": sorted(results)})


def semaphore(lg: Logger, rt: Runtime) -> None:
    """Semaphore: a buffered channel of slots bounds how many tasks run a
    section at once; a send takes a slot, a receive gives it back."""
    slots = Chan[None](2)
    lock, running, peak = threading.Lock(), [0], [0]

    def job() -> None:
        """Hold a slot while working."""
        slots.send(None)  # waits while both slots are taken
        try:
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            time.sleep(0.01)
            with lock:
                running[0] -= 1
        finally:
            slots.recv()

    for t in [rt.spawn(job) for _ in range(6)]:
        t.wait(timeout=5.0)
    lg.info("six jobs done", extra={"most_at_once": peak[0]})


def timeout(lg: Logger, rt: Runtime) -> None:
    """Timeout: wait for a reply, but only so long."""
    replies = Chan[str](1)

    async def slow_service() -> None:
        """Reply after a second."""
        await asyncio.sleep(1.0)
        await replies.asend("late reply")

    service = rt.spawn(slow_service)
    try:
        select(ChanRecv(replies), timeout=0.1)
    except TimeoutError:
        lg.info("no reply in time")
    service.cancel()


def non_blocking(lg: Logger, rt: Runtime) -> None:
    """Non-blocking send and receive: timeout=0 completes at once, or not at
    all."""
    events, dropped = Chan[str](2), 0
    for i in range(5):
        try:
            select(ChanSend(events, f"event-{i}"), timeout=0)
        except TimeoutError:
            dropped += 1  # full: dropped, not waited for
    kept = []
    while True:
        try:
            kept.append(events.recv(timeout=0))
        except TimeoutError:
            break  # empty
    lg.info("buffered", extra={"kept": kept, "dropped": dropped})


def or_done(lg: Logger, rt: Runtime) -> None:
    """Or-done: read a stream until it ends or a quit channel closes, whichever
    comes first. Closing a channel is a signal every waiter sees."""
    stream, quit = Chan[int](0), Chan[None](0)

    def endless(out: Chan[int]) -> None:
        """Send 0, 1, 2, ... until the task is cancelled."""
        i = 0
        while True:
            out.send(i)
            i += 1

    def read(source: Chan[int]) -> Iterator[int]:
        """Values of *source* until it ends or quit is closed."""
        while True:
            try:
                _, value = select(ChanRecv(quit), ChanRecv(source), timeout=5.0)
            except ChanClosedError:
                return
            yield value

    producer = rt.spawn(endless, stream)
    received = []
    for value in read(stream):
        received.append(value)
        if len(received) == 5:
            quit.close()  # a value already in flight may still arrive
    producer.cancel()
    lg.info("quit", extra={"received": len(received)})


def rate_limit(lg: Logger, rt: Runtime) -> None:
    """Rate limiting: a ticker task puts a tick on a channel at a fixed
    interval, and each request waits for a tick."""
    ticks = Chan[None](0)

    async def ticker(interval: float) -> None:
        """Tick every *interval* seconds until cancelled."""
        while True:
            await asyncio.sleep(interval)
            await ticks.asend(None)

    clock = rt.spawn(ticker, 0.02)
    start = time.monotonic()
    for _ in range(5):
        ticks.recv(timeout=5.0)  # one request per tick
    elapsed = time.monotonic() - start
    clock.cancel()
    lg.info("five requests", extra={"seconds": round(elapsed, 2)})


EXAMPLES: list[Callable[[Logger, Runtime], None]] = [
    ping_pong,
    queue,
    generator,
    pipeline,
    fan_out_fan_in,
    worker_pool,
    semaphore,
    timeout,
    non_blocking,
    or_done,
    rate_limit,
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
