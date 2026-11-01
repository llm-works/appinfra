# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""HTTP API server configuration."""

from dataclasses import dataclass, field

from .ipc import IPCConfig
from .uvicorn import UvicornConfig


@dataclass
class ApiConfig:
    """
    HTTP API server configuration.

    Combines server binding, OpenAPI metadata, subprocess settings, and
    nested uvicorn/IPC configuration.

    Attributes:
        host: Bind address (default: "0.0.0.0")
        port: Bind port (default: 8000)
        title: API title for OpenAPI docs (default: "API Server")
        description: API description for OpenAPI docs
        version: API version (default: "0.1.0")
        docs_url: Path of the Swagger UI page, or None to not serve it
            (default: None). Also controls /docs/oauth2-redirect.
        redoc_url: Path of the ReDoc page, or None to not serve it
            (default: None)
        openapi_url: Path of the OpenAPI schema, or None to not serve it
            (default: None). The docs pages need it to render.
        response_timeout: Default response timeout in seconds (default: 60.0).
            Used when IPC is not configured.
        log_file: Path for subprocess log isolation (optional).
            When set, subprocess logs are written to this file and
            stdout/stderr are redirected.
        etc_dir: Base directory for config files (from --etc-dir).
            Required for subprocess config hot-reload.
        config_file: Config filename relative to etc_dir (e.g., "config.yaml").
            Required for subprocess config hot-reload.
        auto_restart: Restart subprocess on crash (default: True)
        restart_delay: Delay before restart in seconds (default: 1.0)
        max_restarts: Max restarts before giving up (default: 5, 0=unlimited)
        start_method: multiprocessing start method for the server subprocess
            ("fork", "spawn", "forkserver"); None uses the default. Spawn or
            forkserver keeps restarts from forking off the monitor thread. The
            queues given to with_ipc() must come from the same start method.
        uvicorn: Uvicorn server configuration
        ipc: IPC configuration (None = direct mode, no subprocess)
    """

    host: str = "0.0.0.0"
    port: int = 8000
    title: str = "API Server"
    description: str = ""
    version: str = "0.1.0"
    # Off by default: the schema lists every route, so serving it is opt-in.
    docs_url: str | None = None
    redoc_url: str | None = None
    openapi_url: str | None = None
    response_timeout: float = 60.0
    log_file: str | None = None
    etc_dir: str | None = None  # For subprocess config hot-reload
    config_file: str | None = None  # For subprocess config hot-reload
    auto_restart: bool = True
    restart_delay: float = 1.0
    max_restarts: int = 5
    start_method: str | None = None
    uvicorn: UvicornConfig = field(default_factory=UvicornConfig)
    ipc: IPCConfig | None = None
