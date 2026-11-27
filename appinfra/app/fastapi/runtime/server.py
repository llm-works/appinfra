# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runtime HTTP server instance."""

from __future__ import annotations

import multiprocessing as mp
import sys
import weakref
from threading import Event
from typing import TYPE_CHECKING, Any

from ....runtime import TaskProcess
from ....service import RunError, Runner, State
from ....service import Runtime as ServiceRuntime
from ....service.state import RestartPolicy
from ..config.api import ApiConfig
from ..config.ipc import IPCConfig
from .adapter import LifecycleCallbackDefinition
from .service import UvicornService

# Seconds start_subprocess() waits for the server to come up
START_TIMEOUT = 30.0

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
    2. Subprocess mode: uvicorn in a process of its own with queue IPC
       (non-blocking), run as an isolated service of a service Runtime: the
       runtime restarts it under its restart policy and escalates its stop.

    Mode is determined by whether IPC queues are provided during construction.

    Example (direct mode):
        server = ServerBuilder("myapi").with_port(8000).build()
        server.start()  # Blocking

    Example (subprocess mode):
        server = ServerBuilder("myapi").subprocess.with_ipc().done().build()
        server.start_subprocess()  # Non-blocking
        request_q = server.request_queue
    """

    def __init__(
        self,
        lg: Logger,
        name: str,
        config: ApiConfig,
        adapter: FastAPIAdapter,
        request_q: mp.Queue[Any] | None = None,
        response_q: mp.Queue[Any] | None = None,
        runtime: ServiceRuntime | None = None,
    ) -> None:
        """
        Initialize server.

        Args:
            lg: Logger for queue-based subprocess logging
            name: Server name (for logging)
            config: API configuration
            adapter: FastAPI adapter with route/middleware definitions
            request_q: Request queue for IPC (enables subprocess mode), made
                from appinfra.runtime.process_context()
            response_q: Response queue for IPC (enables subprocess mode), made
                from the same context
            runtime: A started service Runtime to run the subprocess in, the
                application's; None: start_subprocess() starts one of its
                own, which stop() stops

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
        self._runtime = runtime
        # The runtime start_subprocess() started, when none was given
        self._own_runtime: ServiceRuntime | None = None
        self._runner: Runner | None = None
        self._service: UvicornService | None = None
        # Set by stop(): a start still spawning stops the runner it gets
        self._stop_asked = False
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
    def port(self) -> int:
        """The port the server listens on.

        In subprocess mode, the port the subprocess bound, once start_subprocess() has
        returned: with port 0 in the config, the one the OS picked. Otherwise the
        configured port.
        """
        if self._service is not None and self._service.bound_port:
            return self._service.bound_port
        return self._config.port

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
    def process(self) -> TaskProcess | None:
        """The subprocess of the current run, or None while none runs (before
        start_subprocess(), between a crash and its restart, after stop()).
        A restart runs a new one: read it when needed. Held on to, it still
        gives the ended child's detail, its exit code included."""
        runner = self._runner
        task = None if runner is None else runner.task
        return None if task is None else task.process

    @property
    def pid(self) -> int | None:
        """The pid of the current run's subprocess, or None while none runs."""
        process = self.process
        return None if process is None else process.detail().pid

    @property
    def is_running(self) -> bool:
        """True while the current run's subprocess is alive."""
        process = self.process
        return process is not None and process.detail().alive

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
        In subprocess mode: starts the subprocess and blocks until it has
        ended for good: stopped, ended cleanly, or failed with no restart
        left.
        """
        if self.is_subprocess_mode:
            self.start_subprocess()
            runner = self._runner
            assert runner is not None
            try:
                _wait_settled(runner)
            finally:  # Ctrl-C included; a runtime of its own stops too
                self.stop()
        else:
            self._run_direct()

    def _validate_subprocess_mode(self) -> None:
        """Validate that subprocess mode can be started."""
        if not self.is_subprocess_mode:
            raise RuntimeError(
                "start_subprocess() requires subprocess mode. "
                "Configure IPC with .subprocess.with_ipc() first."
            )
        if self._runner is not None and not _settled(self._runner):
            raise RuntimeError("Server subprocess is already running")

    def _start_runtime(self) -> ServiceRuntime:
        """The runtime to run the subprocess in: the one given, else one of
        the server's own, started on first use."""
        if self._runtime is not None:
            return self._runtime
        if self._own_runtime is None:
            runtime = ServiceRuntime(self._lg, name=f"{self._name}-server")
            runtime.start()
            self._own_runtime = runtime
        return self._own_runtime

    def _make_service(self, runtime: ServiceRuntime) -> UvicornService:
        """A UvicornService for a new start, its shared port made from the
        context *runtime*'s children start in."""
        if self._config.ipc is None:
            self._config.ipc = IPCConfig()
        return UvicornService(
            lg=self._lg,
            server_name=self._name,
            adapter=self._adapter,
            config=self._config,
            context=runtime.process_context,
            request_q=self._request_q,
            response_q=self._response_q,
        )

    def _restart_policy(self) -> RestartPolicy:
        """The configured restarts: a fixed delay between attempts."""
        return RestartPolicy(
            # ApiConfig documents 0 as unlimited; RestartPolicy's 0 means no restarts
            max_retries=self._config.max_restarts or sys.maxsize,
            backoff=self._config.restart_delay,
            backoff_multiplier=1.0,
            restart_on_failure=self._config.auto_restart,
        )

    def start_subprocess(self) -> None:
        """
        Start the server in its subprocess (non-blocking): returns once it
        serves. The runtime restarts it after a crash, as configured; read
        ``port``, ``pid`` and ``process`` for the current run.

        Raises:
            RuntimeError: If not in subprocess mode or already running
            ConfigError: If the configuration cannot run in a subprocess
            SetupError, HealthTimeoutError: If it does not come up; the
                server is stopped then
            RunError: If stop() was called while it started
        """
        self._validate_subprocess_mode()
        self._stop_asked = False
        runtime = self._start_runtime()
        try:
            service = self._make_service(runtime)  # ConfigError: a bad config
            self._service = service
            self._runner = runtime.spawn(service, self._restart_policy(), isolate=True)
            # Its first run's transitions come after this: the child takes far
            # longer to start than spawn() to return
            self._runner.on_state_change(service.on_run_state)
            # Set before stop() reads _runner, read after it is set: a stop()
            # from another thread during spawn() is seen on one side or both
            if self._stop_asked:
                raise RunError(self._name, "stopped while starting")
            runtime.ready(self._runner, timeout=START_TIMEOUT)
        except BaseException:  # Ctrl-C included: nothing is left running
            self.stop()
            raise
        self._lg.info(
            "server started in subprocess",
            extra={
                "server": self._name,
                "pid": self.pid,
                "host": self._config.host,
                "port": self.port,
            },
        )

    def stop(self, timeout: float = 5.0) -> None:
        """
        Gracefully stop the server.

        Stops the subprocess and waits up to ``timeout`` for it to exit; one
        still running then is terminated, and killed if it outlives that,
        the wait going on through both. A runtime of the server's own is
        stopped too; a given one keeps running.

        Args:
            timeout: Seconds to wait for graceful shutdown

        Raises:
            ValueError: If *timeout* is negative, before anything is stopped.
            TimeoutError: If the subprocess outlived its kill. In a given
                runtime the server keeps it, and a later stop() tries again.
        """
        if timeout < 0:
            raise ValueError(f"timeout must not be negative, got {timeout}")
        self._stop_asked = True
        runtime = self._own_runtime if self._own_runtime is not None else self._runtime
        runner = self._runner if self._runner is not None else self._spawned(runtime)
        self._runner = None
        own, self._own_runtime = self._own_runtime, None
        try:
            # No runtime: a stop() during the start stopped the server's own,
            # and the runner with it
            if runner is not None and runtime is not None:
                self._stop_runner(runtime, runner, timeout, keep=own is None)
        finally:
            if own is not None:  # it takes a runner it could not stop with it
                own.stop(timeout=timeout)

    def _stop_runner(
        self, runtime: ServiceRuntime, runner: Runner, timeout: float, keep: bool
    ) -> None:
        """Stop *runner* in *runtime*; if that fails and *keep* is set, hold on
        to it, so that a later stop() tries again."""
        self._lg.debug("stopping server...", extra={"server": self._name})
        try:
            runtime.stop_service(runner, timeout=timeout)
        except BaseException:
            if keep:
                self._runner = runner
            raise
        self._lg.info("server stopped", extra={"server": self._name})

    def _spawned(self, runtime: ServiceRuntime | None) -> Runner | None:
        """The runner of a spawn() that did not return: an interrupt ended its
        wait for the reply after *runtime* took the service. None when the
        runtime holds no runner of this server's service."""
        service = self._service
        if runtime is None or service is None:
            return None
        runner = runtime.services.get(service.name)
        return runner if runner is not None and runner.service is service else None

    def _run_direct(self) -> None:
        """Run uvicorn directly in current process (blocking)."""
        import uvicorn

        self._adapter.add_startup_callback(self._make_server_started_callback())
        app = self._adapter.build()

        self._lg.debug(
            "starting server...",
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

    def _make_server_started_callback(self) -> LifecycleCallbackDefinition:
        """Create callback to log when server is actually listening."""
        lg = self._lg
        name = self._name
        host = self._config.host
        port = self._config.port

        async def log_server_started(_app: Any) -> None:
            lg.info(
                "server started",
                extra={"server": name, "host": host, "port": port},
            )

        return LifecycleCallbackDefinition(log_server_started, "_server_started")


def _settled(runner: Runner) -> bool:
    """True once *runner* will not run again: stopped, ended cleanly, or
    failed with no restart left."""
    state = runner.state
    if state in (State.STOPPED, State.DONE):
        return True
    return state == State.FAILED and not runner.can_restart


def _wait_settled(runner: Runner) -> None:
    """Block until *runner* has settled for good (see _settled()). The hook
    sees every later transition; the check after it covers one made before
    it was registered. It holds the runner weakly: the runner keeps its hooks,
    and a strong one would keep both in a cycle."""
    settled = Event()
    ref = weakref.ref(runner)

    def on_change(_name: str, _old: State, _new: State) -> None:
        current = ref()
        if current is not None and _settled(current):
            settled.set()

    runner.on_state_change(on_change)
    if _settled(runner):
        return
    settled.wait()
