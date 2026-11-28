# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A subprocess-mode server's IPC: its routes submit to the parent over
server.requests, a process Chan homed here, each request with the Chan its
reply comes back on."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import requests

from appinfra.log import Logger
from appinfra.runtime import Chan
from appinfra.runtime.chan import ClosedError
from appinfra.service import Runtime, State
from tests.helpers.http import wait_ready


def _fastapi_available() -> bool:
    try:
        from appinfra.app.fastapi.runtime.adapter import FASTAPI_AVAILABLE

        return FASTAPI_AVAILABLE
    except ImportError:
        return False


if not _fastapi_available():
    pytest.skip("FastAPI not available (may be shadowed)", allow_module_level=True)

from starlette.requests import Request  # noqa: E402  # after the skip: FastAPI's

NAME = "test-ipc"

# Seconds a call expected to end now may take: the failure path, not a wait
DUE = 10.0

Requests = Chan[tuple[str, Chan[str]]]


# The child runs these by name: module level, as the spawn method needs


def _ping_handler() -> dict[str, str]:
    return {"status": "ok"}


async def _echo_handler(data: str, request: Request) -> dict[str, Any]:
    ipc = request.app.state.ipc_channel
    return {"result": await ipc.submit(data, timeout=DUE)}


async def _stream_handler(data: str, request: Request) -> dict[str, Any]:
    ipc = request.app.state.ipc_channel
    return {"values": [value async for value in ipc.stream(data, timeout=DUE)]}


async def _failing_handler(data: str, request: Request) -> dict[str, Any]:
    """Names what ended its wait, if anything did."""
    try:
        return {"result": await request.app.state.ipc_channel.submit(data)}
    except Exception as e:
        return {"error": type(e).__name__}


async def _impatient_handler(data: str, request: Request) -> dict[str, Any]:
    """Gives up at once: the parent has not received the request yet."""
    try:
        await request.app.state.ipc_channel.submit(data, timeout=0)
    except TimeoutError:
        return {"timed_out": True}
    return {"timed_out": False}


@pytest.fixture
def rt() -> Iterator[Runtime]:
    runtime = Runtime(Logger(NAME), name="test")
    runtime.start()
    yield runtime
    runtime.stop(timeout=10.0)


def _echo(data: str, reply: Chan[str]) -> None:
    reply.send(f"processed:{data}", timeout=DUE)


def _spell(data: str, reply: Chan[str]) -> None:
    for letter in data:
        reply.send(letter, timeout=DUE)
    reply.close()  # ends the route's stream


class _Serving:
    """The parent's side on a thread: every request handed to *answer* with
    its reply Chan, until the requests Chan is closed."""

    def __init__(self, inbox: Requests, answer: Callable[[str, Chan[str]], None]):
        self._inbox = inbox
        self._answer = answer
        self._thread = threading.Thread(target=self._run)
        self._thread.start()

    def _run(self) -> None:
        for data, reply in self._inbox:
            self._answer(data, reply)

    def close(self) -> None:
        self._inbox.close()
        self._thread.join(DUE)
        assert not self._thread.is_alive()


def _start(rt: Runtime, **subprocess: Any) -> Any:
    """A started subprocess-mode server in *rt*; *subprocess* are with_*()
    settings of the subprocess facet, by name."""
    from appinfra.app.fastapi.builder.server import ServerBuilder

    facet = (
        ServerBuilder(Logger(NAME), NAME)
        .with_host("127.0.0.1")
        .with_port(0)
        .routes.with_route("/ping", _ping_handler, methods=["GET"])
        .with_route("/echo/{data}", _echo_handler, methods=["GET"])
        .with_route("/stream/{data}", _stream_handler, methods=["GET"])
        .with_route("/impatient/{data}", _impatient_handler, methods=["GET"])
        .with_route("/failing/{data}", _failing_handler, methods=["GET"])
        .done()
        .subprocess.with_ipc()
        .with_runtime(rt)
    )
    for setting, value in subprocess.items():
        getattr(facet, f"with_{setting}")(value)
    server = facet.done().build()
    server.start_subprocess()
    wait_ready(f"http://127.0.0.1:{server.port}/ping", deadline_secs=DUE)
    return server


def _get(server: Any, path: str) -> requests.Response:
    return requests.get(f"http://127.0.0.1:{server.port}{path}", timeout=DUE)


def _until(condition: Callable[[], bool]) -> bool:
    """Whether *condition* holds before DUE, for a change nothing signals
    here: a frame crossing from the child. The deadline is the failure path."""
    deadline = time.monotonic() + DUE
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


class TestSubmit:
    def test_a_route_submits_and_the_parent_replies(self, rt: Runtime) -> None:
        server = _start(rt)
        serving = _Serving(server.requests, _echo)
        try:
            resp = _get(server, "/echo/abc")
            assert resp.status_code == 200, resp.text
            assert resp.json() == {"result": "processed:abc"}
        finally:
            server.stop(timeout=5.0)
            serving.close()

    def test_a_stream_ends_when_the_parent_closes_the_reply(self, rt: Runtime) -> None:
        server = _start(rt)
        serving = _Serving(server.requests, _spell)
        try:
            resp = _get(server, "/stream/abc")
            assert resp.status_code == 200, resp.text
            assert resp.json() == {"values": ["a", "b", "c"]}
        finally:
            server.stop(timeout=5.0)
            serving.close()

    def test_a_reply_after_the_route_gave_up_is_refused(self, rt: Runtime) -> None:
        """The route's reply Chan is closed once it stops waiting: the
        parent learns nobody reads it, rather than sending into the void."""
        server = _start(rt)
        try:
            assert _get(server, "/impatient/abc").json() == {"timed_out": True}
            data, reply = server.requests.recv(timeout=DUE)
            assert data == "abc"
            with pytest.raises(ClosedError):
                reply.send("too late", timeout=DUE)
        finally:
            server.stop(timeout=5.0)
            server.requests.close()


class TestRuns:
    def test_a_stop_ends_a_route_waiting_for_its_reply(self, rt: Runtime) -> None:
        """Nobody answers, and the response timeout is far off: the stop
        itself fails the wait, and the route answers before the server ends."""
        server = _start(rt, response_timeout=600.0)
        got: list[requests.Response] = []
        asking = threading.Thread(target=lambda: got.append(_get(server, "/failing/x")))
        asking.start()
        try:
            assert _until(lambda: len(server.requests) == 1)
        finally:
            server.stop(timeout=5.0)
            asking.join(DUE)
            server.requests.close()
        assert [resp.json() for resp in got] == [{"error": "StoppedError"}]

    def test_a_restarted_server_reaches_the_same_requests(self, rt: Runtime) -> None:
        server = _start(rt, restart_delay=0.1)
        serving = _Serving(server.requests, _echo)
        try:
            runner = rt.services[f"uvicorn-{NAME}"]
            restarted = threading.Event()
            runner.on_state_change(
                lambda _n, _o, new: new == State.RUNNING and restarted.set()
            )
            process = server.process
            assert process is not None
            process.kill()
            assert restarted.wait(DUE * 3)
            wait_ready(f"http://127.0.0.1:{server.port}/ping", deadline_secs=DUE)
            assert _get(server, "/echo/again").json() == {"result": "processed:again"}
        finally:
            server.stop(timeout=5.0)
            serving.close()
