# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""ProcessBase: the self-driving state machine ProcessRunner runs on, apart from
the service Runtime's Runner: start(), stop(), wait_healthy() and check() from
any thread, under a lock."""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager

from ...runtime import StopToken
from ..base import Service
from ..errors import HealthTimeoutError, InvalidTransitionError, RunError, SetupError
from ..state import TRANSITIONS, RestartPolicy, State, StateHook
from .drive import check_service

# The runners whose state hooks the current thread is running (_notify())
_in_hooks = threading.local()

# The policy of every runner given none; RestartPolicy is frozen, so one serves all
_DEFAULT_POLICY = RestartPolicy()


class ProcessBase(ABC):
    """ProcessRunner's base: service execution and state management driven by
    calls on it from any thread.

    It handles:
    - State tracking (STOPPED -> STARTING -> RUNNING -> STOPPING)
    - Restart policy with backoff
    - State change hooks
    """

    def __init__(
        self,
        service: object,
        policy: RestartPolicy | None = None,
        *,
        parent: StopToken | None = None,
    ) -> None:
        """Initialize runner.

        Args:
            service: The service to run.
            policy: Restart policy. Defaults to RestartPolicy().
            parent: The token each run's stopping token derives from, so
                stopping it stops the service; None for a token of its own.

        Raises:
            TypeError: If *service* is not a Service (see check_service()).
        """
        self.service: Service = check_service(service)
        self._parent = parent
        # Before setup(), which may already derive from it
        self.service.stopping = self._new_token()
        self.policy = policy or _DEFAULT_POLICY
        self._state = State.CREATED
        # Created by the first on_state_change(): most runners have no hooks
        self._hooks: list[StateHook] | None = None
        self._retries = 0
        self._restarting = False
        self._lock = threading.Lock()
        # The thread running start(), from its state check until it returns
        # (_start_claim()); a stop() from another thread waits on _start_done.
        # Created only while such a stop() waits, so an idle runner holds no
        # condition; it shares _lock, which guards both fields.
        self._start_thread: int | None = None
        self._start_done: threading.Condition | None = None

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

        Hooks observe transitions; they run on the thread making the
        transition, which may be the service's own thread or loop. A hook that
        calls start() or stop() on this runner gets a RuntimeError, which is
        logged like any other hook failure.

        Args:
            hook: Callable(service_name, from_state, to_state).
        """
        # Under the lock, so two first registrations cannot each create a list
        with self._lock:
            if self._hooks is None:
                self._hooks = []
            self._hooks.append(hook)

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
            RuntimeError: If called from one of this runner's state hooks.
        """
        self._refuse_from_hook("start")
        with self._start_claim():
            self._begin_start()
            self._launch()

    @abstractmethod
    def _launch(self) -> None:
        """Begin the service's work once it is set up and STARTING: start its
        thread, process or task."""

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
        """Block until healthy or timeout. Several threads may wait at once:
        the first to see the service healthy moves it to RUNNING.

        A start() in progress on another thread is waited for first, within
        *timeout*: between setup() and the launch of its work a runner is
        STARTING but not alive, which is no exit.

        Args:
            timeout: Max seconds to wait.
            interval: Seconds between health checks.

        Raises:
            RunError: If execution exits during startup.
            HealthTimeoutError: If timeout reached before healthy.
        """
        start = time.monotonic()
        on_start_thread = self._start_thread == threading.get_ident()
        if not on_start_thread and not self._await_start(timeout):
            raise HealthTimeoutError(self.name, timeout)

        while time.monotonic() - start < timeout:
            # FAILED: the run ended before it was healthy, settled by the
            # runner; not alive: a process that is gone, which nothing settles
            if self._state == State.FAILED or not self.is_alive():
                self._handle_execution_exit()

            if self.is_healthy():
                # Only from STARTING: another waiter may have moved it already,
                # which is success; the run ending or a stop() first is not
                if self._transition_from(State.STARTING, State.RUNNING):
                    self._retries = 0
                elif self._state == State.FAILED:
                    self._handle_execution_exit()
                elif self._state not in (State.RUNNING, State.IDLE):
                    raise RunError(self.name, "stopped during startup")
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
            # The restart stops what is left of the failed run first, and waits
            # for it: nothing starts on top of it
            return self._maybe_restart()

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

    @property
    def restart_delay(self) -> float:
        """Seconds the restart policy waits before the next restart attempt."""
        return self._calculate_backoff()

    def restart(self) -> bool:
        """Make one restart attempt now, counted against the restart policy:
        stop the failed run, start again and wait until healthy. The caller
        waits restart_delay first, as check() does on its own thread.

        Returns:
            True if the service runs again; False if the policy allows no
            further attempt, or this one failed (logged).
        """
        if not self.can_restart:
            return False
        # Before counting it, so restart_pending holds without a gap
        self._restarting = True
        self._retries += 1
        try:
            return self._attempt_restart()
        finally:
            self._restarting = False

    def _maybe_restart(self) -> bool:
        """Wait the policy's backoff, then attempt a restart, as check() does."""
        if not self.can_restart:
            return False
        backoff = self._calculate_backoff()
        # Before counting it, so restart_pending holds without a gap
        self._restarting = True
        self._retries += 1
        try:
            time.sleep(backoff)
            return self._attempt_restart()
        finally:
            self._restarting = False

    def _attempt_restart(self) -> bool:
        """Stop the failed run, start again and wait until healthy; a failure is
        logged. Cleans up via _stop_for_restart() first, so no residual state of
        the failed run remains."""
        try:
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

    def _calculate_backoff(self) -> float:
        """Calculate backoff delay for current retry."""
        return min(
            self.policy.backoff * (self.policy.backoff_multiplier**self._retries),
            self.policy.max_backoff,
        )

    @contextmanager
    def _start_claim(self) -> Iterator[None]:
        """Hold the start for one start() call, from its state check until it
        returns or raises; every runner's start() runs inside it. A second
        start() fails before it calls setup(), and a stop() from another thread
        waits for the claim to be released (_await_start()).

        Raises:
            InvalidTransitionError: If the runner is not CREATED, STOPPED or
                FAILED, or another start() is in progress.
        """
        self._claim_start()
        try:
            yield
        finally:
            with self._lock:
                self._start_thread = None
                if self._start_done is not None:
                    self._start_done.notify_all()
                    self._start_done = None

    def _claim_start(self) -> None:
        """Check under the lock that the runner can start and no other start()
        is in progress, claim the start, and reset the stop request there
        (_reset_stop()), before a stop() from another thread can reach this
        start: such a stop() waits for the claim.

        Raises:
            InvalidTransitionError: If the runner is not CREATED, STOPPED or
                FAILED, or another start() is in progress.
        """
        with self._lock:
            startable = self._state in (State.CREATED, State.STOPPED, State.FAILED)
            if self._start_thread is not None or not startable:
                raise InvalidTransitionError(self.name, self._state, State.INITD)
            self._start_thread = threading.get_ident()
            self._reset_stop()

    def _await_start(self, timeout: float) -> bool:
        """Wait up to *timeout* seconds for a start() in progress on another
        thread to return; every runner's stop() calls it first.

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

    def _begin_start(self) -> None:
        """Run setup() and move to STARTING, inside start()'s claim.

        Raises:
            SetupError: If setup fails.
        """
        self._run_setup()
        self._transition(State.INITD)
        self._transition(State.STARTING)

    def _start_ended(self, timeout: float) -> float | None:
        """For stop(): wait up to *timeout* seconds for a start() in progress
        on another thread; if it is still running then, log it.

        Returns:
            The seconds of *timeout* left for stop() to wait for the service's
            work, or None if stop() should return without acting.
        """
        began = time.monotonic()
        if not self._await_start(timeout):
            self.service.lg.warning(
                "stop() waited for a start() in progress",
                extra={"service": self.name, "timeout": timeout},
            )
            return None
        return max(0.0, timeout - (time.monotonic() - began))

    def _reset_stop(self) -> None:
        """Give the service a token for the coming run; called under the lock.
        A token stays stopped, so a run after a stopped one gets a new token,
        and the old one leaves the tree it was derived in."""
        token = self.service.stopping
        if token.is_set():
            token.detach()
            self.service.stopping = self._new_token()

    def _new_token(self) -> StopToken:
        """A stopping token for a run: derived from the parent, if there is one."""
        return self._parent.child() if self._parent is not None else StopToken()

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

    def _refuse_from_hook(self, call: str) -> None:
        """Refuse a start() or stop() from one of this runner's state hooks:
        the transition that runs them is still under way.

        Raises:
            RuntimeError: If the current thread is running this runner's hooks.
        """
        if any(runner is self for runner in getattr(_in_hooks, "runners", ())):
            raise RuntimeError(
                f"{call}() from a state hook of '{self.name}': hooks observe "
                "their runner's transitions and cannot start or stop it"
            )

    def _notify(self, from_state: State, to: State) -> None:
        """Run the state hooks for a transition; a failing hook is logged."""
        if not self._hooks:
            return
        runners = getattr(_in_hooks, "runners", None)
        if runners is None:
            runners = _in_hooks.runners = []
        runners.append(self)
        try:
            for hook in self._hooks:
                try:
                    hook(self.name, from_state, to)
                except Exception as e:
                    self.service.lg.warning(
                        "state hook failed", extra={"exception": e, "hook": hook}
                    )
        finally:
            runners.pop()
