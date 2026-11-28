# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The FastAPI example's subprocess mode, as it ships: its server and the
loop that answers the server's requests."""

from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest
import requests

from tests.helpers.http import wait_ready


def _fastapi_available() -> bool:
    try:
        from appinfra.app.fastapi.runtime.adapter import FASTAPI_AVAILABLE

        return FASTAPI_AVAILABLE
    except ImportError:
        return False


if not _fastapi_available():
    pytest.skip("FastAPI not available (may be shadowed)", allow_module_level=True)

EXAMPLE = Path(__file__).resolve().parents[2] / "appinfra/examples/07_fastapi"

# Seconds a call expected to end now may take: the failure path, not a wait
DUE = 10.0


@pytest.fixture
def example(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """The example as a module its server's children import by name: they
    start with this process's sys.path."""
    monkeypatch.syspath_prepend(str(EXAMPLE))
    yield importlib.import_module("fastapi_server")


def _until(condition: Callable[[], bool]) -> bool:
    """Whether *condition* holds before DUE, for a change nothing signals
    here: a restarted child. The deadline is the failure path."""
    deadline = time.monotonic() + DUE
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def test_the_example_answers_across_a_restart(example: ModuleType) -> None:
    """Auto-restart is on: a crashed server comes back, and its routes are
    answered as before."""
    server = example.create_subprocess_server(port=0)
    server.start_subprocess()
    serving = threading.Thread(target=example.serve_requests, args=(server,))
    serving.start()
    try:
        url = f"http://127.0.0.1:{server.port}"
        assert requests.get(f"{url}/work/hi", timeout=DUE).json() == {"result": "HI"}

        crashed = server.pid
        server.process.kill()
        # The new run's port reads 0 until it has bound
        assert _until(lambda: server.pid not in (None, crashed) and server.port)
        url = f"http://127.0.0.1:{server.port}"
        wait_ready(f"{url}/health", deadline_secs=DUE)

        resp = requests.get(f"{url}/work/again", timeout=DUE * 2)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"result": "AGAIN"}
    finally:
        server.stop(timeout=5.0)
        server.requests.close()
        serving.join(DUE)
    assert not serving.is_alive()
