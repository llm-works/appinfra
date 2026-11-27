# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""UvicornService's bound port and health, in the parent process.

The service makes the multiprocessing shared value its subprocess writes the
bound port to. is_healthy() reports its own server, not whatever listens on its
port: uvicorn runs the app's lifespan startup before it binds the socket, and
the subprocess health poller calls is_healthy() throughout, so while another
process holds the port, a port probe answered by that process would report a
server that is still starting, and about to fail its bind, as healthy.
"""

import multiprocessing as mp
import socket
from unittest.mock import MagicMock

import pytest

from appinfra.app.fastapi.config.api import ApiConfig

pytest.importorskip("uvicorn")

from appinfra.app.fastapi.runtime.service import UvicornService  # noqa: E402

CONTEXT = mp.get_context("spawn")


def test_a_service_without_a_started_server_is_not_healthy_while_another_listens() -> (
    None
):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as other:
        other.bind(("127.0.0.1", 0))
        other.listen()
        config = ApiConfig(host="127.0.0.1", port=other.getsockname()[1])
        service = UvicornService(MagicMock(), "api", MagicMock(), config, CONTEXT)
        assert not service.is_healthy()


@pytest.mark.parametrize("port", [8000, 0], ids=["fixed", "OS-picked"])
def test_a_new_service_has_bound_no_port(port: int) -> None:
    service = UvicornService(
        MagicMock(), "api", MagicMock(), ApiConfig(port=port), CONTEXT
    )
    assert service.bound_port == 0, "no port is bound before the subprocess runs"


def test_teardown_clears_the_bound_port() -> None:
    """Once its server has shut down, the service reports no port: a restart
    is not taken for ready on the last run's port."""
    service = UvicornService(MagicMock(), "api", MagicMock(), ApiConfig(), CONTEXT)
    service._bound_port.value = 8123  # as a child's server publishes it
    service.teardown()
    assert service.bound_port == 0
