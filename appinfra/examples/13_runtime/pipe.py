#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Pipes: a channel from one process to another.

Each end goes to the process that uses it and is opened there; a process that
hands an end over releases its own copy. Each example is a function, from both
ends in one process to a child's tasks reporting their ends; main() runs them
in order. A child's function is defined at module level, as the spawn start
method imports this module in the child to find it.
"""

import math
import multiprocessing as mp
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
    PipeRecvEnd,
    PipeSendEnd,
    Runtime,
    TaskDone,
    pipe,
    select,
)

_ctx = mp.get_context("spawn")  # the same on Linux and macOS


def _logger() -> Logger:
    """A logger for this process, the parent or a child."""
    return LoggerFactory.create_root(LogConfig.from_params(level="info"))


# -- functions the child processes run ------------------------------------------------


def squares(send: PipeSendEnd[int], n: int) -> None:
    """In the child: open the sending end, send n squares, close."""
    out = send.open()
    for i in range(n):
        out.send(i * i)
    out.close()  # returns once the values are on the pipe


def square_server(requests: PipeRecvEnd[int], replies: PipeSendEnd[int]) -> None:
    """In the child: answer each request with its square."""
    out = replies.open()
    for n in requests.open():  # until the parent closes its end
        out.send(n * n)
    out.close()


def run_jobs(done: PipeSendEnd[TaskDone]) -> None:
    """In the child: run tasks on a runtime of its own, ends on the pipe."""
    ends = done.open()
    with Runtime(_logger()) as rt:
        for n in (16, 81, -1):
            rt.spawn(math.isqrt, n, name=f"isqrt({n})", done=ends)
    ends.close()  # the runtime's stop has sent every end


def greet(send: PipeSendEnd[str]) -> None:
    """In the child: send one greeting, close."""
    out = send.open()
    out.send("hello from the child")
    out.close()


# -- the examples ---------------------------------------------------------------------


def in_one_process(lg: Logger) -> None:
    """Both ends in one process: the plainest use, values pickled on the way."""
    send, recv = pipe(2)
    sender, receiver = send.open(), recv.open()
    sender.send({"id": 1, "tags": ["a", "b"]})
    lg.info("received", extra={"value": receiver.recv(timeout=5.0)})
    sender.close()


def from_a_child(lg: Logger) -> None:
    """A child process sends; the parent receives until the child closes."""
    send, recv = pipe(4)
    child = _ctx.Process(target=squares, args=(send, 10))
    child.start()
    send.release()  # the child has its copy: its exit closes the channel
    lg.info("received", extra={"values": list(recv.open())})
    child.join(timeout=10.0)


def request_and_reply(lg: Logger) -> None:
    """Two pipes, one each way: requests to a child, replies back."""
    req_send, req_recv = pipe(4)
    rep_send, rep_recv = pipe(4)
    child = _ctx.Process(target=square_server, args=(req_recv, rep_send))
    child.start()
    req_recv.release()
    rep_send.release()
    requests, replies = req_send.open(), rep_recv.open()
    answers = []
    for n in (3, 4, 5):
        requests.send(n)
        answers.append(replies.recv(timeout=10.0))
    requests.close()  # the child's loop ends, and it closes the replies
    lg.info("replies", extra={"answers": answers})
    child.join(timeout=10.0)


def a_childs_task_ends(lg: Logger) -> None:
    """A child runs its own tasks with done= on a pipe: the parent learns of
    each end, errors included, as a TaskDone."""
    send, recv = pipe(8)
    child = _ctx.Process(target=run_jobs, args=(send,))
    child.start()
    send.release()
    for end in recv.open():
        if end.error is None:
            lg.info("task ended", extra={"task": end.name, "result": end.result})
        else:
            lg.warning(
                "task failed (expected)",
                extra={"task": end.name, "error": str(end.error)},
            )
    child.join(timeout=10.0)


def select_over_a_pipe(lg: Logger) -> None:
    """A pipe's receiver takes part in select next to a local channel."""
    send, recv = pipe(1)
    child = _ctx.Process(target=greet, args=(send,))
    child.start()
    send.release()
    local, remote = Chan[str](1), recv.open()
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
    child.join(timeout=10.0)


EXAMPLES: list[Callable[[Logger], None]] = [
    in_one_process,
    from_a_child,
    request_and_reply,
    a_childs_task_ends,
    select_over_a_pipe,
]


def main() -> int:
    """Run every example in order."""
    lg = _logger()
    for n, example in enumerate(EXAMPLES, 1):
        lg.info("example", extra={"n": n, "example": example.__name__})
        example(lg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
