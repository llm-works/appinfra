# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Messages for the IPCChannel tests."""

from dataclasses import dataclass


@dataclass
class MockRequest:
    """Mock request for testing."""

    id: str
    data: str


@dataclass
class MockResponse:
    """Mock response for testing."""

    id: str
    result: str
    error: str | None = None


@dataclass
class MockStreamChunk:
    """Mock stream chunk for testing."""

    id: str
    data: str
    is_final: bool = False
