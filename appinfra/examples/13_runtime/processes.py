#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Process Chans: channels between a process and its process tasks.

A ``Chan(n, process=True)`` lives in the process that made it, its home; handed
to a process task, it arrives in the child as the same Chan, and the child uses
it as the parent does. Each example is a function, from a child sending to a
child's own tasks reporting their ends; main() runs them in order. A child's
function is defined at module level, as the child finds it in this module by
name.
"""

import math
import sys
from collections.abc import Callable
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.log import LogConfig, Logger, LoggerFactory
from appinfra.runtime import (
    Chan,
    ChanClosedError,
    ChanRecv,
    Runtime,
    TaskDone,
    select,
)


def _logger() -> Logger:
    """A logger for this process, the parent or a child."""
    return LoggerFactory.create_root(LogConfig.from_params(level="info"))


# -- functions the child processes run ------------------------------------------------


def squares(out: Chan[int], n: int) -> None:
    """In the child: send n squares, then close."""
    for i in range(n):
        out.send(i * i, timeout=10.0)
    out.close()


def square_server(requests: Chan[tuple[int, Chan[int]]]) -> None:
    """In the child: answer each request on the Chan it came with."""
    for n, reply in requests:  # until the parent closes the requests
        reply.send(n * n, timeout=10.0)


def run_jobs(done: Chan[TaskDone], go: Chan[bool]) -> None:
    """In the child: run tasks on a runtime of its own, each reporting its end
    on the parent's Chan; stay until told to go, so the runtime does not stop
    tasks that have not ended yet."""
    with Runtime(_logger()) as rt:
        for n in (16, 81, -1):
            rt.spawn(math.isqrt, n, name=f"isqrt({n})", done=done)
        go.recv(timeout=10.0)


def greet(out: Chan[str]) -> None:
    """In the child: send one greeting, then close."""
    out.send("hello from the child", timeout=10.0)
    out.close()


# -- the examples ---------------------------------------------------------------------


def from_a_child(lg: Logger, rt: Runtime) -> None:
    """A child sends; the parent receives until the child closes."""
    out: Chan[int] = Chan(4, process=True)
    child = rt.spawn(squares, out, 10, process=True)
    lg.info("received", extra={"values": list(out)})
    child.wait(timeout=10.0)


def request_and_reply(lg: Logger, rt: Runtime) -> None:
    """Each request carries the Chan its reply comes back on: no ids, no
    second channel to match replies against."""
    requests: Chan[tuple[int, Chan[int]]] = Chan(4, process=True)
    child = rt.spawn(square_server, requests, process=True)
    answers = []
    for n in (3, 4, 5):
        reply: Chan[int] = Chan(1, process=True)
        requests.send((n, reply), timeout=10.0)
        answers.append(reply.recv(timeout=10.0))
    requests.close()  # the child's loop ends
    lg.info("replies", extra={"answers": answers})
    child.wait(timeout=10.0)


def a_childs_task_ends(lg: Logger, rt: Runtime) -> None:
    """A child runs its own tasks with done= on the parent's Chan: the parent
    learns of each end, errors included, as a TaskDone."""
    done: Chan[TaskDone] = Chan(3, process=True)
    go: Chan[bool] = Chan(1, process=True)
    child = rt.spawn(run_jobs, done, go, process=True)
    for _ in range(3):
        end = done.recv(timeout=10.0)
        if end.error is None:
            lg.info("task ended", extra={"task": end.name, "result": end.result})
        else:
            lg.warning(
                "task failed (expected)",
                extra={"task": end.name, "error": str(end.error)},
            )
    go.send(True, timeout=10.0)
    child.wait(timeout=10.0)


def select_in_the_home(lg: Logger, rt: Runtime) -> None:
    """A process Chan takes part in select in its home, next to a local
    Chan; a child's proxy of it cannot."""
    remote: Chan[str] = Chan(1, process=True)
    child = rt.spawn(greet, remote, process=True)
    local: Chan[str] = Chan(1)
    local.send("hello from this process")
    local.close()
    cases, seen = [ChanRecv(local), ChanRecv(remote)], []
    while cases:
        try:
            _, value = select(*cases, timeout=10.0)
        except ChanClosedError as e:
            assert e.index is not None
            del cases[e.index]
            continue
        seen.append(value)
    lg.info("merged", extra={"values": seen})
    child.wait(timeout=10.0)


EXAMPLES: list[Callable[[Logger, Runtime], None]] = [
    from_a_child,
    request_and_reply,
    a_childs_task_ends,
    select_in_the_home,
]


def main() -> int:
    """Run every example in order, on one runtime."""
    lg = _logger()
    with Runtime(lg) as rt:
        for n, example in enumerate(EXAMPLES, 1):
            lg.info("example", extra={"n": n, "example": example.__name__})
            example(lg, rt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
