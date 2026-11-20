# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""ThreadRunner - runs services in daemon threads."""

from __future__ import annotations

import threading

from ..base import ScheduledService, Service
from ..state import RestartPolicy, State
from .base import Runner
from .drive import check_drivable, drive


class ThreadRunner(Runner):
    """Runs a service in a daemon thread.

    Runs the service's work in a background thread (see drive()). Handles
    setup, teardown, and state management. An AsyncService runs on a LoopHost
    instead.

    Example:
        runner = ThreadRunner(my_service)
        runner.start()
        runner.wait_healthy(timeout=30.0)
        # ... service is running ...
        runner.stop()
    """

    def __init__(self, service: Service, policy: RestartPolicy | None = None) -> None:
        """Initialize thread runner.

        Args:
            service: The service to run.
            policy: Restart policy.

        Raises:
            TypeError: If *service* is an AsyncService.
        """
        super().__init__(service, policy)
        check_drivable(self.service)
        self._thread: threading.Thread | None = None
        self._exception: BaseException | None = None
        # Ends a scheduled service's loop; set by stop()
        self._stop = threading.Event()
        # Set by _run() once the service's work has returned. Thread.is_alive() on
        # Python 3.13+ stays True until the OS thread handle is marked done,
        # which happens after the GIL is released; polling it alone lets
        # wait_healthy() observe a finished thread as alive and report
        # RUNNING for a service that exited during startup.
        self._exited = False

    def _launch(self) -> None:
        """Start the service's thread."""
        self._exception = None
        # The thread first, so an older one ending now sees it isn't current
        self._thread = threading.Thread(
            target=self._run,
            name=f"svc-{self.name}",
            daemon=True,
        )
        self._exited = False
        self._thread.start()

    def _reset_stop(self) -> None:
        self._stop.clear()

    @property
    def _loops_here(self) -> bool:
        """True if the runner loops the service (scheduled) and so tears it down
        on this thread once the loop ends; a service with its own run() is torn
        down by stop(), which is how run() learns to return."""
        return isinstance(self.service, ScheduledService)

    def _run(self) -> None:
        """Thread target.

        Records how the service's work ended, tears down a service the runner
        loops, then settles the state. Transitions are guarded to handle races
        with stop() or wait_healthy().
        """
        try:
            try:
                drive(self.service, self._stop)
            except BaseException as e:
                self._exception = e
            if self._loops_here:
                self._teardown()
            self._settle_exit_state(self._exception)
        finally:
            # Last, so _exception, teardown and the state are settled before
            # is_alive() reports the exit; not once a start() on another
            # thread has launched a newer run
            if self._thread is threading.current_thread():
                self._exited = True

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the service.

        A scheduled service's loop ends and the service thread tears it down; a
        service with its own run() is torn down here, which tells run() to
        return. Either way the thread is then joined for up to *timeout*
        seconds. A start() in progress on another thread is waited for first;
        both waits together take at most *timeout*.

        Raises:
            RuntimeError: If called from one of this runner's state hooks.
        """
        self._refuse_from_hook("stop")
        left = self._start_ended(timeout)
        if left is None:
            return
        timeout = left
        if self._state in (State.CREATED, State.STOPPED, State.STOPPING, State.DONE):
            return

        self._transition(State.STOPPING)
        self._stop.set()
        if not self._loops_here:
            self._teardown()

        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                # Thread didn't exit within timeout - it's a daemon thread
                # so it will be terminated when the process exits
                self.service.lg.warning(
                    f"service thread did not exit within {timeout}s, "
                    "will be terminated on process exit"
                )
                # Stay STOPPING; the thread moves the runner to STOPPED once
                # it ends
                return

        # The thread, ending, may have moved the runner to STOPPED already
        self._transition_from(State.STOPPING, State.STOPPED)

    def is_alive(self) -> bool:
        """Check if thread is running."""
        return self._thread is not None and not self._exited and self._thread.is_alive()

    def is_healthy(self) -> bool:
        """Check if service is healthy."""
        return self.service.is_healthy()

    @property
    def exception(self) -> BaseException | None:
        """Exception from the service's work, if any."""
        return self._exception
