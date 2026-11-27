# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Inter-process communication configuration."""

from dataclasses import dataclass


@dataclass
class IPCConfig:
    """
    Inter-process communication configuration.

    Controls the behavior of Chan-based IPC between the FastAPI subprocess
    and the main process.

    Attributes:
        response_timeout: Default timeout for waiting on responses in seconds
            (default: 60.0). Can be overridden per-request.
        max_pending: Maximum number of pending requests before rejection
            (default: 100). Prevents unbounded memory growth under load; also
            the capacity of the server's requests Chan.
        enable_health_reporting: Include IPC status in health endpoint
            (default: True). Reports pending_count and is_healthy status.
    """

    response_timeout: float = 60.0
    max_pending: int = 100
    enable_health_reporting: bool = True
