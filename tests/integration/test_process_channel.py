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
    Channel,
    ChannelTimeoutError,
    Message,
    Runner,
    RunnerFactory,
    Service,
)

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]


class EchoService(Service):
    """Answers every request on its channel with "pong:<payload>"."""

    def __init__(self, lg: Logger) -> None:
        self._lg = lg
        self._shutdown_event: mp.synchronize.Event | None = None  # injected
        self.channel: Channel | None = None

    @property
    def name(self) -> str:
        return "echo"

    def execute(self) -> None:
        assert self._shutdown_event is not None and self.channel is not None
        while not self._shutdown_event.is_set():
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

    def execute(self) -> None:
        pass


def run_dead_child(method: str) -> None:
    """Queue 1 MiB of requests to a service whose process has exited, then stop."""
    mp.set_start_method(method, force=True)
    lg = Logger(name="test")
    service = QuitService(lg)
    result = RunnerFactory(lg).create_process_runner_with_channel(service)
    service.channel = result.service_channel
    result.runner.start()
    try:
        _wait_exited(result.runner)
        for i in range(16):
            result.channel.send(Message(id=str(i), payload="x" * 65536))
    finally:
        result.runner.stop()
        result.channel.close()
        result.service_channel.close()
    print("closed")


def _wait_exited(runner: Runner) -> None:
    deadline = time.monotonic() + 10.0
    while runner.is_alive():
        if time.monotonic() > deadline:
            raise TimeoutError("service process did not exit")
        time.sleep(0.01)


def run_echo(method: str) -> None:
    """Start EchoService under *method*, submit one request, print the reply, stop."""
    mp.set_start_method(method, force=True)
    lg = Logger(name="test")
    service = EchoService(lg)
    result = RunnerFactory(lg).create_process_runner_with_channel(service)
    service.channel = result.service_channel
    result.runner.start()
    try:
        result.runner.wait_healthy(timeout=10.0)
        reply = result.channel.submit(Message(payload="ping"), timeout=10.0)
        print(f"reply={reply.payload}")
    finally:
        result.runner.stop()
        result.channel.close()
        result.service_channel.close()


def _run_parent(func: str, method: str) -> subprocess.CompletedProcess[str]:
    """Run *func* from this module as the parent, in its own interpreter.

    The start method is process-wide, so each one gets a fresh interpreter; that
    interpreter exiting is part of the check.
    """
    code = (
        f"from tests.integration.test_process_channel import {func}; {func}({method!r})"
    )
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
