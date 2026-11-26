# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""ProcessRunner: the FastAPI server's supervisor of its uvicorn process.

It runs one service in a process of its own, started with the server's start
method so the IPC queues the caller made work in the child; waits until the
service reports healthy; restarts it per the restart policy from a monitor
thread; and stops it, escalating to terminate and kill. start(), stop(),
wait_healthy() and check() may be called from any thread, under a lock.
"""

from __future__ import annotations

import contextlib
import functools
import multiprocessing as mp
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.context import BaseContext
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event as MPEvent
from queue import Empty
from types import FrameType
from typing import Any

from ....log import Logger
from ....log.mp import LogQueueListener
from ....runtime import StoppedError, StopToken
from ....service import (
    AsyncService,
    HealthTimeoutError,
    InvalidTransitionError,
    RestartPolicy,
    RunError,
    Service,
    SetupError,
    State,
)
from ....service.state import TRANSITIONS

# The policy of every runner given none; RestartPolicy is frozen, so one serves all
_DEFAULT_POLICY = RestartPolicy()


@dataclass(frozen=True, slots=True)
class _Monitor:
    """A monitor thread and the event that stops it: its own, so stopping one
    monitor never reaches another started since."""

    thread: threading.Thread
    stopped: threading.Event


class _RunErrors:
    """One run's errors: the queue its child reports on, and the first
    exception read from it (the root cause). Each run has its own, so one
    run's error is never reported as another's, and a waiter holding a run's
    record still reads that run's cause once a later run has replaced it.

    Reads and the close are serialized: the close drains the queue into the
    record first, so a cause queued before cleanup is kept.

    The queue of a child ended by a signal is never read: one killed while
    its feeder was writing leaves a partial frame, and a read of it waits for
    the rest, which never comes (this process holds a writer too, so no EOF).
    Its cause, if it had written one, is lost. A child that exited on its own
    flushed its queue at exit: its frames are whole.
    """

    __slots__ = ("queue", "process", "first", "_lock")

    def __init__(self) -> None:
        self.queue: mp.Queue[BaseException] | None = None  # once launched
        self.process: BaseProcess | None = None  # the child writing to it
        self.first: BaseException | None = None
        self._lock = threading.Lock()

    def drain(self) -> BaseException | None:
        """Read what the child reported so far; the first exception, if any."""
        with self._lock:
            self._drain_locked()
            return self.first

    def close(self) -> None:
        """Keep what the child reported, then close the queue."""
        with self._lock:
            self._drain_locked()
            errors, self.queue = self.queue, None
        if errors is not None:
            with contextlib.suppress(Exception):
                errors.cancel_join_thread()
                errors.close()

    def _drain_locked(self) -> None:
        errors = self.queue
        if errors is None or self._killed():
            return
        # Drained until empty: Queue.empty() is unreliable
        with contextlib.suppress(Exception):
            while True:
                try:
                    exc = errors.get_nowait()
                except Empty:
                    break
                if self.first is None:
                    self.first = exc

    def _killed(self) -> bool:
        """True once the child has ended by a signal (a negative exit code)."""
        exitcode = self.process.exitcode if self.process is not None else None
        return exitcode is not None and exitcode < 0


class ProcessRunner:
    """Runs a service in a process of its own using multiprocessing.

    The service must be picklable. Its setup() runs here, its run() and
    teardown() in the subprocess, where ``self.stopping`` is set when this
    process stops the service.
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
            policy: Restart policy. Defaults to RestartPolicy().
            stop_timeout: Seconds to wait for graceful stop.
            start_method: multiprocessing start method ("fork", "spawn",
                "forkserver") for the service process and its queues and events;
                None uses multiprocessing's default. Under fork, a restart forks
                from the monitor thread, which Python 3.12+ warns may deadlock the
                child; spawn or forkserver avoids it.

        Raises:
            TypeError: If *service* is an AsyncService: the subprocess calls
                run() on no event loop.
        """
        if isinstance(service, AsyncService):
            raise TypeError(
                f"async service '{service.name}' cannot run in a process of "
                "its own: an async service runs on an event loop"
            )
        self.service = service
        # Before setup(), which may already derive from it
        self.service.stopping = StopToken()
        self.policy = policy or _DEFAULT_POLICY
        self.stop_timeout = stop_timeout
        self._start_method = start_method
        self._state = State.CREATED
        self._retries = 0
        self._restarting = False
        self._lock = threading.Lock()
        # The thread running start(), from its state check until it returns
        # (_release_start()); a stop() from another thread waits on _start_done.
        # Created only while such a stop() waits, so an idle runner holds no
        # condition; it shares _lock, which guards both fields.
        self._start_thread: int | None = None
        self._start_done: threading.Condition | None = None
        # Counts the runs start() has claimed, under _lock: a wait_healthy()
        # acts only on the run it began waiting for, not one started since
        self._run = 0
        # The thread stopping the subprocess, under _lock: one stop at a time
        self._stopper: int | None = None
        self._init_handles()
        # Monitor thread for auto-restart
        self._monitor: _Monitor | None = None  # under _lock

    def _init_handles(self) -> None:
        """The process and the IPC and logging handles of a run: none yet."""
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
        self._errors = _RunErrors()  # the current run's; replaced per claim
        # Logging infrastructure for subprocess
        self._log_queue: mp.Queue[Any] | None = None
        self._log_listener: LogQueueListener | None = None

    @property
    def name(self) -> str:
        """Service name."""
        return self.service.name

    @property
    def state(self) -> State:
        """Current state."""
        return self._state

    @property
    def can_restart(self) -> bool:
        """True if the restart policy still allows another restart attempt."""
        return self._retry_left()

    def _retry_left(self) -> bool:
        """can_restart, for a caller holding the lock."""
        return (
            self.policy.restart_on_failure and self._retries < self.policy.max_retries
        )

    @property
    def restart_pending(self) -> bool:
        """True while a restart attempt runs or the policy allows another one.

        The attempt in progress counts: _maybe_restart() counts it before making
        it, so can_restart is already False during the last allowed attempt.
        """
        return self._restarting or self.can_restart

    # -- start ------------------------------------------------------------------------

    def start(self) -> None:
        """Start the service (STOPPED -> STARTING -> begins execution).

        Non-blocking. After start() returns, execution has begun but
        service may not be healthy yet. Call wait_healthy() to block
        until ready. A stop() from another thread waits for start() to
        return.

        Raises:
            InvalidTransitionError: If not in CREATED, STOPPED or FAILED state,
                or another start() is in progress.
            SetupError: If setup fails.
            RunError: If execution fails to start.
        """
        self._start(self._claim_start)

    def _start(self, claim: Callable[[], int]) -> None:
        """Set up and launch a run, once *claim* has claimed the start.

        A stop() that ended the run meanwhile, with no time left to wait for
        this start, has its effect once the child is spawned: it is stopped
        here, through its stop pipe, so it tears down as on any stop. The
        child is spawned first because teardown() runs in it.

        Whether a stop() ended the run is read under the lock that releases
        the start: a stop() before that is seen here, one after it finds no
        start in progress and stops the child itself.

        Raises:
            RunError: If a stop() ended the run during the start.
        """
        run = claim()
        try:
            if self._process is not None:
                # A FAILED run's handles, its child dead (the claim refuses a
                # live one): released before this run creates its own
                self._cleanup_ipc()
            self._run_setup()
            self._transition(State.INITD)
            self._transition(State.STARTING)
            self._launch()
        except BaseException:
            self._release_start(run)
            raise
        if self._release_start(run):
            self._stop_process(None)
            raise RunError(self.name, "stopped during startup")

    def _launch(self) -> None:
        """Spawn the service's subprocess.

        An interrupt (KeyboardInterrupt, SystemExit) gets the cleanup a failure
        gets, and reaches the caller unchanged.

        Raises:
            RunError: If the launch fails, caused by what failed.
        """
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
        except BaseException as e:
            self._reap_spawned()
            # As in stop(): keep the handles of a child that survived, so a
            # later stop() can retry
            if not self.is_alive():
                self._cleanup_ipc()
            # Work setup() started on the token ends, as after a failed setup()
            self.service.stopping.stop()
            self._transition(State.FAILED)
            if not isinstance(e, Exception):
                raise
            raise RunError(self.name, f"failed to start: {e}") from e

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
        """Create IPC primitives for subprocess communication: the run's own,
        its error queue in the record its claim made."""
        self._shutdown_event = ctx.Event()
        self._stop_reader, self._stop_writer = ctx.Pipe(duplex=False)
        self._healthy_event = ctx.Event()
        self._errors.queue = ctx.Queue()

    def _inherited_writer(self, ctx: BaseContext) -> Connection | None:
        """The stop pipe's writer as the child inherits it: a forked child holds
        a copy, which it must close for the pipe to reach EOF once the parent's
        copy closes; a spawned child has none."""
        return self._stop_writer if ctx.get_start_method() == "fork" else None

    def _spawn_process(self, ctx: BaseContext, log_config: dict[str, Any]) -> None:
        """Spawn the subprocess."""
        # The logger does not pickle, which spawn and forkserver need; the
        # subprocess makes its own from log_config
        saved_lg = getattr(self.service, "_lg", None)
        if saved_lg is not None:
            setattr(self.service, "_lg", None)

        try:
            self._process = self._new_process(ctx, log_config)
            self._errors.process = self._process  # the writer of its queue
            # A SIGINT between the fork and Process.start() storing the child's
            # handle would leave a child no cleanup can reach: held until then
            with _interrupt_held():
                self._process.start()
        finally:
            # Restore logger in parent process
            if saved_lg is not None:
                setattr(self.service, "_lg", saved_lg)

    def _new_process(self, ctx: BaseContext, log_config: dict[str, Any]) -> BaseProcess:
        """The service's subprocess, not yet started, with this run's IPC."""
        # typeshed declares Process on each concrete context, not BaseContext
        process: BaseProcess = ctx.Process(  # type: ignore[attr-defined]
            target=_process_entry,
            args=(
                self.service,
                self._shutdown_event,
                self._stop_reader,
                self._inherited_writer(ctx),
                self._healthy_event,
                self._errors.queue,
                log_config,
            ),
            name=f"svc-{self.name}",
            daemon=True,
        )
        return process

    def _release_start(self, run: int) -> bool:
        """Release the start of *run*: a second start() could not claim it
        meanwhile, and a stop() from another thread waited for this release
        (_await_start()).

        Returns:
            True if a stop() ended *run* before the release.
        """
        with self._lock:
            self._start_thread = None
            if self._start_done is not None:
                self._start_done.notify_all()
                self._start_done = None
            return self._run != run

    def _claim_start(self) -> int:
        """Check under the lock that the runner can start and no other start()
        is in progress, claim the start, and reset the stop request there
        (_reset_stop()), before a stop() from another thread can reach this
        start: such a stop() waits for the claim.

        Returns:
            The run claimed.

        Raises:
            InvalidTransitionError: If the runner is not CREATED, STOPPED or
                FAILED, is FAILED with its child still alive (a wait_healthy()
                that timed out leaves it so: stop() it first), or another
                start() is in progress.
        """
        with self._lock:
            return self._claim_locked()

    def _claim_restart(self, run: int) -> int:
        """Claim the start of a restart of *run*, which failed, as
        _claim_start() does, unless a stop() has ended *run* since.

        Returns:
            The run claimed.

        Raises:
            StoppedError: If a stop() ended *run*: the restart is cancelled.
            InvalidTransitionError: As for _claim_start().
        """
        with self._lock:
            if self._run != run:
                raise StoppedError()
            return self._claim_locked()

    def _claim_locked(self) -> int:
        """_claim_start()'s check and claim, under the lock; returns the run."""
        startable = self._state in (State.CREATED, State.STOPPED, State.FAILED)
        if self._state == State.FAILED and self.is_alive():
            startable = False
        if self._start_thread is not None or not startable:
            raise InvalidTransitionError(self.name, self._state, State.INITD)
        self._start_thread = threading.get_ident()
        self._run += 1
        self._reset_stop()
        # A record of its own before setup() can fail: the previous run's
        # child is gone (the check above), so its queue is closed, its cause
        # kept for the waiters holding it
        self._errors.close()
        self._errors = _RunErrors()
        return self._run

    def _await_start(self, timeout: float) -> bool:
        """Wait up to *timeout* seconds for a start() in progress on another
        thread to return; stop() calls it first.

        Returns:
            False if a start() is still in progress after *timeout*.
        """
        with self._lock:
            if self._start_thread is None:
                return True
            if self._start_done is None:
                self._start_done = threading.Condition(self._lock)
            return self._start_done.wait_for(
                lambda: self._start_thread is None, timeout
            )

    def _await_run(self, timeout: float) -> int:
        """The run a wait_healthy() waits for: the current run, read under the
        lock; with a start() in progress on another thread, that start's run,
        once it has returned within *timeout*. A run that a stop() ended
        meanwhile stays the waiter's, even when another has started since:
        the wait learns it was stopped.

        Raises:
            HealthTimeoutError: If a start() is still in progress after *timeout*.
        """
        with self._lock:
            run = self._run  # a start in progress has claimed it already
            own = self._start_thread == threading.get_ident()
            if not own and self._start_thread is not None:
                if self._start_done is None:
                    self._start_done = threading.Condition(self._lock)
                # Done once the start returned, or once a stop() ended the run:
                # a start claimed since is not this wait's to wait for
                if not self._start_done.wait_for(
                    lambda: self._start_thread is None or self._run != run, timeout
                ):
                    raise HealthTimeoutError(self.name, timeout)
            return run

    def _reset_stop(self) -> None:
        """Give the service a token for the coming run; called under the lock.
        A token stays stopped, so a run after a stopped one gets a new token."""
        if self.service.stopping.is_set():
            self.service.stopping = StopToken()

    def _run_setup(self) -> None:
        """Run service setup, transition to FAILED on error. A failed setup's
        token is stopped, so work it started on it ends; the next start()
        gives the service a new one (_reset_stop())."""
        try:
            self.service.setup()
        except Exception as e:
            self.service.stopping.stop()
            if self._state != State.FAILED:  # a retry from FAILED stays there
                self._transition(State.FAILED)
            if isinstance(e, SetupError):
                raise
            raise SetupError(self.name, str(e)) from e

    # -- health and restarts ---------------------------------------------------------

    def wait_healthy(self, timeout: float = 30.0, interval: float = 0.1) -> None:
        """Block until healthy or timeout. Several threads may wait at once:
        the first to see the service healthy moves it to RUNNING.

        A start() in progress on another thread is waited for first, within
        *timeout*: between setup() and the launch of its process a runner is
        STARTING but not alive, which is no exit.

        Args:
            timeout: Max seconds to wait.
            interval: Seconds between health checks.

        Raises:
            RunError: If execution exits during startup.
            HealthTimeoutError: If timeout reached before healthy.
        """
        start = time.monotonic()
        run = self._await_run(timeout)  # a later run is not this wait's

        while time.monotonic() - start < timeout:
            if self._run != run:
                raise RunError(self.name, "stopped during startup")
            # FAILED: the run ended before it was healthy, settled by the
            # runner; not alive: a process that is gone, which nothing settles
            if self._state == State.FAILED or not self.is_alive():
                self._handle_execution_exit(run)

            if self.is_healthy():
                self._settle_healthy(run)
                return

            time.sleep(interval)

        if self._fail_run(run) is None:
            raise RunError(self.name, "stopped during startup")
        error = HealthTimeoutError(self.name, timeout)
        error.add_note(self._child_state())  # what became of the child
        raise error

    def _child_state(self) -> str:
        """The child as a health timeout found it: alive, or how it ended."""
        process = self._process
        if process is None:
            return "no child process"
        if process.is_alive():
            return f"child pid {process.pid} alive, never reported healthy"
        return f"child pid {process.pid} exited with code {process.exitcode}"

    def _settle_healthy(self, run: int) -> None:
        """*run* reported healthy: it is RUNNING, from STARTING only. Another
        waiter may have moved it already, which is success; the run ending, a
        stop() or a later run first is not.

        Raises:
            RunError: If the run ended or was stopped before.
        """
        if self._transition_from(run, State.STARTING, State.RUNNING):
            self._retries = 0
        elif self._run != run:
            raise RunError(self.name, "stopped during startup")
        elif self._state == State.FAILED:
            self._handle_execution_exit(run)
        elif self._state not in (State.RUNNING, State.IDLE):
            raise RunError(self.name, "stopped during startup")

    def _handle_execution_exit(self, run: int) -> None:
        """*run* exited during a health wait: it fails, checked under the lock
        to be still the current run, and its exception is the cause.

        Raises:
            RunError: Always: the run exited, or a stop() ended it first.
        """
        errors = self._fail_run(run)
        if errors is None:
            raise RunError(self.name, "stopped during startup")
        exc = errors.drain()  # this run's, not a later one's
        if exc:
            raise RunError(self.name, f"exited during startup: {exc}") from exc
        raise RunError(self.name, "exited during startup")

    def check(self) -> bool:
        """Check health and handle failures; the monitor calls it periodically.

        Returns:
            True if a restart was initiated.
        """
        return self._check(threading.Event())  # no monitor's: never stopped

    def _check(self, stopped: threading.Event) -> bool:
        """check(), for a monitor that *stopped* stops. Whether it is set is
        read under the lock with the run: stop() sets it under the lock that
        ends the run, so a pass either finds it set and acts on nothing, or
        observed a run that every transition below is bound to."""
        with self._lock:
            if stopped.is_set():
                return False
            # The run this check observes, and its process
            state, run, process = self._state, self._run, self._process
        if state not in (State.RUNNING, State.FAILED):
            return False
        if state == State.RUNNING:
            if self.is_alive() and self.is_healthy():
                return False
            if process is None or not self._exited_cleanly(process):
                # Only the observed run: one started since is not this check's
                if not self._transition_from(run, State.RUNNING, State.FAILED):
                    return False
                if self.is_alive():
                    return False  # unhealthy: the next check restarts it
        # Exit code 0 is a clean shutdown, whenever it is seen: never restarted
        if process is not None and self._exited_cleanly(process):
            self._end_clean(run, process)
            return False
        # The restart stops what is left of the failed run first, and waits for
        # it: nothing starts on top of it
        return self._maybe_restart(run)

    def _exited_cleanly(self, process: BaseProcess) -> bool:
        """True if *process*, the run's child, is gone with exit code 0."""
        return not self.is_alive() and process.exitcode == 0

    def _maybe_restart(self, run: int) -> bool:
        """Wait the policy's backoff, then attempt a restart of the failed
        *run*. The run and the retry are checked, and the retry counted, under
        the lock: two callers finding one retry left (the monitor, and check()
        on another thread) spend it once, and a caller that saw a run another
        caller has since restarted reserves nothing."""
        with self._lock:
            if self._run != run or self._state != State.FAILED:
                return False
            # One restart at a time: one under way is the failed run's
            if self._restarting or not self._retry_left():
                return False
            backoff = min(
                self.policy.backoff * (self.policy.backoff_multiplier**self._retries),
                self.policy.max_backoff,
            )
            # Before counting it, so restart_pending holds without a gap
            self._restarting = True
            self._retries += 1
        try:
            time.sleep(backoff)
            return self._attempt_restart(run)
        finally:
            with self._lock:
                self._restarting = False

    def _attempt_restart(self, run: int) -> bool:
        """Stop the failed *run*, start again and wait until healthy; a failure
        is logged. Cleans up via _stop_for_restart() first, so no residual state
        of the failed run remains. A stop() that ended *run* meanwhile cancels
        the restart: checked under the lock both when its cleanup claims the
        stop and when its start is claimed."""
        try:
            self._stop_for_restart(run)
            self._start(functools.partial(self._claim_restart, run))
            self.wait_healthy()
            return True
        except StoppedError:
            return False
        except Exception as e:
            self.service.lg.warning(
                "restart failed",
                extra={"exception": e, "service": self.name, "attempt": self._retries},
            )
            return False

    def start_monitor(self, interval: float = 1.0) -> None:
        """Start background monitor thread for auto-restart.

        The monitor periodically calls check() to detect failures and
        trigger restarts according to the restart policy.

        Args:
            interval: Seconds between health checks (default: 1.0)
        """
        with self._lock:
            if self._monitor is not None and self._monitor.thread.is_alive():
                return  # Already monitoring
            stopped = threading.Event()  # this monitor's own
            thread = threading.Thread(
                target=self._monitor_loop,
                args=(interval, stopped),
                daemon=True,
                name=f"monitor-{self.name}",
            )
            # Started under the lock: until then is_alive() is False, and another
            # call would take it for no monitor and start its own
            self._monitor = _Monitor(thread, stopped)
            try:
                thread.start()
            except BaseException:
                self._monitor = None  # a later call can start one
                raise

    @property
    def monitoring(self) -> bool:
        """True while the start_monitor() thread is running."""
        monitor = self._monitor
        return monitor is not None and monitor.thread.is_alive()

    def stop_monitor(self, timeout: float = 2.0) -> None:
        """Stop the monitor thread.

        Args:
            timeout: Seconds to wait for thread to stop.
        """
        with self._lock:
            monitor = self._monitor
        self._end_monitor(monitor, timeout)

    def _end_monitor(self, monitor: _Monitor | None, timeout: float = 2.0) -> None:
        """Stop *monitor* and wait for it, up to *timeout* seconds; a monitor
        started since is left running."""
        if monitor is None:
            return
        monitor.stopped.set()
        if monitor.thread.is_alive():
            monitor.thread.join(timeout=timeout)
        with self._lock:
            if self._monitor is monitor:
                self._monitor = None

    def _monitor_loop(self, interval: float, stopped: threading.Event) -> None:
        """Monitor loop that checks health and triggers restarts, until
        *stopped*, its own event, is set."""
        while not stopped.is_set():
            if self._state in (State.STOPPED, State.DONE):
                break

            # Failure detection and restart, a clean exit ending the run DONE;
            # nothing once a stop() has signalled this monitor
            restarted = self._check(stopped)
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
            stopped.wait(timeout=interval)

    def _end_clean(self, run: int, process: BaseProcess) -> bool:
        """Move *run*, whose *process* exited cleanly, to DONE. DONE is final,
        so no stop() follows to release the log listener and queues: release
        them here, keeping the process handle for exit_code.

        Claimed under the lock: an exit observed for a run a stop() has ended
        since, or for a process replaced since, changes nothing.

        Returns:
            True if the run ended here.
        """
        with self._lock:
            if self._run != run or self._process is not process:
                return False
            if self._stopper is not None:
                return False  # a stop in progress ends it
            if State.DONE not in TRANSITIONS.get(self._state, set()):
                return False
            self._state = State.DONE
        # Work setup() started on the token ends, as on every other end of a
        # run; from DONE no other run replaces the token
        self.service.stopping.stop()
        self._cleanup_ipc()
        self._process = process
        return True

    # -- stop -------------------------------------------------------------------------

    def stop(self, timeout: float | None = None) -> None:
        """Stop the subprocess. A start() in progress on another thread is
        waited for first; that wait and the wait for the child to exit
        gracefully take at most *timeout* (stop_timeout if None) together.

        It ends the current run first, even with no child left to stop: a
        restart of that run the monitor has under way starts nothing. Called
        from setup(), on the start's own thread, it returns at once: start()
        stops the child it spawns and raises RunError."""
        with self._lock:
            self._run += 1
            run = self._run  # this stop's: a stop or start after it moves it on
            monitor = self._monitor  # this run's: one started later is not ended
            if monitor is not None:
                # With the run's end: a pass that takes its snapshot from now
                # on finds it set (_check())
                monitor.stopped.set()
            if self._start_done is not None:
                self._start_done.notify_all()  # their run ended: waiters learn it
            if self._start_thread == threading.get_ident():
                return  # from setup(): its start() stops the child it spawns
        budget = self.stop_timeout if timeout is None else timeout
        began = time.monotonic()
        if not self._await_start(budget):
            self.service.lg.warning(
                "stop() waited for a start() in progress",
                extra={"service": self.name, "timeout": budget},
            )
            return
        # STOPPING goes on: a stop the child outlived is finished here, and
        # one in progress on another thread is left to it (_stop_run())
        if self._state in (State.CREATED, State.STOPPED, State.DONE):
            return

        # Stop monitor thread first
        self._end_monitor(monitor)
        self._stop_run(run, max(0.0, budget - (time.monotonic() - began)))

    def _stop_run(self, run: int, timeout: float) -> None:
        """stop()'s _stop_process(), for the *run* it ended: once another stop
        or a start has moved the run on, what runs now is not this stop's."""
        with self._lock:
            if self._run != run or self._state == State.DONE:
                return
            claimed = self._claim_stop_locked()
        if claimed:
            self._end_claimed(timeout)

    def _stop_for_restart(self, run: int) -> None:
        """Stop the failed *run*'s process only: a restart runs on the monitor
        thread, which keeps watching the restarted process.

        Raises:
            StoppedError: If a stop() ended *run* already: what runs now is
                another start's, and is left alone.
        """
        with self._lock:
            if self._run != run:
                raise StoppedError()
            claimed = self._claim_stop_locked()
        if claimed:
            self._end_claimed(None)

    def _stop_process(self, timeout: float | None) -> None:
        """Signal the subprocess to stop, escalating to terminate and kill. One
        stop runs at a time: another one in progress is left to finish. From
        STOPPING, which a child that outlived kill() leaves, it tries again.
        A run the monitor ended DONE meanwhile, its child having exited
        cleanly, has nothing left to stop."""
        with self._lock:
            if self._state == State.DONE:
                return
            claimed = self._claim_stop_locked()
        if claimed:
            self._end_claimed(timeout)

    def _end_claimed(self, timeout: float | None) -> None:
        """End the process of a stop claimed, then release the claim. STOPPED
        is published under the same lock hold that releases it: a start()
        that sees STOPPED, and the stop() of that run, find no claim held."""
        stopped = False
        try:
            stopped = self._end_process(
                self.stop_timeout if timeout is None else timeout
            )
        finally:
            with self._lock:
                if stopped:
                    if State.STOPPED not in TRANSITIONS.get(self._state, set()):
                        raise InvalidTransitionError(
                            self.name, self._state, State.STOPPED
                        )
                    self._state = State.STOPPED
                self._stopper = None

    def _claim_stop_locked(self) -> bool:
        """Claim the stop and move to STOPPING, under the lock, unless another
        stop is in progress.

        Returns:
            False if another stop is in progress.
        """
        if self._stopper is not None:
            return False
        if self._state != State.STOPPING:
            if State.STOPPING not in TRANSITIONS.get(self._state, set()):
                raise InvalidTransitionError(self.name, self._state, State.STOPPING)
            self._state = State.STOPPING
        self._stopper = threading.get_ident()
        return True

    def _end_process(self, timeout: float) -> bool:
        """Signal the subprocess to stop and wait for it, escalating to
        terminate and kill; its handles are released once it is gone.

        Returns:
            True if the process is gone: the caller publishes STOPPED.
        """
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
        # A process still alive after kill() leaves the runner STOPPING with its
        # handles: a later stop() tries again and cleans up once it is gone
        return process_stopped

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
        self._errors.close()  # what the child reported stays readable
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

    # -- state ------------------------------------------------------------------------

    def _transition_from(self, run: int, from_state: State, to: State) -> bool:
        """Transition to *to* if *run* is still the current run and its state is
        *from_state*, checked under the lock, so that two threads ending the
        same state cannot both do it, nor one end a run started since.

        Returns:
            True if this call made the transition.
        """
        with self._lock:
            if self._run != run or self._state != from_state:
                return False
            self._state = to
        return True

    def _fail_run(self, run: int) -> _RunErrors | None:
        """A wait_healthy() for *run* timed out, or saw it exit: fail its start,
        checked under the lock, if the run is still starting. One another
        waiter saw healthy (RUNNING) is not this wait's to fail, and one that
        has settled already is left as it is.

        Returns:
            *run*'s error record, read under the same lock: a run started
            later has its own. None if *run* is no longer the current run,
            which is left as it is.
        """
        with self._lock:
            if self._run != run:
                return None
            if self._state in (State.INITD, State.STARTING):
                self._state = State.FAILED
            return self._errors

    def _transition(self, to: State) -> None:
        """Transition to a new state."""
        with self._lock:
            if to not in TRANSITIONS.get(self._state, set()):
                raise InvalidTransitionError(self.name, self._state, to)
            self._state = to

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

        Returns the first exception encountered (root cause), the current
        run's: each run reports into a record of its own.
        """
        return self._errors.drain()

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
    _restore_interrupt()
    exit_code = 0
    try:
        lg = Logger.from_queue_config(log_config, name=f"svc/{service.name}")
        if hasattr(service, "_lg"):
            service._lg = lg
        _bridge_stop(service.stopping, stop_reader, inherited_writer)

        _start_health_poller(service, shutdown_event, healthy_event)
        service.run()
    except BaseException as e:
        exit_code = _exit_code(e)
        with contextlib.suppress(Exception):
            error_queue.put(e)
    finally:
        # The run has ended: work derived from its token is told to stop
        with contextlib.suppress(Exception):
            service.stopping.stop()
        with contextlib.suppress(Exception):
            service.teardown()
    if exit_code:
        sys.exit(exit_code)


class _HeldInterrupt:
    """A SIGINT handler that holds the signal back, keeping the handler it
    replaced: the one a held signal goes to, and the one a forked child, which
    inherits this handler, puts back (_restore_interrupt())."""

    def __init__(self, previous: Callable[[int, FrameType | None], Any]) -> None:
        self.previous = previous
        self.held: tuple[int, FrameType | None] | None = None

    def __call__(self, signum: int, frame: FrameType | None) -> None:
        if self.held is None:
            self.held = (signum, frame)


@contextlib.contextmanager
def _interrupt_held() -> Iterator[None]:
    """Hold a SIGINT back for the block, then deliver it to the handler it
    went to before: a KeyboardInterrupt comes after the block, not inside it.

    Only the main thread receives KeyboardInterrupt and may change handlers;
    elsewhere, and with no Python handler installed, there is nothing to hold.
    """
    previous = signal.getsignal(signal.SIGINT)
    if threading.current_thread() is not threading.main_thread() or not callable(
        previous
    ):
        yield
        return
    holder = _HeldInterrupt(previous)
    signal.signal(signal.SIGINT, holder)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
        if holder.held is not None:
            previous(*holder.held)


def _restore_interrupt() -> None:
    """In a forked child: put back the SIGINT handler that _interrupt_held()
    replaced in the parent at the fork. A spawned child starts with its own."""
    handler = signal.getsignal(signal.SIGINT)
    if isinstance(handler, _HeldInterrupt):
        signal.signal(signal.SIGINT, handler.previous)


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
