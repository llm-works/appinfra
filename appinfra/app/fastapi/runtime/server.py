"""Runtime HTTP server instance."""

from __future__ import annotations

import multiprocessing as mp
from typing import TYPE_CHECKING, Any

from ....service import ProcessRunner
from ....service.state import RestartPolicy
from ..config.api import ApiConfig
from ..config.ipc import IPCConfig
from .service import UvicornService

if TYPE_CHECKING:
    from ....log import Logger
    from .adapter import FastAPIAdapter

# Guard imports for optional dependency
try:
    from fastapi import FastAPI

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    FastAPI = Any  # type: ignore[assignment,misc]


def _build_uvicorn_log_config(config: ApiConfig) -> dict[str, Any]:
    """Build uvicorn logging configuration dict."""
    uv = config.uvicorn
    access_level = "info" if uv.access_log else "warning"
    return {
        "version": 1,
        "disable_existing_loggers": True,
        "handlers": {},
        "loggers": {
            "uvicorn": {"level": uv.log_level.upper()},
            "uvicorn.access": {"level": access_level.upper()},
            "uvicorn.error": {"level": uv.log_level.upper()},
        },
    }


class Server:
    """
    Runtime HTTP server instance.

    Supports two modes:
    1. Direct mode: uvicorn.run() in current process (blocking)
    2. Subprocess mode: uvicorn in child process with queue IPC (non-blocking)

    Mode is determined by whether IPC queues are provided during construction.

    Example (direct mode):
        server = ServerBuilder("myapi").with_port(8000).build()
        server.start()  # Blocking

    Example (subprocess mode):
        request_q, response_q = mp.Queue(), mp.Queue()
        server = (ServerBuilder("myapi")
            .subprocess.with_ipc(request_q, response_q).done()
            .build())
        proc = server.start_subprocess()  # Non-blocking
    """

    def __init__(
        self,
        lg: Logger,
        name: str,
        config: ApiConfig,
        adapter: FastAPIAdapter,
        request_q: mp.Queue[Any] | None = None,
        response_q: mp.Queue[Any] | None = None,
    ) -> None:
        """
        Initialize server.

        Args:
            lg: Logger for queue-based subprocess logging
            name: Server name (for logging)
            config: API configuration
            adapter: FastAPI adapter with route/middleware definitions
            request_q: Request queue for IPC (enables subprocess mode)
            response_q: Response queue for IPC (enables subprocess mode)

        Raises:
            ImportError: If FastAPI is not installed
        """
        if not FASTAPI_AVAILABLE:
            raise ImportError(
                "FastAPI is not installed. Install with: pip install appinfra[fastapi]"
            )

        self._name = name
        self._config = config
        self._adapter = adapter
        self._request_q = request_q
        self._response_q = response_q
        self._lg = lg
        self._runner: ProcessRunner | None = None
        self._app: FastAPI | None = None

    @property
    def name(self) -> str:
        """Server name."""
        return self._name

    @property
    def config(self) -> ApiConfig:
        """Server configuration."""
        return self._config

    @property
    def app(self) -> FastAPI:
        """
        Access underlying FastAPI application.

        In subprocess mode, this is the app template (not the running instance).
        The actual running app is inside the subprocess.
        """
        if self._app is None:
            self._app = self._adapter.build()
        return self._app

    @property
    def is_subprocess_mode(self) -> bool:
        """Check if configured for subprocess mode."""
        return self._request_q is not None and self._response_q is not None

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        if self._runner:
            return self._runner.is_alive()
        return False

    @property
    def request_queue(self) -> mp.Queue[Any] | None:
        """Request queue for IPC (main process side)."""
        return self._request_q

    @property
    def response_queue(self) -> mp.Queue[Any] | None:
        """Response queue for IPC (main process side)."""
        return self._response_q

    def start(self) -> None:
        """
        Start server (blocking).

        In direct mode: calls uvicorn.run() directly.
        In subprocess mode: starts subprocess and blocks waiting.
        """
        if self.is_subprocess_mode:
            self.start_subprocess()
            # Block until process exits
            if self._runner:
                while self._runner.is_alive():
                    import time

                    time.sleep(0.5)
        else:
            self._run_direct()

    def _validate_subprocess_mode(self) -> None:
        """Validate that subprocess mode can be started."""
        if not self.is_subprocess_mode:
            raise RuntimeError(
                "start_subprocess() requires subprocess mode. "
                "Configure IPC with .subprocess.with_ipc() first."
            )
        if self._runner and self._runner.is_alive():
            raise RuntimeError("Server subprocess is already running")

    def _create_runner(self) -> ProcessRunner:
        """Create ProcessRunner with UvicornService."""
        if self._config.ipc is None:
            self._config.ipc = IPCConfig()

        service = UvicornService(
            lg=self._lg,
            adapter=self._adapter,
            config=self._config,
            request_q=self._request_q,
            response_q=self._response_q,
        )

        # Map config to RestartPolicy
        policy = RestartPolicy(
            max_retries=self._config.max_restarts,
            backoff=self._config.restart_delay,
            backoff_multiplier=1.0,  # Linear backoff like SubprocessManager
            restart_on_failure=self._config.auto_restart,
        )

        return ProcessRunner(service, policy=policy, stop_timeout=5.0)

    def start_subprocess(self) -> mp.Process:
        """
        Start server in subprocess (non-blocking).

        Returns:
            The subprocess Process object

        Raises:
            RuntimeError: If not in subprocess mode or already running
        """
        self._validate_subprocess_mode()

        self._runner = self._create_runner()
        self._runner.start()
        self._runner.wait_healthy(timeout=30.0)

        # Start monitor for auto-restart if enabled
        if self._config.auto_restart:
            self._runner.start_monitor(interval=1.0)

        self._lg.info(
            "server started in subprocess",
            extra={
                "server": self._name,
                "pid": self._runner.pid,
                "host": self._config.host,
                "port": self._config.port,
            },
        )

        # Return the process for compatibility with existing code
        assert self._runner._process is not None
        return self._runner._process

    def stop(self, timeout: float = 5.0) -> None:
        """
        Gracefully stop the server.

        Uses terminate -> join(timeout) -> kill pattern.

        Args:
            timeout: Seconds to wait for graceful shutdown
        """
        if self._runner:
            self._lg.debug("stopping server...", extra={"server": self._name})
            self._runner.stop(timeout=timeout)
            self._runner = None
            self._lg.info("server stopped", extra={"server": self._name})

    def _run_direct(self) -> None:
        """Run uvicorn directly in current process (blocking)."""
        import uvicorn

        app = self._adapter.build()

        self._lg.info(
            "Starting server",
            extra={
                "server": self._name,
                "host": self._config.host,
                "port": self._config.port,
            },
        )

        uvicorn.run(
            app,
            host=self._config.host,
            port=self._config.port,
            **self._config.uvicorn.to_uvicorn_kwargs(),
        )
