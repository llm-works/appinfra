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
        uvicorn: Uvicorn server configuration
        ipc: IPC configuration (None = direct mode, no subprocess)
    """

    host: str = "0.0.0.0"
    port: int = 8000
    title: str = "API Server"
    description: str = ""
    version: str = "0.1.0"
    response_timeout: float = 60.0
    log_file: str | None = None
    etc_dir: str | None = None  # For subprocess config hot-reload
    config_file: str | None = None  # For subprocess config hot-reload
    auto_restart: bool = True
    restart_delay: float = 1.0
    max_restarts: int = 5
    uvicorn: UvicornConfig = field(default_factory=UvicornConfig)
    ipc: IPCConfig | None = None
