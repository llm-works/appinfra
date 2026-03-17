"""ThreadRunner - runs services in daemon threads."""

from __future__ import annotations

import threading

from ..base import Service
from ..errors import SetupError
from ..state import RestartPolicy, State
from .base import Runner


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
        self._thread = threading.Thread(
            target=self._run,
            name=f"svc-{self.name}",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        """Thread target.

        Updates state on exit (clean or exception). Transitions are guarded
        to handle races with stop() or wait_healthy().
        """
        from ..errors import InvalidTransitionError

        try:
            self.service.execute()
            # Clean exit - transition to DONE if in RUNNING state
            try:
                if self._state == State.RUNNING:
                    self._transition(State.DONE)
            except InvalidTransitionError:
                pass  # Already transitioned by stop()
        except BaseException as e:
            self._exception = e
            # Transition to FAILED if possible
            try:
                if self._state in (State.STARTING, State.RUNNING):
                    self._transition(State.FAILED)
            except InvalidTransitionError:
                pass  # Already transitioned by stop()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the service."""
        if self._state in (State.CREATED, State.STOPPED, State.STOPPING, State.DONE):
            return

        self._transition(State.STOPPING)

        # Teardown with exception handling - continue to join even if teardown fails
        try:
            self.service.teardown()
        except Exception as e:
            self.service.lg.warning(
                "teardown failed", extra={"exception": e, "service": self.name}
            )

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
