# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Base runner class - abstract execution and state management."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod

from ..base import Service
from ..errors import HealthTimeoutError, InvalidTransitionError, RunError, SetupError
from ..state import TRANSITIONS, RestartPolicy, State, StateHook
from .drive import check_service


class Runner(ABC):
    """Abstract base for service execution and state management.

    A Runner handles:
    - HOW a service is executed (thread, process, task on an event loop)
    - State tracking (STOPPED -> STARTING -> RUNNING -> STOPPING)
    - Restart policy with backoff
    - State change hooks

    Implementations:
    - ThreadRunner: Runs the service in a daemon thread
    - ProcessRunner: Runs the service in a subprocess
    - TaskRunner: Runs an AsyncService as a task on a LoopHost's event loop
    """

    def __init__(self, service: object, policy: RestartPolicy | None = None) -> None:
        """Initialize runner.

        Args:
            service: The service to run.
            policy: Restart policy. Defaults to RestartPolicy().

        Raises:
            TypeError: If *service* is not a Service (see check_service()).
        """
        self.service: Service = check_service(service)
        self.policy = policy or RestartPolicy()
        self._state = State.CREATED
        self._hooks: list[StateHook] = []
        self._retries = 0
        self._restarting = False
        self._lock = threading.Lock()
        # Held by a start() from its state check until STARTING (_begin_start())
        self._start_claimed = False

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

    @property
    def can_restart(self) -> bool:
        """True if the restart policy still allows another restart attempt."""
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

    def _stop_for_restart(self) -> None:
        """Clean up the failed execution before a restart."""
        self.stop()

    def _maybe_restart(self) -> bool:
        """Attempt restart based on policy.

        Cleans up via _stop_for_restart() before restarting to ensure no
        residual state from the failed execution.
        """
        if not self.policy.restart_on_failure:
            return False

        if self._retries >= self.policy.max_retries:
            return False

        backoff = self._calculate_backoff()
        # Before counting it, so restart_pending holds without a gap
        self._restarting = True
        self._retries += 1

        try:
            time.sleep(backoff)
            # Ensure cleanup before restart (handles residual state)
            self._stop_for_restart()
            self.start()
            self.wait_healthy()
            return True
        except Exception as e:
            self.service.lg.warning(
                "restart failed",
                extra={"exception": e, "service": self.name, "attempt": self._retries},
            )
            return False
        finally:
            self._restarting = False

    def _calculate_backoff(self) -> float:
        """Calculate backoff delay for current retry."""
        return min(
            self.policy.backoff * (self.policy.backoff_multiplier**self._retries),
            self.policy.max_backoff,
        )

    def _begin_start(self) -> None:
        """Claim the start, run setup() and move to STARTING; the first steps of
        every runner's start(). The claim holds until STARTING, from which the
        state check alone refuses another start, so a second start() fails
        before it calls setup().

        Raises:
            InvalidTransitionError: If the runner is not CREATED, STOPPED or
                FAILED, or another start() is in progress.
            SetupError: If setup fails.
        """
        self._claim_start()
        try:
            self._run_setup()
            self._transition(State.INITD)
            self._transition(State.STARTING)
        finally:
            with self._lock:
                self._start_claimed = False

    def _claim_start(self) -> None:
        """Check under the lock that the runner can start and no other start()
        is in progress, claim the start, and reset the stop request there
        (_reset_stop()): no stop() is accepted yet, so one that lands later
        survives until the service's work sees it.

        Raises:
            InvalidTransitionError: If the runner is not CREATED, STOPPED or
                FAILED, or another start() is in progress.
        """
        with self._lock:
            startable = self._state in (State.CREATED, State.STOPPED, State.FAILED)
            if self._start_claimed or not startable:
                raise InvalidTransitionError(self.name, self._state, State.INITD)
            self._start_claimed = True
            self._reset_stop()

    def _reset_stop(self) -> None:
        """Clear the runner's stop request before a start; called under the lock.
        A runner whose stop goes through its own signal overrides it."""

    def _run_setup(self) -> None:
        """Run service setup, transition to FAILED on error."""
        try:
            self.service.setup()
        except Exception as e:
            self._transition(State.FAILED)
            if isinstance(e, SetupError):
                raise
            raise SetupError(self.name, str(e)) from e

    def _teardown(self) -> None:
        """Run the service's teardown(); a failure is logged, not raised."""
        try:
            self.service.teardown()
        except Exception as e:
            self.service.lg.warning(
                "teardown failed", extra={"exception": e, "service": self.name}
            )

    def _settle_exit_state(self, exception: BaseException | None) -> None:
        """Once the service's work has ended: STOPPED if a stop() is waiting for
        it or gave up waiting, else DONE after a clean end of a RUNNING service
        and FAILED after *exception*, unless wait_healthy() has already moved
        the state on."""
        if self._transition_from(State.STOPPING, State.STOPPED):
            return
        if exception is None:
            self._transition_from(State.RUNNING, State.DONE)
        elif not self._transition_from(State.STARTING, State.FAILED):
            self._transition_from(State.RUNNING, State.FAILED)

    def _transition_from(self, from_state: State, to: State) -> bool:
        """Transition to *to* if the state is *from_state*, checked under the
        lock, so that two threads ending the same state cannot both do it.

        Returns:
            True if this call made the transition.
        """
        with self._lock:
            if self._state != from_state:
                return False
            self._state = to
        self._notify(from_state, to)
        return True

    def _transition(self, to: State) -> None:
        """Transition to a new state."""
        with self._lock:
            from_state = self._state

            if to not in TRANSITIONS.get(from_state, set()):
                raise InvalidTransitionError(self.name, from_state, to)

            self._state = to

        self._notify(from_state, to)

    def _notify(self, from_state: State, to: State) -> None:
        """Run the state hooks for a transition; a failing hook is logged."""
        for hook in self._hooks:
            try:
                hook(self.name, from_state, to)
            except Exception as e:
                self.service.lg.warning(
                    "state hook failed", extra={"exception": e, "hook": hook}
                )
