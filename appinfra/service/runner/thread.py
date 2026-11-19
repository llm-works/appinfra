# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""ThreadRunner - runs services in daemon threads."""

from __future__ import annotations

import threading

from ..base import Service
from ..channel.sync import Channel
from ..errors import SetupError
from ..state import RestartPolicy, State
from .base import Runner
from .drive import LOOPED_SERVICES, drive


class ThreadRunner(Runner):
    """Runs a service in a daemon thread.

    Runs the service's work in a background thread, by its form (see
    drive()). Handles setup, teardown, and state management.

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
        inbox: Channel | None = None,
    ) -> None:
        """Initialize thread runner.

        Args:
            service: The service to run.
            policy: Restart policy.
            inbox: A StepService's inbox channel (see Runner).
        """
        super().__init__(service, policy, inbox)
        self._thread: threading.Thread | None = None
        self._exception: BaseException | None = None
        # Ends a scheduled or step service's loop; set by stop()
        self._stop = threading.Event()
        # Set by _run() once the service's work has returned. Thread.is_alive() on
        # Python 3.13+ stays True until the OS thread handle is marked done,
        # which happens after the GIL is released; polling it alone lets
        # wait_healthy() observe a finished thread as alive and report
        # RUNNING for a service that exited during startup.
        self._exited = False

    def start(self) -> None:
        """Start the service in a background thread."""
        # Validate state under lock before setup to prevent concurrent starts
        with self._lock:
            if self._state not in (State.CREATED, State.STOPPED, State.FAILED):
                from ..errors import InvalidTransitionError

                raise InvalidTransitionError(self.name, self._state, State.INITD)

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
        self._exited = False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"svc-{self.name}",
            daemon=True,
        )
        self._thread.start()

    @property
    def _loops_here(self) -> bool:
        """True if the runner loops the service (step, scheduled) and so tears it
        down on this thread once the loop ends; a service with its own run() is
        torn down by stop(), which is how run() learns to return."""
        return isinstance(self.service, LOOPED_SERVICES)

    def _run(self) -> None:
        """Thread target.

        Records how the service's work ended, tears down a service the runner
        loops, then settles the state. Transitions are guarded to handle races
        with stop() or wait_healthy().
        """
        try:
            try:
                drive(self.service, self._stop, self.inbox)
            except BaseException as e:
                self._exception = e
            if self._loops_here:
                self._teardown()
            self._settle_exit_state()
        finally:
            # Last, so _exception, teardown and the state are settled before
            # is_alive() reports the exit.
            self._exited = True

    def _settle_exit_state(self) -> None:
        """DONE after a clean exit, FAILED after an exception, unless stop() or
        wait_healthy() has already moved the state on."""
        from ..errors import InvalidTransitionError

        try:
            if self._exception is None:
                if self._state == State.RUNNING:
                    self._transition(State.DONE)
            elif self._state in (State.STARTING, State.RUNNING):
                self._transition(State.FAILED)
        except InvalidTransitionError:
            pass  # Already transitioned by stop()

    def _teardown(self) -> None:
        """Run the service's teardown(); a failure is logged, not raised."""
        try:
            self.service.teardown()
        except Exception as e:
            self.service.lg.warning(
                "teardown failed", extra={"exception": e, "service": self.name}
            )

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the service.

        A step or scheduled service's loop ends and the service thread tears it
        down; a service with its own run() is torn down here, which tells run()
        to return. Either way the thread is then joined for up to *timeout*
        seconds.
        """
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
                # Stay in STOPPING state since thread is still alive
                return

        self._transition(State.STOPPED)

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
