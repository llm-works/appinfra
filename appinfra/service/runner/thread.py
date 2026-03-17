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
