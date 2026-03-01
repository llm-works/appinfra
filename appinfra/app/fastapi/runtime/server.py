"""Runtime HTTP server instance."""

from __future__ import annotations

import logging
import multiprocessing as mp
from typing import TYPE_CHECKING, Any

from ..config.api import ApiConfig
from ..config.ipc import IPCConfig
from .logging import setup_subprocess_logging
from .subprocess import SubprocessManager

if TYPE_CHECKING:
    from .adapter import FastAPIAdapter

# Module-level logger for main process Server class methods
logger = logging.getLogger("fastapi.server")

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


def _create_subprocess_logger(config: ApiConfig) -> Any:
    """Create appinfra logger for subprocess hot-reload support."""
    from ....log import LoggerFactory
    from ....log.config import LogConfig

    setup_subprocess_logging(
        config.log_file, log_level=config.uvicorn.log_level.upper()
    )
    log_config = LogConfig.from_params(level=config.uvicorn.log_level, location=1)
    return LoggerFactory.create_root(log_config)


def _uvicorn_subprocess_entry(
    adapter: FastAPIAdapter,
    config: ApiConfig,
    request_q: mp.Queue[Any],
    response_q: mp.Queue[Any],
) -> None:
    """
    Entry point for uvicorn subprocess.

    Runs inside subprocess: sets up logging, creates IPC channel,
    builds FastAPI app, and runs uvicorn (blocking).
    """
    import uvicorn

    from ....subprocess import SubprocessContext
    from .ipc import IPCChannel

    lg = _create_subprocess_logger(config)

    # Inject logger into handlers that need it (after unpickling, before build)
    adapter.inject_subprocess_logger(lg)

    with SubprocessContext(
        lg=lg,
        etc_dir=config.etc_dir,
        config_file=config.config_file,
        handle_signals=False,  # uvicorn handles SIGTERM/SIGINT
    ):
        assert config.ipc is not None  # We're in subprocess mode
        ipc_channel = IPCChannel(request_q, response_q, config.ipc)
        # IPC lifecycle (start_polling/stop_polling) is now integrated into
        # the adapter's lifespan, so no separate event registration needed
        app = adapter.build(ipc_channel=ipc_channel)

        uvicorn_kwargs = config.uvicorn.to_uvicorn_kwargs()
        uvicorn_kwargs["log_config"] = _build_uvicorn_log_config(config)
        uvicorn.run(app, host=config.host, port=config.port, **uvicorn_kwargs)


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
        name: str,
        config: ApiConfig,
        adapter: FastAPIAdapter,
        request_q: mp.Queue[Any] | None = None,
        response_q: mp.Queue[Any] | None = None,
    ) -> None:
        """
        Initialize server.

        Args:
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
        self._subprocess_manager: SubprocessManager | None = None
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
        if self._subprocess_manager:
            return self._subprocess_manager.is_alive()
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
        In subprocess mode: starts subprocess and blocks on join().
        """
        if self.is_subprocess_mode:
            proc = self.start_subprocess()
            proc.join()
        else:
            self._run_direct()

    def _validate_subprocess_mode(self) -> None:
        """Validate that subprocess mode can be started."""
        if not self.is_subprocess_mode:
            raise RuntimeError(
                "start_subprocess() requires subprocess mode. "
                "Configure IPC with .subprocess.with_ipc() first."
            )
        if self._subprocess_manager and self._subprocess_manager.is_alive():
            raise RuntimeError("Server subprocess is already running")

    def _create_subprocess_manager(self) -> SubprocessManager:
        """Create subprocess manager with current configuration."""
        assert self._request_q is not None
        assert self._response_q is not None

        if self._config.ipc is None:
            self._config.ipc = IPCConfig()

        return SubprocessManager(
            target=_uvicorn_subprocess_entry,
            args=(self._adapter, self._config, self._request_q, self._response_q),
            shutdown_timeout=5.0,
            auto_restart=self._config.auto_restart,
            restart_delay=self._config.restart_delay,
            max_restarts=self._config.max_restarts,
        )

    def start_subprocess(self) -> mp.Process:
        """
        Start server in subprocess (non-blocking).

        Returns:
            The subprocess Process object

        Raises:
            RuntimeError: If not in subprocess mode or already running
        """
        self._validate_subprocess_mode()
        self._subprocess_manager = self._create_subprocess_manager()
        proc = self._subprocess_manager.start()
        logger.info(
            f"Server '{self._name}' started in subprocess "
            f"(pid={proc.pid}, host={self._config.host}, port={self._config.port})"
        )
        return proc

    def stop(self, timeout: float = 5.0) -> None:
        """
        Gracefully stop the server.

        Uses terminate -> join(timeout) -> kill pattern.

        Args:
            timeout: Seconds to wait for graceful shutdown
        """
        if self._subprocess_manager:
            logger.info(f"Stopping server '{self._name}'...")
            self._subprocess_manager.stop()
            self._subprocess_manager = None
            logger.info(f"Server '{self._name}' stopped")

    def _run_direct(self) -> None:
        """Run uvicorn directly in current process (blocking)."""
        import uvicorn

        app = self._adapter.build()

        logger.info(
            f"Starting server '{self._name}' "
            f"(host={self._config.host}, port={self._config.port})"
        )

        uvicorn.run(
            app,
            host=self._config.host,
            port=self._config.port,
            **self._config.uvicorn.to_uvicorn_kwargs(),
        )
