"""Uvicorn service for ProcessRunner integration."""

from __future__ import annotations

import multiprocessing as mp
import socket
from multiprocessing.synchronize import Event as MPEvent
from typing import TYPE_CHECKING, Any

from ....service import Service

if TYPE_CHECKING:
    from ....log import Logger
    from ..config.api import ApiConfig
    from .adapter import FastAPIAdapter


class UvicornService(Service):
    """Service wrapper for running uvicorn in a subprocess.

    Integrates with ProcessRunner to provide:
    - Subprocess isolation for uvicorn
    - Health checking via TCP connection test
    - Proper logging forwarding to parent process

    The service setup() validates configuration in the parent process.
    The execute() method runs in the subprocess and starts uvicorn.

    Example:
        service = UvicornService(lg, adapter, config, request_q, response_q)
        runner = ProcessRunner(service, policy=RestartPolicy(max_retries=5))
        runner.start()
        runner.wait_healthy(timeout=30.0)
        runner.start_monitor()  # Enable auto-restart
    """

    def __init__(
        self,
        lg: Logger,
        adapter: FastAPIAdapter,
        config: ApiConfig,
        request_q: mp.Queue[Any] | None = None,
        response_q: mp.Queue[Any] | None = None,
    ) -> None:
        """Initialize uvicorn service.

        Args:
            lg: Logger instance (for parent process, subprocess gets its own)
            adapter: FastAPI adapter with route definitions
            config: API configuration
            request_q: IPC request queue (optional, for subprocess mode)
            response_q: IPC response queue (optional, for subprocess mode)
        """
        self._lg = lg
        self._adapter = adapter
        self._config = config
        self._request_q = request_q
        self._response_q = response_q
        # Injected by ProcessRunner in subprocess
        self._shutdown_event: MPEvent | None = None

    @property
    def name(self) -> str:
        """Service name."""
        return f"uvicorn-{self._config.port}"

    def setup(self) -> None:
        """Validate configuration (runs in parent process)."""
        from ..errors import ConfigError

        if self._config.port <= 0 or self._config.port > 65535:
            raise ConfigError(f"Invalid port: {self._config.port}")
        if not self._config.host:
            raise ConfigError("Host is required")

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

    def execute(self) -> None:
        """Run uvicorn (runs in subprocess)."""
        import uvicorn

        from ....subprocess import SubprocessContext
        from .server import _build_uvicorn_log_config

        self._setup_subprocess_logging()

        with SubprocessContext(
            lg=self._lg,
            config_files=self._get_config_files_for_watcher(),
            handle_signals=False,  # uvicorn handles SIGTERM/SIGINT
        ):
            ipc_channel = self._create_ipc_channel()
            app = self._adapter.build(ipc_channel=ipc_channel)

            uvicorn_kwargs = self._config.uvicorn.to_uvicorn_kwargs()
            uvicorn_kwargs["log_config"] = _build_uvicorn_log_config(self._config)
            uvicorn.run(
                app,
                host=self._config.host,
                port=self._config.port,
                **uvicorn_kwargs,
            )

    def teardown(self) -> None:
        """Cleanup - uvicorn handles its own shutdown via SIGTERM."""
        pass

    def is_healthy(self) -> bool:
        """Check if uvicorn is accepting connections."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.settimeout(0.5)
                result = sock.connect_ex((self._config.host, self._config.port))
                return result == 0
            finally:
                sock.close()
        except Exception:
            return False
