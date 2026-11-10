# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""UvicornService's setup and health, in the parent process.

setup() creates the multiprocessing shared value the subprocess writes its bound port
to. is_healthy() reports its own server, not whatever listens on its port: uvicorn
runs the app's lifespan startup before it binds the socket, and the subprocess health
poller calls is_healthy() throughout, so while another process holds the port, a port
probe answered by that process would report a server that is still starting, and about
to fail its bind, as healthy.
"""

import socket
from unittest.mock import MagicMock

import pytest

from appinfra.app.fastapi.config.api import ApiConfig

pytest.importorskip("uvicorn")

from appinfra.app.fastapi.runtime.service import UvicornService  # noqa: E402


def test_a_service_without_a_started_server_is_not_healthy_while_another_listens() -> (
    None
):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as other:
        other.bind(("127.0.0.1", 0))
        other.listen()
        config = ApiConfig(host="127.0.0.1", port=other.getsockname()[1])
        service = UvicornService(MagicMock(), MagicMock(), config)
        assert not service.is_healthy()


@pytest.mark.parametrize("port", [8000, 0], ids=["fixed", "OS-picked"])
def test_setup_accepts_the_port(port: int) -> None:
    service = UvicornService(MagicMock(), MagicMock(), ApiConfig(port=port))
    service.setup()
    assert service.bound_port == 0, "no port is bound before the subprocess runs"


def test_setup_accepts_a_single_worker() -> None:
    """The default single worker passes setup."""
    UvicornService(MagicMock(), MagicMock(), ApiConfig()).setup()
