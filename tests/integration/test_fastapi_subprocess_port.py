# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Port 0 in subprocess mode: the server's child binds a port the OS picks, and
Server.port gives that port once start_subprocess() returns. The port is never free
between choosing and binding it, so tests running in parallel cannot take each other's."""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers.http import wait_ready


def _fastapi_available() -> bool:
    try:
        from appinfra.app.fastapi.runtime.adapter import FASTAPI_AVAILABLE

        return FASTAPI_AVAILABLE
    except ImportError:
        return False


if not _fastapi_available():
    pytest.skip("FastAPI not available (may be shadowed)", allow_module_level=True)


def _ping_handler() -> dict[str, str]:
    """Readiness route. Module-level for picklability under spawn."""
    return {"status": "ok"}


def _build_server(port: int) -> Any:
    from appinfra.app.fastapi.builder.server import ServerBuilder
    from appinfra.log import Logger

    return (
        ServerBuilder(Logger("test-subprocess-port"), "test-subprocess-port")
        .with_host("127.0.0.1")
        .with_port(port)
        .routes.with_route("/ping", _ping_handler, methods=["GET"])
        .done()
        .subprocess.with_ipc()
        .done()
        .build()
    )


def test_port_zero_serves_on_the_port_the_os_picked() -> None:
    """The shared port reaches the subprocess, and its bound port the parent."""
    server = _build_server(0)
    server.start_subprocess()
    try:
        assert server.port != 0
        wait_ready(f"http://127.0.0.1:{server.port}/ping", deadline_secs=10.0)
    finally:
        server.stop(timeout=5.0)
