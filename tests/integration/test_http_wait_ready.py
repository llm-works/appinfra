# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for tests.helpers.http.wait_ready against a local socket server."""

import socket
import threading

from tests.helpers.http import wait_ready

_OK = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


def _read_request(conn: socket.socket) -> None:
    """Read one request head; a GET has no body."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            return
        data += chunk


def _slow_then_ok(listener: socket.socket) -> None:
    """Leave the first request unanswered until the client gives up; answer the next."""
    slow, _ = listener.accept()
    with slow:
        _read_request(slow)
        # recv() returns b"" once the client closes the connection after its read timeout
        while slow.recv(4096):
            pass
    conn, _ = listener.accept()
    with conn:
        _read_request(conn)
        conn.sendall(_OK)


def test_wait_ready_retries_a_poll_that_times_out() -> None:
    """A server that accepts but answers one poll too late is not ready yet, not failed."""
    with socket.create_server(("127.0.0.1", 0)) as listener:
        port = listener.getsockname()[1]
        server = threading.Thread(target=_slow_then_ok, args=(listener,), daemon=True)
        server.start()

        wait_ready(f"http://127.0.0.1:{port}/ping", deadline_secs=10.0)

        server.join(timeout=5.0)
        assert not server.is_alive(), "the server thread did not answer the second poll"
