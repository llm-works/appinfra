# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Uvicorn service for ProcessRunner integration."""

from __future__ import annotations

import multiprocessing as mp
from ctypes import c_int
from multiprocessing.synchronize import Event as MPEvent
from typing import TYPE_CHECKING, Any

from ....service import Service

if TYPE_CHECKING:
    from ....log import Logger
    from ..config.api import ApiConfig
    from .adapter import FastAPIAdapter
    from .watched_server import WatchedServer

# uvicorn's exit status for a failed startup (its STARTUP_FAILURE). uvicorn moved the constant
# from uvicorn.main to uvicorn.config, so no one import path holds it across supported versions.
_UVICORN_STARTUP_FAILURE = 3


class UvicornService(Service):
    """Service wrapper for running uvicorn in a subprocess.

    Integrates with ProcessRunner to provide:
    - Subprocess isolation for uvicorn
    - Health from its own uvicorn server having started
    - Proper logging forwarding to parent process

    The service setup() validates configuration in the parent process.
    The execute() method runs in the subprocess and starts uvicorn.

    Example:
        service = UvicornService(lg, "myapi", adapter, config, request_q, response_q)
        runner = ProcessRunner(service, policy=RestartPolicy(max_retries=5))
        runner.start()
        runner.wait_healthy(timeout=30.0)
        runner.start_monitor()  # Enable auto-restart
        port = service.bound_port
    """

    def __init__(
        self,
        lg: Logger,
        server_name: str,
        adapter: FastAPIAdapter,
        config: ApiConfig,
        request_q: mp.Queue[Any] | None = None,
        response_q: mp.Queue[Any] | None = None,
    ) -> None:
        """Initialize uvicorn service.

        Args:
            lg: Logger instance (for parent process, subprocess gets its own)
            server_name: Name of the server it runs; the service is named after it
            adapter: FastAPI adapter with route definitions
            config: API configuration; port 0 lets the OS pick the port
            request_q: IPC request queue (optional, for subprocess mode)
            response_q: IPC response queue (optional, for subprocess mode)
        """
        self._lg = lg
        self._server_name = server_name
        self._adapter = adapter
        self._config = config
        # Created by setup() in the parent; the subprocess writes the port it bound
        self._bound_port: c_int | None = None
        self._request_q = request_q
        self._response_q = response_q
        # Injected by ProcessRunner in subprocess
        self._shutdown_event: MPEvent | None = None
        # Set by execute() in the subprocess
        self._server: WatchedServer | None = None

    @property
    def name(self) -> str:
        """Service name, after the server's: it names the subprocess, its logger and the
        runner's errors, and stays the same whichever port the server binds."""
        return f"uvicorn-{self._server_name}"

    @property
    def bound_port(self) -> int:
        """The port the subprocess's server bound, or 0 until it is ready.

        With port 0 in the config, the port the OS picked.
        """
        return 0 if self._bound_port is None else int(self._bound_port.value)

    def setup(self) -> None:
        """Validate configuration and create the shared bound port (runs in parent
        process)."""
        from ..errors import ConfigError

        if self._config.port < 0 or self._config.port > 65535:
            raise ConfigError(f"Invalid port: {self._config.port}")
        if not self._config.host:
            raise ConfigError("Host is required")
        # uvicorn's multi-worker mode needs the app as an import string, and
        # this service passes the built app object.
        if self._config.uvicorn.workers != 1:
            raise ConfigError("uvicorn workers must be 1 in subprocess mode")
        # From the context ProcessRunner starts the subprocess with; a new one per
        # start, so a restarted server is not taken for ready on the old port
        context = mp.get_context(self._config.start_method)
        self._bound_port = context.RawValue("i", 0)

    def _setup_subprocess_logging(self) -> None:
        """Set up logging for subprocess."""
        from .logging import setup_subprocess_logging

        setup_subprocess_logging(
            self._config.log_file,
            log_level=self._config.uvicorn.log_level,
        )
        self._adapter.inject_subprocess_logger(self._lg)

    def _create_ipc_channel(self) -> Any:
        """Create IPC channel if queues are configured."""
        from .ipc import IPCChannel

        if self._request_q is None or self._response_q is None:
            return None

        if self._config.ipc is None:
            from ..config.ipc import IPCConfig

            self._config.ipc = IPCConfig()
        return IPCChannel(self._request_q, self._response_q, self._config.ipc)

    def _get_config_files_for_watcher(self) -> list[str]:
        """Get config files for hot-reload watcher.

        Note: Currently only supports single config file from ApiConfig.
        For layered configs, config_files should be passed via ApiConfig.
        """
        if self._config.etc_dir and self._config.config_file:
            from pathlib import Path

            return [str(Path(self._config.etc_dir) / self._config.config_file)]
        return []

    def _build_uvicorn_config(self, app: Any) -> Any:
        """Build uvicorn.Config for the given app."""
        import uvicorn

        from .server import _build_uvicorn_log_config

        uvicorn_kwargs = self._config.uvicorn.to_uvicorn_kwargs()
        uvicorn_kwargs["log_config"] = _build_uvicorn_log_config(self._config)
        return uvicorn.Config(
            app,
            host=self._config.host,
            port=self._config.port,
            **uvicorn_kwargs,
        )

    def execute(self) -> None:
        """Run uvicorn (runs in subprocess).

        Exits on SIGTERM/SIGINT, when the shutdown event is set, or when the
        parent process dies (see ``WatchedServer``).
        """
        from ....subprocess import SubprocessContext
        from .watched_server import WatchedServer

        if self._shutdown_event is None:
            raise RuntimeError("_shutdown_event must be injected by ProcessRunner")
        if self._bound_port is None:
            raise RuntimeError("setup() must run before execute()")
        bound_port = self._bound_port
        self._setup_subprocess_logging()

        with SubprocessContext(
            lg=self._lg,
            config_files=self._get_config_files_for_watcher(),
            handle_signals=False,  # uvicorn handles SIGTERM/SIGINT
        ):
            ipc_channel = self._create_ipc_channel()
            app = self._adapter.build(ipc_channel=ipc_channel)
            config = self._build_uvicorn_config(app)
            server = WatchedServer(
                config, self._shutdown_event, ipc_channel, bound_port
            )
            self._server = server
            server.run()
            if not server.started:
                raise SystemExit(_UVICORN_STARTUP_FAILURE)

    def teardown(self) -> None:
        """Cleanup - uvicorn shuts itself down (see ``execute``)."""

    def is_healthy(self) -> bool:
        """Whether this service's uvicorn server is ready: ran the app's startup, bound
        its socket and published the bound port.

        Not a probe of the port: uvicorn runs the startup before it binds, so while
        another process holds the port, that process would answer the probe for a
        server that is still starting and about to fail its bind.
        """
        server = self._server
        return server is not None and server.ready
