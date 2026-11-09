# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Messages for the channel tests."""

from dataclasses import dataclass


@dataclass
class Request:
    """Test request message."""

    id: str
    data: str


@dataclass
class Response:
    """Test response message."""

    id: str
    result: str
    error: str | None = None
