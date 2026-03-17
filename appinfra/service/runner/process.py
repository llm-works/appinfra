"""ProcessRunner - runs services in subprocesses."""

from __future__ import annotations

import multiprocessing as mp
import threading
import time
from multiprocessing.synchronize import Event as MPEvent
from typing import Any

from ...log import Logger
from ...log.mp import LogQueueListener
from ..base import Service
from ..errors import SetupError
from ..state import RestartPolicy, State
from .base import Runner


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
        # Monitor thread for auto-restart
        self._monitor_thread: threading.Thread | None = None
        self._stop_monitor_event: threading.Event = threading.Event()

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

        # Stop monitor thread first
        self.stop_monitor()

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

        if process_stopped:
            self._cleanup_ipc()
            self._transition(State.STOPPED)
        # If process still alive after kill, stay in STOPPING state
        # and preserve IPC handles so supervisor can retry/monitor

    def start_monitor(self, interval: float = 1.0) -> None:
        """Start background monitor thread for auto-restart.

        The monitor periodically calls check() to detect failures and
        trigger restarts according to the restart policy.

        Args:
            interval: Seconds between health checks (default: 1.0)
        """
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            return  # Already monitoring

        self._stop_monitor_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval,),
            daemon=True,
            name=f"monitor-{self.name}",
        )
        self._monitor_thread.start()

    def stop_monitor(self, timeout: float = 2.0) -> None:
        """Stop the monitor thread.

        Args:
            timeout: Seconds to wait for thread to stop.
        """
        self._stop_monitor_event.set()
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=timeout)
        self._monitor_thread = None

    def _monitor_loop(self, interval: float) -> None:
        """Monitor loop that checks health and triggers restarts."""
        while not self._stop_monitor_event.is_set():
            if self._state in (State.STOPPED, State.DONE):
                break

            # Check for clean exit (exit_code == 0) - don't restart
            if not self.is_alive() and self._process is not None:
                exit_code = self._process.exitcode
                if exit_code == 0:
                    # Clean shutdown (e.g., SIGINT/SIGTERM) - transition to DONE
                    self._transition(State.DONE)
                    break

            # check() handles failure detection and restart
            self.check()

            # Wait for interval or stop signal
            self._stop_monitor_event.wait(timeout=interval)

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
        """Exception from subprocess, if any.

        Returns the first exception encountered (root cause).
        """
        # Drain queue using exception-based loop (Queue.empty() is unreliable)
        if self._error_queue is not None:
            from queue import Empty

            try:
                while True:
                    try:
                        exc = self._error_queue.get_nowait()
                        if self._exception is None:
                            self._exception = exc
                    except Empty:
                        break
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

    @property
    def process(self) -> mp.Process | None:
        """Underlying process, or None if not started."""
        return self._process


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
    """Entry point for service subprocess.

    Injects runtime dependencies into the service:
    - ``_lg``: Logger configured to forward to parent via queue
    - ``_shutdown_event``: Event signaled when parent requests shutdown
    """
    try:
        lg = Logger.from_queue_config(log_config, name=f"svc/{service.name}")
        # Inject runtime dependencies (services must have these attributes)
        if hasattr(service, "_lg"):
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
