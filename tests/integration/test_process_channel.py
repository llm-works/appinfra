# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A process service talks to its parent over the built-in channel, per start method."""

import multiprocessing as mp
import subprocess
import sys
import time
from pathlib import Path

import pytest

from appinfra.log import Logger
from appinfra.service import (
    BufferedChannel,
    Channel,
    ChannelPair,
    ChannelTimeoutError,
    Message,
    ProcessQueueChannelFactory,
    ProcessQueueTransport,
    ProcessRunner,
    Service,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


class EchoService(Service):
    """Answers every request on its channel with "pong:<payload>"."""

    def __init__(self, lg: Logger) -> None:
        self._lg = lg
        self.channel: Channel | None = None

    @property
    def name(self) -> str:
        return "echo"

    def run(self) -> None:
        assert self.channel is not None
        while not self.stopping.is_set():
            try:
                request = self.channel.recv(timeout=0.1)
            except ChannelTimeoutError:
                continue
            self.channel.send(Message(id=request.id, payload=f"pong:{request.payload}"))

    def is_healthy(self) -> bool:
        return True


class QuitService(Service):
    """Exits at once without reading its channel."""

    def __init__(self, lg: Logger) -> None:
        self._lg = lg
        self.channel: Channel | None = None

    @property
    def name(self) -> str:
        return "quit"

    def run(self) -> None:
        pass


def _connect(
    service: EchoService | QuitService, start_method: str | None = None
) -> tuple[ProcessRunner, ChannelPair]:
    """A runner for *service* and a channel pair to it, both from *start_method*.

    The parent's end may drop what the service never read when this process
    exits, instead of blocking the exit on it.
    """
    pair = ProcessQueueChannelFactory(start_method=start_method).create_pair()
    assert isinstance(pair.parent, BufferedChannel)
    transport = pair.parent.transport
    assert isinstance(transport, ProcessQueueTransport)
    transport.allow_exit_without_flush()
    service.channel = pair.child
    return ProcessRunner(service, start_method=start_method), pair


def run_dead_child(method: str) -> None:
    """Queue 1 MiB of requests to a service whose process has exited, then stop."""
    mp.set_start_method(method, force=True)
    runner, pair = _connect(QuitService(Logger(name="test")))
    runner.start()
    try:
        _wait_exited(runner)
        for i in range(16):
            pair.parent.send(Message(id=str(i), payload="x" * 65536))
    finally:
        runner.stop()
        pair.close()
    print("closed")


def _wait_exited(runner: ProcessRunner) -> None:
    deadline = time.monotonic() + 10.0
    while runner.is_alive():
        if time.monotonic() > deadline:
            raise TimeoutError("service process did not exit")
        time.sleep(0.01)


def run_echo(method: str, runner_method: str | None = None) -> None:
    """Start EchoService, submit one request, print the reply, stop.

    *method* is the interpreter's default start method, *runner_method* the
    one for the runner and its channel (None: the default).
    """
    mp.set_start_method(method, force=True)
    runner, pair = _connect(EchoService(Logger(name="test")), runner_method)
    runner.start()
    try:
        runner.wait_healthy(timeout=10.0)
        reply = pair.parent.submit(Message(payload="ping"), timeout=10.0)
        print(f"reply={reply.payload}")
    finally:
        runner.stop()
        pair.close()


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
def test_service_answers_over_its_channel(method: str) -> None:
    """The service's end of the channel reaches the child and the reply comes back.

    Under spawn and forkserver the service, channel included, is pickled into the
    child.
    """
    proc = _run_parent("run_echo", method)
    assert proc.returncode == 0, proc.stderr
    assert "reply=pong:ping" in proc.stdout, proc.stdout + proc.stderr


@pytest.mark.parametrize("method", mp.get_all_start_methods())
def test_parent_exits_after_its_service_died(method: str) -> None:
    """Requests queued to a service whose process is gone do not keep the parent alive."""
    proc = _run_parent("run_dead_child", method)
    assert proc.returncode == 0, proc.stderr
    assert "closed" in proc.stdout, proc.stdout + proc.stderr


@pytest.mark.parametrize("runner_method", ["forkserver", "spawn"])
def test_one_start_method_for_runner_and_channel(runner_method: str) -> None:
    """A start method other than the default works for the runner and its channel
    queues alike.

    Under a fork default, queues from the default context would be refused by a
    forkserver or spawn child ("SemLock created in a fork context").
    """
    proc = _run_parent("run_echo", "fork", runner_method)
    assert proc.returncode == 0, proc.stderr
    assert "reply=pong:ping" in proc.stdout, proc.stdout + proc.stderr
