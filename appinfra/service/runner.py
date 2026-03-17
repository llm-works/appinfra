"""Service runners - execution and state management."""

from __future__ import annotations

import multiprocessing as mp
import threading
import time
from abc import ABC, abstractmethod
from multiprocessing.synchronize import Event as MPEvent
from typing import Any

from ..log import Logger
from ..log.mp import LogQueueListener
from .base import Service
from .errors import HealthTimeoutError, InvalidTransitionError, RunError, SetupError
from .state import TRANSITIONS, RestartPolicy, State, StateHook


class Runner(ABC):
    """Abstract base for service execution and state management.

    A Runner handles:
    - HOW a service is executed (thread, process, async, scheduled)
    - State tracking (STOPPED -> STARTING -> RUNNING -> STOPPING)
    - Restart policy with backoff
    - State change hooks

    Different runners for different execution models:
    - ThreadRunner: Runs service.execute() in a daemon thread
    - ProcessRunner: Runs ProcessService as subprocess
    - AsyncRunner: Runs service as asyncio task (future)
    - ScheduledRunner: Runs multiple services cooperatively (future)
    """

    def __init__(
        self,
        service: Service,
        policy: RestartPolicy | None = None,
    ) -> None:
        """Initialize runner.

        Args:
            service: The service to run.
            policy: Restart policy. Defaults to RestartPolicy().
        """
        self.service = service
        self.policy = policy or RestartPolicy()
        self._state = State.CREATED
        self._hooks: list[StateHook] = []
        self._retries = 0
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        """Service name."""
        return self.service.name

    @property
    def state(self) -> State:
        """Current state."""
        return self._state

    @property
    def retries(self) -> int:
        """Number of restart attempts since last successful start."""
        return self._retries

    def on_state_change(self, hook: StateHook) -> None:
        """Register a callback for state changes.

        Args:
            hook: Callable(service_name, from_state, to_state).
        """
        self._hooks.append(hook)

    @abstractmethod
    def start(self) -> None:
        """Start the service (STOPPED -> STARTING -> begins execution).

        Non-blocking. After start() returns, execution has begun but
        service may not be healthy yet. Call wait_healthy() to block
        until ready.

        Raises:
            InvalidTransitionError: If not in STOPPED or FAILED state.
            SetupError: If setup fails.
            RunError: If execution fails to start.
        """

    @abstractmethod
    def stop(self, timeout: float = 5.0) -> None:
        """Stop the service (-> STOPPING -> STOPPED).

        Args:
            timeout: Seconds to wait for graceful stop.
        """

    @abstractmethod
    def is_alive(self) -> bool:
        """Check if execution is still active."""

    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if service is healthy."""

    @property
    @abstractmethod
    def exception(self) -> BaseException | None:
        """Exception from execution, if any."""

    def wait_healthy(self, timeout: float = 30.0, interval: float = 0.1) -> None:
        """Block until healthy or timeout.

        Args:
            timeout: Max seconds to wait.
            interval: Seconds between health checks.

        Raises:
            RunError: If execution exits during startup.
            HealthTimeoutError: If timeout reached before healthy.
        """
        start = time.monotonic()

        while time.monotonic() - start < timeout:
            if not self.is_alive():
                self._handle_execution_exit()

            if self.is_healthy():
                self._transition(State.RUNNING)
                self._retries = 0
                return

            time.sleep(interval)

        self._transition(State.FAILED)
        raise HealthTimeoutError(self.name, timeout)

    def _handle_execution_exit(self) -> None:
        """Handle execution exit during health wait."""
        exc = self.exception
        self._transition(State.FAILED)
        if exc:
            raise RunError(self.name, f"exited during startup: {exc}") from exc
        raise RunError(self.name, "exited during startup")

    def check(self) -> bool:
        """Check health and handle failures.

        Call periodically to detect failures and trigger restarts.

        Returns:
            True if a restart was initiated.
        """
        if self._state == State.FAILED:
            # Only restart if not alive (avoid spawning on top of running process)
            if not self.is_alive():
                return self._maybe_restart()
            return False

        if self._state != State.RUNNING:
            return False

        if self.is_alive() and self.is_healthy():
            return False

        self._transition(State.FAILED)
        # Only restart if not alive
        if not self.is_alive():
            return self._maybe_restart()
        return False

    def _maybe_restart(self) -> bool:
        """Attempt restart based on policy."""
        if not self.policy.restart_on_failure:
            return False

        if self._retries >= self.policy.max_retries:
            return False

        backoff = self._calculate_backoff()
        self._retries += 1

        time.sleep(backoff)

        try:
            self.start()
            self.wait_healthy()
            return True
        except Exception:
            return False

    def _calculate_backoff(self) -> float:
        """Calculate backoff delay for current retry."""
        return min(
            self.policy.backoff * (self.policy.backoff_multiplier**self._retries),
            self.policy.max_backoff,
        )

    def _transition(self, to: State) -> None:
        """Transition to a new state."""
        with self._lock:
            from_state = self._state

            if to not in TRANSITIONS.get(from_state, set()):
                raise InvalidTransitionError(self.name, from_state, to)

            self._state = to

        for hook in self._hooks:
            try:
                hook(self.name, from_state, to)
            except Exception:
                pass


class ThreadRunner(Runner):
    """Runs a service in a daemon thread.

    Executes service.execute() in a background thread. Handles setup,
    teardown, and state management.

    Example:
        runner = ThreadRunner(my_service)
        runner.start()
        runner.wait_healthy(timeout=30.0)
        # ... service is running ...
        runner.stop()
    """

    def __init__(
        self,
        service: Service,
        policy: RestartPolicy | None = None,
    ) -> None:
        """Initialize thread runner.

        Args:
            service: The service to run.
            policy: Restart policy.
        """
        super().__init__(service, policy)
        self._thread: threading.Thread | None = None
        self._exception: BaseException | None = None

    def start(self) -> None:
        """Start the service in a background thread."""
        # Setup phase
        try:
            self.service.setup()
        except Exception as e:
            self._transition(State.FAILED)
            if isinstance(e, SetupError):
                raise
            raise SetupError(self.name, str(e)) from e

        self._transition(State.INITD)
        self._transition(State.STARTING)

        # Execute phase
        self._exception = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"svc-{self.name}",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        """Thread target."""
        try:
            self.service.execute()
        except BaseException as e:
            self._exception = e

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the service."""
        if self._state in (State.CREATED, State.STOPPED, State.STOPPING, State.DONE):
            return

        self._transition(State.STOPPING)
        self.service.teardown()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                # Thread didn't exit within timeout - it's a daemon thread
                # so it will be terminated when the process exits
                self.service.lg.warning(
                    f"service thread did not exit within {timeout}s, "
                    "will be terminated on process exit"
                )
                # Stay in STOPPING state since thread is still alive
                return

        self._transition(State.STOPPED)

    def is_alive(self) -> bool:
        """Check if thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def is_healthy(self) -> bool:
        """Check if service is healthy."""
        return self.service.is_healthy()

    @property
    def exception(self) -> BaseException | None:
        """Exception from execute(), if any."""
        return self._exception


class ProcessRunner(Runner):
    """Runs a service in a separate process using multiprocessing.

    Similar to ThreadRunner but uses a subprocess for isolation.
    The service must be picklable for this to work.

    Note:
        Services should use ``_shutdown_event`` (injected by ProcessRunner) to
        detect shutdown signals from the parent process. Do NOT create your own
        multiprocessing.Event - it won't be shared across processes.

    Example:
        from appinfra.service import Service, ProcessRunner

        class MyService(Service):
            def __init__(self, lg: Logger):
                self._lg = lg
                self._shutdown_event: mp.Event | None = None  # Injected

            @property
            def name(self) -> str:
                return "worker"

            def execute(self) -> None:
                while not self._shutdown_event.is_set():
                    self._lg.debug("doing work")
                    do_work()
                    self._shutdown_event.wait(1.0)

            def teardown(self) -> None:
                pass  # _shutdown_event already set by ProcessRunner.stop()

        runner = ProcessRunner(MyService(lg))
        runner.start()
        runner.wait_healthy(timeout=30.0)
        # ... service is running in subprocess ...
        runner.stop()
    """

    def __init__(
        self,
        service: Service,
        policy: RestartPolicy | None = None,
        stop_timeout: float = 5.0,
    ) -> None:
        """Initialize process runner.

        Args:
            service: Service to run (must be picklable).
            policy: Restart policy.
            stop_timeout: Seconds to wait for graceful stop.
        """
        super().__init__(service, policy)
        self.stop_timeout = stop_timeout
        self._process: mp.Process | None = None
        self._shutdown_event: MPEvent | None = None
        self._healthy_event: MPEvent | None = None
        self._error_queue: mp.Queue[BaseException] | None = None
        self._exception: BaseException | None = None
        # Logging infrastructure for subprocess
        self._log_queue: mp.Queue[Any] | None = None
        self._log_listener: LogQueueListener | None = None

    def start(self) -> None:
        """Start the service in a subprocess."""
        self._run_setup()
        self._transition(State.INITD)
        self._transition(State.STARTING)

        try:
            log_config = self._create_log_infrastructure()
            self._create_ipc_primitives()
            self._spawn_process(log_config)
        except Exception:
            self._cleanup_ipc()
            self._transition(State.FAILED)
            raise

    def _run_setup(self) -> None:
        """Run service setup, transition to FAILED on error."""
        try:
            self.service.setup()
        except Exception as e:
            self._transition(State.FAILED)
            if isinstance(e, SetupError):
                raise
            raise SetupError(self.name, str(e)) from e

    def _create_log_infrastructure(self) -> dict[str, Any]:
        """Create logging infrastructure for subprocess."""
        self._log_queue = mp.Queue()
        log_config = self.service.lg.queue_config(self._log_queue)
        self._log_listener = LogQueueListener(self._log_queue, self.service.lg)
        self._log_listener.start()
        return log_config

    def _create_ipc_primitives(self) -> None:
        """Create IPC primitives for subprocess communication."""
        self._shutdown_event = mp.Event()
        self._healthy_event = mp.Event()
        self._error_queue = mp.Queue()

    def _spawn_process(self, log_config: dict[str, Any]) -> None:
        """Spawn the subprocess."""
        self._process = mp.Process(
            target=_process_entry,
            args=(
                self.service,
                self._shutdown_event,
                self._healthy_event,
                self._error_queue,
                log_config,
            ),
            name=f"svc-{self.name}",
            daemon=True,
        )
        self._process.start()

    def stop(self, timeout: float | None = None) -> None:
        """Stop the subprocess."""
        if self._state in (State.CREATED, State.STOPPED, State.STOPPING, State.DONE):
            return

        self._transition(State.STOPPING)
        timeout = timeout or self.stop_timeout

        # Signal shutdown
        if self._shutdown_event is not None:
            self._shutdown_event.set()

        # Wait for graceful exit
        process_stopped = True
        if self._process is not None:
            self._process.join(timeout=timeout)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=2.0)
            if self._process.is_alive():
                self._process.kill()
                self._process.join(timeout=1.0)
            process_stopped = not self._process.is_alive()

        self._cleanup_ipc()
        if process_stopped:
            self._transition(State.STOPPED)
        # If process still alive after kill, stay in STOPPING state

    def _cleanup_ipc(self) -> None:
        """Clean up IPC resources."""
        self._process = None
        self._shutdown_event = None
        self._healthy_event = None
        if self._error_queue is not None:
            try:
                self._error_queue.cancel_join_thread()
                self._error_queue.close()
            except Exception:
                pass
            self._error_queue = None
        # Stop log listener
        if self._log_listener is not None:
            try:
                self._log_listener.stop()
            except Exception:
                pass
            self._log_listener = None
        if self._log_queue is not None:
            try:
                self._log_queue.cancel_join_thread()
                self._log_queue.close()
            except Exception:
                pass
            self._log_queue = None

    def is_alive(self) -> bool:
        """Check if process is running."""
        return self._process is not None and self._process.is_alive()

    def is_healthy(self) -> bool:
        """Check if service reported healthy."""
        if not self.is_alive():
            return False
        if self._healthy_event is None:
            return False
        return self._healthy_event.is_set()

    @property
    def exception(self) -> BaseException | None:
        """Exception from subprocess, if any."""
        # Check for errors from subprocess
        if self._error_queue is not None:
            try:
                while not self._error_queue.empty():
                    self._exception = self._error_queue.get_nowait()
            except Exception:
                pass
        return self._exception

    @property
    def pid(self) -> int | None:
        """Process ID, or None if not running."""
        if self._process is not None and self._process.is_alive():
            return self._process.pid
        return None

    @property
    def exit_code(self) -> int | None:
        """Exit code, or None if still running."""
        if self._process is not None:
            return self._process.exitcode
        return None


def _start_health_poller(
    service: Any, shutdown_event: MPEvent, healthy_event: MPEvent
) -> None:
    """Start background thread to continuously poll service health."""
    import threading

    def poll() -> None:
        while not shutdown_event.is_set():
            if service.is_healthy():
                healthy_event.set()
            else:
                healthy_event.clear()
            time.sleep(0.05)

    threading.Thread(target=poll, daemon=True).start()


def _process_entry(
    service: Any,
    shutdown_event: MPEvent,
    healthy_event: MPEvent,
    error_queue: mp.Queue[BaseException],
    log_config: dict[str, Any],
) -> None:
    """Entry point for service subprocess."""
    try:
        lg = Logger.from_queue_config(log_config, name=f"svc/{service.name}")
        service._lg = lg
        if hasattr(service, "_shutdown_event"):
            service._shutdown_event = shutdown_event

        _start_health_poller(service, shutdown_event, healthy_event)
        service.execute()
    except BaseException as e:
        try:
            error_queue.put(e)
        except Exception:
            pass
    finally:
        try:
            service.teardown()
        except Exception:
            pass
