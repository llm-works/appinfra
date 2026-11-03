# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for tests.helpers.http.wait_ready against a local socket server."""

from __future__ import annotations

import socket
import threading

import pytest

from tests.helpers.http import wait_ready

_OK = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
_REDIRECT = (
    b"HTTP/1.1 302 Found\r\nLocation: /ready\r\nContent-Length: 0\r\n"
    b"Connection: close\r\n\r\n"
)


def _read_request_path(conn: socket.socket) -> str:
    """Read one request head (a GET has no body); return its path."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    request_line = data.split(b"\r\n", 1)[0].split()
    return request_line[1].decode() if len(request_line) > 1 else ""


class _Server:
    """A local HTTP server on its own thread, for one test.

    Each request for /ping gets the next of ``ping_replies``, the last one from then on; any
    other path gets 200. A reply of None leaves the request unanswered until the client gives
    up. ``pings`` counts the /ping requests. It answers until the test leaves the block, so a
    poll that times out on a loaded machine is answered on the next try.
    """

    def __init__(self, ping_replies: list[bytes | None]) -> None:
        self.pings = 0
        self._replies = ping_replies
        self._stop = threading.Event()
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self._listener.getsockname()[1]}/ping"
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> _Server:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        # A connection of our own wakes the accept() the thread waits in
        socket.create_connection(self._listener.getsockname()).close()
        self._thread.join(timeout=5.0)
        self._listener.close()
        assert not self._thread.is_alive(), "the server thread did not stop"

    def _serve(self) -> None:
        while True:
            conn, _ = self._listener.accept()
            with conn:
                if self._stop.is_set():
                    return
                self._answer(conn)

    def _answer(self, conn: socket.socket) -> None:
        if _read_request_path(conn) != "/ping":
            conn.sendall(_OK)
            return
        reply = self._replies[min(self.pings, len(self._replies) - 1)]
        self.pings += 1
        if reply is None:
            # recv() returns b"" once the client closes the connection after its timeout
            while conn.recv(4096):
                pass
        else:
            conn.sendall(reply)


@pytest.mark.parametrize("slow_polls", [1, 2])
def test_wait_ready_retries_polls_that_time_out(slow_polls: int) -> None:
    """A server that accepts but answers polls too late is not ready yet, not failed."""
    with _Server([None] * slow_polls + [_OK]) as server:
        wait_ready(server.url, deadline_secs=10.0)
    assert server.pings >= slow_polls + 1


def test_wait_ready_takes_only_a_success_from_the_url_itself() -> None:
    """A redirect, even to a page that answers, is not ready: the URL itself must succeed."""
    with _Server([_REDIRECT, _OK]) as server:
        wait_ready(server.url, deadline_secs=10.0)
    assert server.pings >= 2, "wait_ready took the redirect's target for the URL"
