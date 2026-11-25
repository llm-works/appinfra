# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""ProcessRunner - runs services in subprocesses."""

from __future__ import annotations

import contextlib
import multiprocessing as mp
import sys
import threading
import time
from multiprocessing.connection import Connection
from multiprocessing.context import BaseContext
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event as MPEvent
from typing import Any

from ...log import Logger
from ...log.mp import LogQueueListener
from ..base import Service
from ..state import RestartPolicy, State
from ..stop import StopToken
from .drive import check_drivable, drive
from .runner import Runner


class ProcessRunner(Runner):
    """Runs a service in a separate process using multiprocessing.

    Similar to ThreadRunner but uses a subprocess for isolation.
    The service must be picklable for this to work. An AsyncService runs on a
    LoopHost instead.

    Note:
        In the subprocess, ``self.stopping`` is set when the parent stops the
        service, as under any runner. Scheduled services need nothing: the
        runner ends their loop.

    Example:
        from appinfra.service import ProcessRunner, Service

        class MyService(Service):
            def __init__(self, lg: Logger):
                self._lg = lg

            @property
            def name(self) -> str:
                return "worker"

            def run(self) -> None:
                while not self.stopping.is_set():
                    self._lg.debug("doing work")
                    do_work()
                    self.stopping.wait(1.0)

            def teardown(self) -> None:
                pass  # Runs in the subprocess after run() returns

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
        start_method: str | None = None,
    ) -> None:
        """Initialize process runner.

        Args:
            service: Service to run (must be picklable).
            policy: Restart policy.
            stop_timeout: Seconds to wait for graceful stop.
            start_method: multiprocessing start method ("fork", "spawn",
                "forkserver") for the service process and its queues and events;
                None uses multiprocessing's default. Under fork, a restart forks
                from the monitor thread, which Python 3.12+ warns may deadlock the
                child; spawn or forkserver avoids it.

        Raises:
            TypeError: If *service* is an AsyncService.
        """
        super().__init__(service, policy)
        check_drivable(self.service)
        self.stop_timeout = stop_timeout
        self._start_method = start_method
        self._process: BaseProcess | None = None
        # Read by the subprocess's health poller, which only checks it: nothing
        # waits on it, so set() never waits for a waiter (see _stop_writer)
        self._shutdown_event: MPEvent | None = None
        # The stop signal itself. The subprocess blocks on its read end and stops
        # the service's token on a message or EOF. Not an mp.Event: Event.set()
        # waits until every process waiting on the event has woken, so a
        # subprocess that died while waiting would block set() for good.
        self._stop_reader: Connection | None = None
        self._stop_writer: Connection | None = None
        self._healthy_event: MPEvent | None = None
        self._error_queue: mp.Queue[BaseException] | None = None
        self._exception: BaseException | None = None
        # Logging infrastructure for subprocess
        self._log_queue: mp.Queue[Any] | None = None
        self._log_listener: LogQueueListener | None = None
        # Monitor thread for auto-restart
        self._monitor_thread: threading.Thread | None = None
        self._stop_monitor_event: threading.Event = threading.Event()

    def _launch(self) -> None:
        """Spawn the service's subprocess."""
        try:
            # One context for the process and every queue and event it uses:
            # multiprocessing refuses a lock from another context in the child
            ctx = mp.get_context(self._start_method)
            log_config, listener = self._create_log_infrastructure(ctx)
            self._create_ipc_primitives(ctx)
            self._spawn_process(ctx, log_config)
            # After the fork, so its thread is not running while the child is
            # forked; the queue holds any records the child sends before then
            listener.start()
        except Exception:
            self._reap_spawned()
            # As in stop(): keep the handles of a child that survived, so a
            # later stop() can retry
            if not self.is_alive():
                self._cleanup_ipc()
            self._transition(State.FAILED)
            raise

    def _reap_spawned(self) -> None:
        """End a child that start() forked before failing, so none is left running."""
        proc = self._process
        if proc is None or not proc.is_alive():
            return
        proc.terminate()
        proc.join(timeout=2.0)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=1.0)

    def _create_log_infrastructure(
        self, ctx: BaseContext
    ) -> tuple[dict[str, Any], LogQueueListener]:
        """Create the subprocess log queue and its listener, not yet started."""
        self._log_queue = ctx.Queue()
        log_config = self.service.lg.queue_config(self._log_queue)
        self._log_listener = LogQueueListener(self._log_queue, self.service.lg)
        return log_config, self._log_listener

    def _create_ipc_primitives(self, ctx: BaseContext) -> None:
        """Create IPC primitives for subprocess communication."""
        self._shutdown_event = ctx.Event()
        self._stop_reader, self._stop_writer = ctx.Pipe(duplex=False)
        self._healthy_event = ctx.Event()
        self._error_queue = ctx.Queue()

    def _inherited_writer(self, ctx: BaseContext) -> Connection | None:
        """The stop pipe's writer as the child inherits it: a forked child holds
        a copy, which it must close for the pipe to reach EOF once the parent's
        copy closes; a spawned child has none."""
        return self._stop_writer if ctx.get_start_method() == "fork" else None

    def _spawn_process(self, ctx: BaseContext, log_config: dict[str, Any]) -> None:
        """Spawn the subprocess."""
        # Temporarily nullify logger to make service picklable on macOS.
        # macOS uses spawn (not fork), requiring all subprocess args to be
        # picklable. Loggers can't be pickled, but the subprocess creates
        # its own from log_config anyway.
        saved_lg = getattr(self.service, "_lg", None)
        if saved_lg is not None:
            setattr(self.service, "_lg", None)

        try:
            # typeshed declares Process on each concrete context, not BaseContext
            self._process = ctx.Process(  # type: ignore[attr-defined]
                target=_process_entry,
                args=(
                    self.service,
                    self._shutdown_event,
                    self._stop_reader,
                    self._inherited_writer(ctx),
                    self._healthy_event,
                    self._error_queue,
                    log_config,
                ),
                name=f"svc-{self.name}",
                daemon=True,
            )
            self._process.start()
        finally:
            # Restore logger in parent process
            if saved_lg is not None:
                setattr(self.service, "_lg", saved_lg)

    def stop(self, timeout: float | None = None) -> None:
        """Stop the subprocess. A start() in progress on another thread is
        waited for first; that wait and the wait for the child to exit
        gracefully take at most *timeout* (stop_timeout if None) together.

        Raises:
            RuntimeError: If called from one of this runner's state hooks.
        """
        self._refuse_from_hook("stop")
        left = self._start_ended(self.stop_timeout if timeout is None else timeout)
        if left is None:
            return
        if self._state in (State.CREATED, State.STOPPED, State.STOPPING, State.DONE):
            return

        # Stop monitor thread first
        self.stop_monitor()
        self._stop_process(left)

    def _stop_for_restart(self) -> None:
        """Stop the failed process only: a restart runs on the monitor thread,
        which keeps watching the restarted process."""
        self._stop_process(None)

    def _stop_process(self, timeout: float | None) -> None:
        """Signal the subprocess to stop, escalating to terminate and kill."""
        self._transition(State.STOPPING)
        if timeout is None:
            timeout = self.stop_timeout

        # Signal shutdown: the parent's token, and through the pipe the
        # subprocess's own. A write never waits for the reader, so a subprocess
        # that has died cannot block it.
        self.service.stopping.stop()
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        if self._stop_writer is not None:
            with contextlib.suppress(OSError):
                self._stop_writer.send_bytes(b"")

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

    @property
    def monitoring(self) -> bool:
        """True while the start_monitor() thread is running."""
        thread = self._monitor_thread
        return thread is not None and thread.is_alive()

    def stop_monitor(self, timeout: float = 2.0) -> None:
        """Stop the monitor thread.

        Args:
            timeout: Seconds to wait for thread to stop.
        """
        self._stop_monitor_event.set()
        thread = self._monitor_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
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
                    # Clean shutdown (e.g., SIGINT/SIGTERM)
                    self._end_clean()
                    break

            # check() handles failure detection and restart
            restarted = self.check()
            # A dead process the policy won't restart again: nothing left to watch. Still
            # RUNNING means it died after check() looked; the next pass records how it ended.
            if (
                not restarted
                and not self.is_alive()
                and not self.restart_pending
                and self._state != State.RUNNING
            ):
                break

            # Wait for interval or stop signal
            self._stop_monitor_event.wait(timeout=interval)

    def _end_clean(self) -> None:
        """Move a process that exited cleanly to DONE. DONE is final, so no
        stop() follows to release the log listener and queues: release them
        here, keeping the process handle for exit_code."""
        process = self._process
        self._cleanup_ipc()
        self._process = process
        self._transition(State.DONE)

    def _cleanup_ipc(self) -> None:
        """Clean up IPC resources."""
        self._process = None
        self._shutdown_event = None
        for end in (self._stop_reader, self._stop_writer):
            if end is not None:
                with contextlib.suppress(OSError):
                    end.close()
        self._stop_reader = self._stop_writer = None
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
            with contextlib.suppress(Exception):
                self._log_listener.stop()
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
    def process(self) -> BaseProcess | None:
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


def _bridge_stop(
    token: StopToken, stop_reader: Connection, inherited_writer: Connection | None
) -> None:
    """Stop *token*, the service's own, from a daemon thread once the parent
    writes to *stop_reader*'s pipe or the pipe reaches EOF. The service's token,
    not a new one: setup() ran in the parent and may have kept it or derived
    from it, and the subprocess has those tokens as copies of it.

    EOF comes only once every copy of the writer is closed. A forked child
    closes its own copy, *inherited_writer*, here. Children forked later by the
    same parent hold copies too, so when the parent dies without closing its
    writer, EOF is certain only for a single forked child."""
    if inherited_writer is not None:
        with contextlib.suppress(OSError):
            inherited_writer.close()

    def bridge() -> None:
        with contextlib.suppress(EOFError, OSError):
            stop_reader.recv_bytes()
        token.stop()

    threading.Thread(target=bridge, name="stopping", daemon=True).start()


def _process_entry(
    service: Any,
    shutdown_event: MPEvent,
    stop_reader: Connection,
    inherited_writer: Connection | None,
    healthy_event: MPEvent,
    error_queue: mp.Queue[BaseException],
    log_config: dict[str, Any],
) -> None:
    """Entry point for service subprocess.

    Gives the service what it runs with here:
    - ``_lg``: Logger configured to forward to parent via queue
    - ``stopping``: its own token, stopped here when the parent requests shutdown

    The process exits non-zero when the service failed, so the parent's monitor
    restarts it; exit code 0 means a clean shutdown.
    """
    exit_code = 0
    try:
        lg = Logger.from_queue_config(log_config, name=f"svc/{service.name}")
        if hasattr(service, "_lg"):
            service._lg = lg
        _bridge_stop(service.stopping, stop_reader, inherited_writer)

        _start_health_poller(service, shutdown_event, healthy_event)
        drive(service, service.stopping)
    except BaseException as e:
        exit_code = _exit_code(e)
        with contextlib.suppress(Exception):
            error_queue.put(e)
    finally:
        # The run has ended: work derived from its token ends with it
        with contextlib.suppress(Exception):
            service.stopping.stop()
        with contextlib.suppress(Exception):
            service.teardown()
    if exit_code:
        sys.exit(exit_code)


def _exit_code(exc: BaseException) -> int:
    """Exit code for a service that ended with *exc*.

    KeyboardInterrupt (Ctrl-C reaching the process group) is a shutdown and
    SystemExit keeps its own code; any other exception is a failure.
    """
    if isinstance(exc, KeyboardInterrupt):
        return 0
    if isinstance(exc, SystemExit):
        if exc.code is None:
            return 0
        return exc.code if isinstance(exc.code, int) else 1
    return 1
