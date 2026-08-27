# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Uvicorn server configuration."""

from dataclasses import dataclass
from typing import Any


@dataclass
class UvicornConfig:
    """
    Uvicorn server configuration.

    Attributes:
        workers: Number of worker processes (default: 1)
        timeout_keep_alive: Keep-alive timeout in seconds (default: 5)
        limit_concurrency: Max concurrent connections (None = unlimited)
        limit_max_requests: Max requests per worker before restart (None = unlimited)
        backlog: Socket backlog size (default: 2048)
        log_level: Uvicorn log level (default: "warning")
        access_log: Enable access logging (default: False)
        ssl_keyfile: Path to SSL key file (optional)
        ssl_certfile: Path to SSL certificate file (optional)
    """

    workers: int = 1
    timeout_keep_alive: int = 5
    limit_concurrency: int | None = None
    limit_max_requests: int | None = None
    backlog: int = 2048
    log_level: str = "warning"
    access_log: bool = False
    ssl_keyfile: str | None = None
    ssl_certfile: str | None = None

    def to_uvicorn_kwargs(self) -> dict[str, Any]:
        """
        Convert to uvicorn.run() kwargs.

        Only includes optional parameters if they are set, to avoid
        overriding uvicorn defaults with None values.

        Returns:
            Dictionary of kwargs for uvicorn.run()
        """
        kwargs: dict[str, Any] = {
            "workers": self.workers,
            "timeout_keep_alive": self.timeout_keep_alive,
            "backlog": self.backlog,
            "log_level": self.log_level,
            "access_log": self.access_log,
        }

        if self.limit_concurrency is not None:
            kwargs["limit_concurrency"] = self.limit_concurrency

        if self.limit_max_requests is not None:
            kwargs["limit_max_requests"] = self.limit_max_requests

        if self.ssl_keyfile and self.ssl_certfile:
            kwargs["ssl_keyfile"] = self.ssl_keyfile
            kwargs["ssl_certfile"] = self.ssl_certfile

        return kwargs
