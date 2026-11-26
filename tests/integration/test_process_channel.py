# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A channel pair across processes, per start method: a child answers over its
end, and a parent whose child died exits."""

import multiprocessing as mp
import subprocess
import sys
from pathlib import Path

import pytest

from appinfra.service import (
    BufferedChannel,
    Channel,
    ChannelPair,
    Message,
    ProcessQueueChannelFactory,
    ProcessQueueTransport,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _echo(channel: Channel) -> None:
    """The child: answer one request with "pong:<payload>"."""
    request = channel.recv(timeout=10.0)
    channel.send(Message(id=request.id, payload=f"pong:{request.payload}"))


def _quit() -> None:
    """The child: exit at once, reading nothing."""


def _pair(start_method: str | None = None) -> ChannelPair:
    """A channel pair from *start_method*; the parent's end may drop what the
    child never read when this process exits, instead of blocking the exit."""
    pair = ProcessQueueChannelFactory(start_method=start_method).create_pair()
    assert isinstance(pair.parent, BufferedChannel)
    transport = pair.parent.transport
    assert isinstance(transport, ProcessQueueTransport)
    transport.allow_exit_without_flush()
    return pair


def run_echo(method: str, child_method: str | None = None) -> None:
    """Start an echo child, submit one request, print the reply.

    *method* is the interpreter's default start method, *child_method* the one
    for the child and its channel (None: the default).
    """
    mp.set_start_method(method, force=True)
    pair = _pair(child_method)
    child = mp.get_context(child_method).Process(target=_echo, args=(pair.child,))
    child.start()
    try:
        reply = pair.parent.submit(Message(payload="ping"), timeout=10.0)
        print(f"reply={reply.payload}")
    finally:
        child.join(timeout=10.0)
        pair.close()


def run_dead_child(method: str) -> None:
    """Queue 1 MiB of requests to a child that has exited, then close."""
    mp.set_start_method(method, force=True)
    pair = _pair()
    child = mp.Process(target=_quit)
    child.start()
    child.join(timeout=10.0)
    try:
        for i in range(16):
            pair.parent.send(Message(id=str(i), payload="x" * 65536))
    finally:
        pair.close()
    print("closed")


def _run_parent(func: str, *args: str | None) -> subprocess.CompletedProcess[str]:
    """Run *func*(*args*) from this module as the parent, in its own interpreter.

    The start method is process-wide, so each one gets a fresh interpreter; that
    interpreter exiting is part of the check.
    """
    call = ", ".join(repr(a) for a in args)
    code = f"from tests.integration.test_process_channel import {func}; {func}({call})"
    method = "/".join(str(a) for a in args)
    try:
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{method}: the parent did not exit within 60 s")


@pytest.mark.parametrize("method", mp.get_all_start_methods())
def test_a_child_answers_over_its_end(method: str) -> None:
    """The child's end of the channel reaches it and the reply comes back.

    Under spawn and forkserver the child's end is pickled into the child.
    """
    proc = _run_parent("run_echo", method)
    assert proc.returncode == 0, proc.stderr
    assert "reply=pong:ping" in proc.stdout, proc.stdout + proc.stderr


def test_parent_exits_after_its_child_died() -> None:
    """Requests queued to a child that is gone do not keep the parent alive."""
    proc = _run_parent("run_dead_child", mp.get_start_method())
    assert proc.returncode == 0, proc.stderr
    assert "closed" in proc.stdout, proc.stdout + proc.stderr


@pytest.mark.skipif(
    "fork" not in mp.get_all_start_methods(), reason="needs the fork start method"
)
def test_one_start_method_for_child_and_channel() -> None:
    """A start method other than the default works for the child and its channel
    queues alike.

    Under a fork default, queues from the default context would be refused by a
    forkserver child ("SemLock created in a fork context").
    """
    proc = _run_parent("run_echo", "fork", "forkserver")
    assert proc.returncode == 0, proc.stderr
    assert "reply=pong:ping" in proc.stdout, proc.stdout + proc.stderr
