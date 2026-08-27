# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Network fixtures for testing.

Provides fixtures for mock servers, network connections, and HTTP testing.
"""

import socket
from collections.abc import Generator
from typing import Any
from unittest.mock import Mock

import pytest


@pytest.fixture
def mock_socket() -> Generator[Mock, None, None]:
    """
    Provide a mock socket for testing.

    Yields:
        Mock: Mock socket object
    """
    sock = Mock()
    sock.connect = Mock()
    sock.send = Mock(return_value=1024)
    sock.sendall = Mock()
    sock.recv = Mock(return_value=b"")
    sock.close = Mock()
    sock.settimeout = Mock()
    sock.setsockopt = Mock()

    yield sock

    sock.close()


@pytest.fixture
def mock_tcp_server(mock_socket: Mock) -> Generator[Mock, None, None]:
    """
    Provide a mock TCP server for testing.

    Args:
        mock_socket: Mock socket fixture

    Yields:
        Mock: Mock TCP server
    """
    server = Mock()
    server.bind = Mock()
    server.listen = Mock()
    server.accept = Mock(return_value=(mock_socket, ("127.0.0.1", 12345)))
    server.close = Mock()

    yield server

    server.close()


@pytest.fixture
def sample_http_response() -> dict[str, Any]:
    """
    Provide a sample HTTP response for testing.

    Returns:
        dict: Sample HTTP response data
    """
    return {
        "status_code": 200,
        "headers": {
            "Content-Type": "application/json",
            "Content-Length": "42",
        },
        "body": '{"status": "success", "data": []}',
    }


@pytest.fixture
def mock_http_client() -> Mock:
    """
    Provide a mock HTTP client for testing.

    Returns:
        Mock: Mock HTTP client
    """
    client = Mock()
    client.get = Mock()
    client.post = Mock()
    client.put = Mock()
    client.delete = Mock()
    client.close = Mock()

    return client


@pytest.fixture
def available_port() -> int:
    """
    Find an available port for testing.

    Returns:
        int: Available port number
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port
