# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Uvicorn service, run isolated in a process of its own."""

from __future__ import annotations

from ctypes import c_int
from multiprocessing.context import BaseContext
from typing import TYPE_CHECKING, Any

from ....runtime import Chan
from ....service import Service, State
from ..errors import ConfigError
from .ipc import IPCChannel, Request

if TYPE_CHECKING:
    from ....log import Logger
    from ..config.api import ApiConfig
    from .adapter import FastAPIAdapter
    from .watched_server import WatchedServer

# uvicorn's exit status for a failed startup (its STARTUP_FAILURE). uvicorn moved the constant
# from uvicorn.main to uvicorn.config, so no one import path holds it across supported versions.
_UVICORN_STARTUP_FAILURE = 3

# The states a run has ended in: its process no longer serves
_ENDED = frozenset({State.FAILED, State.STOPPED, State.DONE})


class UvicornService(Service):
    """Uvicorn, run by the service Runtime in a process of its own
    (``spawn(service, isolate=True)``): its setup, run, health checks and
    teardown run there, its log records are forwarded to the parent's logger.

    The configuration is checked here, in the parent, when the service is made.
    The port the child bound is shared through a value made from the context
    children start in (``Runtime.process_context``); the requests Chan, homed
    in the parent, crosses into each run's child with the service.

    Example:
        service = UvicornService(lg, "myapi", adapter, config, rt.process_context)
        runner = rt.spawn(service, RestartPolicy(max_retries=5), isolate=True)
        rt.ready(runner, timeout=30.0)
        port = service.bound_port
    """

    def __init__(
        self,
        lg: Logger,
        server_name: str,
        adapter: FastAPIAdapter,
        config: ApiConfig,
        context: BaseContext,
        requests: Chan[Request] | None = None,
    ) -> None:
        """Initialize uvicorn service.

        Args:
            lg: Logger instance (for parent process, subprocess gets its own)
            server_name: Name of the server it runs; the service is named after it
            adapter: FastAPI adapter with route definitions
            config: API configuration; port 0 lets the OS pick the port
            context: The multiprocessing context its process starts in, which
                makes the value the child writes its bound port to
            requests: The process Chan the routes' IPC requests go to; None
                for a server without IPC

        Raises:
            ConfigError: If the configuration cannot run in a subprocess.
        """
        _check_config(config)
        self._lg = lg
        self._server_name = server_name
        self._adapter = adapter
        self._config = config
        # Written by the child once its server is up; 0 while none is
        self._bound_port: c_int = context.RawValue("i", 0)
        self._requests = requests
        # Set by run() in the subprocess
        self._server: WatchedServer | None = None

    @property
    def name(self) -> str:
        """Service name, after the server's: it names the subprocess, its logger and the
        runner's errors, and stays the same whichever port the server binds."""
        return f"uvicorn-{self._server_name}"

    @property
    def bound_port(self) -> int:
        """The port the subprocess's server bound, or 0 while none is up.

        With port 0 in the config, the port the OS picked.
        """
        return int(self._bound_port.value)

    def _setup_subprocess_logging(self) -> None:
        """Set up logging for subprocess."""
        from .logging import setup_subprocess_logging

        setup_subprocess_logging(
            self._config.log_file,
            log_level=self._config.uvicorn.log_level,
        )
        self._adapter.inject_subprocess_logger(self._lg)

    def _create_ipc_channel(self) -> IPCChannel | None:
        """The routes' IPC channel, over the requests Chan if there is one."""
        if self._requests is None:
            return None

        if self._config.ipc is None:
            from ..config.ipc import IPCConfig

            self._config.ipc = IPCConfig()
        return IPCChannel(self._requests, self._config.ipc)

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

    def run(self) -> None:
        """Run uvicorn (runs in subprocess).

        Exits on SIGTERM/SIGINT, once ``stopping`` is set, or when the parent
        process dies (see ``WatchedServer``).
        """
        from ....subprocess import SubprocessContext
        from .watched_server import WatchedServer

        # A restart's run starts unbound: the last run's port is not this one's
        bound_port = self._bound_port
        bound_port.value = 0
        self._setup_subprocess_logging()

        with SubprocessContext(
            lg=self._lg,
            config_files=self._get_config_files_for_watcher(),
            handle_signals=False,  # uvicorn handles SIGTERM/SIGINT
        ):
            ipc_channel = self._create_ipc_channel()
            app = self._adapter.build(ipc_channel=ipc_channel)
            config = self._build_uvicorn_config(app)
            server = WatchedServer(config, self.stopping, bound_port)
            self._server = server
            try:
                server.run()
            except KeyboardInterrupt:
                # uvicorn shuts down on SIGINT, then raises it again: an
                # interrupt asked the server to end, it did not crash
                return
            if not server.started:
                raise SystemExit(_UVICORN_STARTUP_FAILURE)

    def teardown(self) -> None:
        """In the subprocess, once run() returned: uvicorn shut itself down
        there, so no port is bound any more."""
        self._bound_port.value = 0

    def on_run_state(self, _name: str, _old: State, new: State) -> None:
        """In the parent, a state hook of the service's runner: a run that has
        ended, however, binds no port. A child killed before its teardown()
        leaves its port behind otherwise, read until the next run starts."""
        if new in _ENDED:
            self._bound_port.value = 0

    def is_healthy(self) -> bool:
        """Whether this service's uvicorn server is ready: ran the app's startup, bound
        its socket and published the bound port.

        Not a probe of the port: uvicorn runs the startup before it binds, so while
        another process holds the port, that process would answer the probe for a
        server that is still starting and about to fail its bind.
        """
        server = self._server
        return server is not None and server.ready


def _check_config(config: ApiConfig) -> None:
    """Refuse a configuration uvicorn cannot run with in a subprocess.

    Raises:
        ConfigError: For a port outside 0-65535, no host, or more than one
            worker: uvicorn's multi-worker mode needs the app as an import
            string, and the service passes the built app object.
    """
    if config.port < 0 or config.port > 65535:
        raise ConfigError(f"Invalid port: {config.port}")
    if not config.host:
        raise ConfigError("Host is required")
    if config.uvicorn.workers != 1:
        raise ConfigError("uvicorn workers must be 1 in subprocess mode")
