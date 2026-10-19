# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Integration tests for how the uvicorn subprocess exits.

The subprocess must exit when the parent sets the shutdown event (so
Server.stop() returns without escalating to SIGTERM) and when the parent dies
without cleaning up (SIGKILL). In both cases requests waiting on IPC for a
reply must fail at once instead of holding the shutdown for the response
timeout.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
import requests
from starlette.requests import Request


def _fastapi_available() -> bool:
    try:
        from appinfra.app.fastapi.runtime.adapter import FASTAPI_AVAILABLE

        return FASTAPI_AVAILABLE
    except ImportError:
        return False


if not _fastapi_available():
    pytest.skip("FastAPI not available (may be shadowed)", allow_module_level=True)


@dataclass
class _IPCRequest:
    """IPC request that nobody answers."""

    id: str


def _ping_handler() -> dict[str, str]:
    """Readiness route. Module-level for picklability under spawn."""
    return {"status": "ok"}


async def _wait_on_ipc(request: Request) -> dict[str, str]:
    """Wait for an IPC reply that never comes. Module-level for spawn."""
    ipc = request.app.state.ipc_channel
    await ipc.submit(_IPCRequest(id=str(uuid.uuid4())), timeout=60.0)
    return {"status": "answered"}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _build_server(port: int) -> Any:
    from appinfra.app.fastapi.builder.server import ServerBuilder
    from appinfra.log import Logger

    lg = Logger("test-subprocess-exit")
    return (
        ServerBuilder(lg, "test-subprocess-exit")
        .with_host("127.0.0.1")
        .with_port(port)
        .routes.with_route("/ping", _ping_handler, methods=["GET"])
        .with_route("/wait", _wait_on_ipc, methods=["GET"])
        .done()
        .subprocess.with_ipc(mp.Queue(), mp.Queue())
        .done()
        .build()
    )


def _wait_ready(port: int) -> None:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            if requests.get(f"http://127.0.0.1:{port}/ping", timeout=0.5).ok:
                return
        except requests.exceptions.ConnectionError:
            time.sleep(0.1)
    raise AssertionError("server did not become ready")


def _start_pending_request(port: int) -> tuple[threading.Thread, dict[str, Any]]:
    """GET /wait in a thread; the result dict gets the outcome and its time."""
    result: dict[str, Any] = {}

    def run() -> None:
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/wait", timeout=30.0)
            result["outcome"] = resp.status_code
        except requests.exceptions.RequestException as e:
            result["outcome"] = type(e).__name__
        result["done_at"] = time.monotonic()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(0.5)  # let the request reach ipc.submit()
    assert "outcome" not in result, "request finished before shutdown"
    return thread, result


def _pid_gone(pid: int) -> bool:
    """True if the process no longer exists or is a zombie awaiting reaping."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] == "Z"
    except OSError:
        return False


def _port_bindable(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _run_parent(method: str, port: int, pid_q: mp.Queue[int]) -> None:
    """Start the server subprocess with the given start method, then idle."""
    mp.set_start_method(method, force=True)
    server = _build_server(port)
    proc = server.start_subprocess()
    pid_q.put(proc.pid)
    time.sleep(120)


@pytest.mark.integration
class TestSubprocessExit:
    """The uvicorn subprocess exits promptly when told to or orphaned."""

    def test_stop_does_not_escalate(self) -> None:
        """stop() returns well before its timeout and the child exits cleanly."""
        port = _free_port()
        server = _build_server(port)
        proc = server.start_subprocess()
        _wait_ready(port)

        started = time.monotonic()
        server.stop(timeout=5.0)

        assert time.monotonic() - started < 2.0
        assert proc.exitcode == 0

    def test_stop_fails_request_waiting_on_ipc(self) -> None:
        """A request waiting on IPC fails at once instead of blocking stop()."""
        port = _free_port()
        server = _build_server(port)
        proc = server.start_subprocess()
        try:
            _wait_ready(port)
            thread, result = _start_pending_request(port)

            started = time.monotonic()
            server.stop(timeout=5.0)
            stopped_in = time.monotonic() - started
            thread.join(timeout=5.0)
        finally:
            if proc.is_alive():
                proc.kill()

        assert stopped_in < 2.0
        assert result["outcome"] == 500
        assert result["done_at"] - started < 2.0

    @pytest.mark.parametrize(
        "method",
        [m for m in ("fork", "spawn", "forkserver") if m in mp.get_all_start_methods()],
    )
    def test_child_exits_when_parent_is_killed(self, method: str) -> None:
        """SIGKILL of the parent frees the port and ends the child within seconds."""
        port = _free_port()
        ctx = mp.get_context("spawn")
        pid_q: mp.Queue[int] = ctx.Queue()
        parent = ctx.Process(target=_run_parent, args=(method, port, pid_q))
        parent.start()
        child_pid = pid_q.get(timeout=30.0)
        try:
            _wait_ready(port)
            thread, result = _start_pending_request(port)

            killed_at = time.monotonic()
            os.kill(parent.pid, signal.SIGKILL)
            parent.join(timeout=5.0)
            deadline = killed_at + 5.0
            while not _pid_gone(child_pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            exited_in = time.monotonic() - killed_at
            thread.join(timeout=5.0)

            assert _pid_gone(child_pid), "child outlived its parent"
            assert exited_in < 3.0
            assert result["done_at"] - killed_at < 3.0
            assert _port_bindable(port)
        finally:
            if not _pid_gone(child_pid):
                os.kill(child_pid, signal.SIGKILL)
