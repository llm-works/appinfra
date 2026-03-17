"""Base runner class - abstract execution and state management."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod

from ..errors import HealthTimeoutError, InvalidTransitionError, RunError
from ..state import TRANSITIONS, RestartPolicy, State, StateHook


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
        service: object,
        policy: RestartPolicy | None = None,
    ) -> None:
        """Initialize runner.

        Args:
            service: The service to run.
            policy: Restart policy. Defaults to RestartPolicy().
        """
        from ..base import Service

        if not isinstance(service, Service):
            raise TypeError(f"service must be a Service, got {type(service)}")

        self.service: Service = service
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

        # Guard transition - _run() may have already transitioned
        if self._state not in (State.FAILED, State.STOPPED, State.DONE):
            self._transition(State.FAILED)
        raise HealthTimeoutError(self.name, timeout)

    def _handle_execution_exit(self) -> None:
        """Handle execution exit during health wait."""
        exc = self.exception
        # Guard transition - _run() may have already transitioned to FAILED
        if self._state != State.FAILED:
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
        """Attempt restart based on policy.

        Performs cleanup via stop() before restarting to ensure no residual
        state from the failed execution.
        """
        if not self.policy.restart_on_failure:
            return False

        if self._retries >= self.policy.max_retries:
            return False

        backoff = self._calculate_backoff()
        self._retries += 1

        time.sleep(backoff)

        try:
            # Ensure cleanup before restart (handles residual state)
            self.stop()
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
            except Exception as e:
                self.service.lg.warning(
                    "state hook failed", extra={"exception": e, "hook": hook}
                )
