# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A subprocess-mode server as an isolated service of a service Runtime: what
the runtime's supervision means for it, through the server's public API. The
server is given the test's runtime (with_runtime()), so its runner is read
from rt.services and its transitions waited on through state hooks."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from appinfra.log import Logger
from appinfra.runtime import process as process_module
from appinfra.service import Runner, Runtime, State
from tests.helpers.http import wait_ready


def _fastapi_available() -> bool:
    try:
        from appinfra.app.fastapi.runtime.adapter import FASTAPI_AVAILABLE

        return FASTAPI_AVAILABLE
    except ImportError:
        return False


if not _fastapi_available():
    pytest.skip("FastAPI not available (may be shadowed)", allow_module_level=True)

NAME = "test-server-runtime"


def _ping_handler() -> dict[str, str]:
    """Readiness route. Module-level for picklability under spawn."""
    return {"status": "ok"}


async def _never_shuts_down(_app: Any) -> None:
    """A shutdown callback that never returns: the child ignores its stop."""
    await asyncio.Event().wait()


@pytest.fixture
def rt() -> Iterator[Runtime]:
    runtime = Runtime(Logger("test-server-runtime"), name="test")
    runtime.start()
    yield runtime
    runtime.stop(timeout=10.0)


def _build_server(rt: Runtime, port: int = 0, **subprocess: Any) -> Any:
    """A subprocess-mode server in *rt*; *subprocess* are with_*() settings of
    the subprocess facet, by name: auto_restart=False calls with_auto_restart(False)."""
    from appinfra.app.fastapi.builder.server import ServerBuilder

    builder = (
        ServerBuilder(Logger(NAME), NAME)
        .with_host("127.0.0.1")
        .with_port(port)
        .routes.with_route("/ping", _ping_handler, methods=["GET"])
        .done()
    )
    facet = builder.subprocess.with_ipc().with_runtime(rt)
    for setting, value in subprocess.items():
        getattr(facet, f"with_{setting}")(value)
    return facet.done()


def _wait_ready(server: Any) -> None:
    wait_ready(f"http://127.0.0.1:{server.port}/ping", deadline_secs=10.0)


def _until(condition: Any, timeout: float = 30.0) -> bool:
    """Poll *condition* until it holds; False once *timeout* passes. For a
    change no event signals: a child process starting."""
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def _on_state(runner: Runner, state: State) -> threading.Event:
    """An event set when *runner* next moves to *state*."""
    reached = threading.Event()

    def hook(_name: str, _old: State, new: State) -> None:
        if new == state:
            reached.set()

    runner.on_state_change(hook)
    return reached


class TestSupervision:
    def test_a_crashed_server_is_restarted(self, rt: Runtime) -> None:
        """Killed, the server's child is replaced by a new one that serves."""
        server = _build_server(rt, restart_delay=0.1).build()
        server.start_subprocess()
        try:
            runner = rt.services[f"uvicorn-{NAME}"]
            restarted = _on_state(runner, State.RUNNING)
            first = server.pid
            process = server.process
            assert process is not None

            process.kill()

            assert restarted.wait(30.0)
            assert server.pid not in (None, first)
            _wait_ready(server)
        finally:
            server.stop(timeout=5.0)

    def test_a_crashed_servers_port_reads_unbound_until_it_restarts(
        self, rt: Runtime
    ) -> None:
        """Killed, its child skips teardown(): the server reads no bound port
        while the runtime waits to restart it."""
        server = _build_server(rt, restart_delay=30.0).build()
        server.start_subprocess()
        try:
            runner = rt.services[f"uvicorn-{NAME}"]
            failed = _on_state(runner, State.FAILED)
            assert server.port != 0
            process = server.process
            assert process is not None

            process.kill()

            assert failed.wait(30.0)
            assert server.port == 0, "the dead child's port is not the server's"
        finally:
            server.stop(timeout=5.0)

    def test_an_interrupted_server_ends_without_a_restart(self, rt: Runtime) -> None:
        """Ctrl-C reaching the child alone ends its server cleanly: DONE, and
        the runtime does not start it again."""
        server = _build_server(rt).build()
        server.start_subprocess()
        try:
            runner = rt.services[f"uvicorn-{NAME}"]
            done = _on_state(runner, State.DONE)
            process = server.process
            assert process is not None and server.pid is not None

            os.kill(server.pid, signal.SIGINT)

            assert done.wait(30.0)
            assert process.detail().exitcode == 0
            assert f"uvicorn-{NAME}" not in rt.services
            assert server.process is None
        finally:
            server.stop(timeout=5.0)


class TestStop:
    def test_a_hung_server_is_terminated_then_killed(
        self, rt: Runtime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A child that does not end within stop()'s timeout is forced, and
        stop() returns once it has ended."""
        monkeypatch.setattr(process_module, "_GRACE", 0.2)
        server = (
            _build_server(rt).with_on_shutdown(_never_shuts_down, name="hang").build()
        )
        server.start_subprocess()
        process = server.process
        assert process is not None
        _wait_ready(server)

        server.stop(timeout=0.2)

        detail = process.detail()
        assert not detail.alive
        assert detail.exitcode in (-signal.SIGTERM, -signal.SIGKILL)

    def test_a_blocking_start_returns_when_stopped_in_a_restart_backoff(
        self, rt: Runtime
    ) -> None:
        """start() blocks until the server will not run again: killed, its
        child waits out the restart delay, and a stop() then ends the wait."""
        server = _build_server(rt, restart_delay=30.0).build()
        starter = threading.Thread(target=server.start, daemon=True)
        starter.start()
        name = f"uvicorn-{NAME}"
        assert _until(
            lambda: name in rt.services and rt.services[name].state == State.RUNNING
        ), "the server never came up"
        runner = rt.services[name]
        failed = _on_state(runner, State.FAILED)
        process = server.process
        assert process is not None

        process.kill()
        assert failed.wait(30.0)
        server.stop(timeout=5.0)

        starter.join(30.0)  # the timeout is the failure path
        assert not starter.is_alive(), "start() still blocks"

    def test_a_stop_during_start_leaves_no_child(self, rt: Runtime) -> None:
        """stop() from another thread while start_subprocess() waits for the
        server: the start fails and no child is left running."""
        server = _build_server(rt).build()
        runner_seen = threading.Event()
        original_spawn = rt.spawn

        def spawn(*args: Any, **kwargs: Any) -> Runner:
            runner = original_spawn(*args, **kwargs)
            runner_seen.set()
            return runner

        stopper = threading.Thread(
            target=lambda: runner_seen.wait(30.0) and server.stop(timeout=5.0)
        )
        stopper.start()
        try:
            rt.spawn = spawn  # type: ignore[method-assign]
            with pytest.raises(Exception):  # noqa: B017  # whichever ready() raises
                server.start_subprocess()
        finally:
            rt.spawn = original_spawn  # type: ignore[method-assign]
            stopper.join(30.0)

        assert not server.is_running
        assert f"uvicorn-{NAME}" not in rt.services


class TestFailedStart:
    def test_a_server_that_cannot_bind_fails_its_start(self, rt: Runtime) -> None:
        """Its port taken, the server's child fails to start: start_subprocess()
        raises, and with no restart allowed nothing is left in the runtime."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            server = _build_server(rt, port=port, auto_restart=False).build()

            with pytest.raises(Exception) as raised:  # noqa: B017
                server.start_subprocess()

        assert f"uvicorn-{NAME}" in str(raised.value)
        assert not server.is_running
        assert f"uvicorn-{NAME}" not in rt.services
