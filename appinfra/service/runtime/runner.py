# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Runner: a service's state in the service Runtime."""

from __future__ import annotations

from ...runtime import Task
from ..base import AsyncService, ScheduledService, Service
from ..errors import InvalidTransitionError
from ..state import TRANSITIONS, RestartPolicy, State, StateHook

# The policy of every runner given none; RestartPolicy is frozen, so one serves all
_DEFAULT_POLICY = RestartPolicy()

# Where a run's teardown() stands; none is owed before the first run
OWED, TEARING, TORN = 0, 1, 2


def _check_service(service: object) -> Service:
    """Check that *service* is a Service, not both scheduled and async, and,
    if scheduled, keeps its tick loop.

    Returns:
        *service*, typed as a Service.

    Raises:
        TypeError: If it is not, is both a ScheduledService and an AsyncService,
            or is a ScheduledService overriding run(), its tick loop, which an
            override would replace.
    """
    if not isinstance(service, Service):
        raise TypeError(f"service must be a Service, got {type(service)}")
    if isinstance(service, ScheduledService) and isinstance(service, AsyncService):
        raise TypeError(
            f"service '{service.name}' is both a ScheduledService and an AsyncService"
        )
    if isinstance(service, ScheduledService) and (
        type(service).run is not ScheduledService.run
    ):
        raise TypeError(
            f"scheduled service '{service.name}' overrides run(), its tick loop: "
            "override tick() instead, and setup() or teardown() for what goes "
            "around the loop"
        )
    return service


class Runner:
    """A service in the service Runtime: its state, restart policy and the hooks
    observing its transitions, and the runtime task of its current step.

    A runner is a record. The Runtime's own task moves it, one message at a
    time, so it holds no lock; spawn() returns it to be read. Its hooks run on
    that task: a hook observes, and cannot call the Runtime back.
    """

    __slots__ = (
        "service",
        "name",
        "policy",
        "_state",
        "_hooks",
        "_retries",
        "_task",
        "_error",
        "_teardown",
        "_owner",
        "__weakref__",
    )

    def __init__(self, service: object, policy: RestartPolicy | None = None) -> None:
        """A runner of *service*, CREATED.

        Raises:
            TypeError: If *service* is not a Service (see _check_service()).
        """
        self.service: Service = _check_service(service)
        # Read once: the Runtime keys the service by it for its lifetime
        self.name: str = self.service.name
        self.policy = policy or _DEFAULT_POLICY
        self._state = State.CREATED
        # Created by the first on_state_change(): most runners have no hooks
        self._hooks: list[StateHook] | None = None
        self._retries = 0
        self._task: Task | None = None  # the current step: setup or run
        self._error: BaseException | None = None
        self._teardown = TORN
        # The runtime task that admitted it, which alone moves it; set there
        self._owner: object = None

    @property
    def state(self) -> State:
        """Current state."""
        return self._state

    @property
    def retries(self) -> int:
        """Restart attempts since the service last became healthy."""
        return self._retries

    @property
    def can_restart(self) -> bool:
        """True if the restart policy still allows another restart attempt."""
        return (
            self.policy.restart_on_failure and self._retries < self.policy.max_retries
        )

    @property
    def restart_delay(self) -> float:
        """Seconds the restart policy waits before the next restart attempt."""
        return min(
            self.policy.backoff * (self.policy.backoff_multiplier**self._retries),
            self.policy.max_backoff,
        )

    @property
    def exception(self) -> BaseException | None:
        """What the service's last run raised, if anything."""
        return self._error

    @property
    def task(self) -> Task | None:
        """The runtime task of the service's current step, its setup() or its
        run(); None between steps. A restart replaces it, so read it when
        needed rather than once. Its kind says what the service runs as, and
        an isolated one's task.process gives its child."""
        return self._task

    def _stop_span(self, timeout: float) -> float:
        """How long a stop that gives the run *timeout* seconds can take: an
        isolated run's includes the forcing of its process."""
        task = self._task
        process = None if task is None else task.process
        return timeout if process is None else timeout + process.grace

    def is_alive(self) -> bool:
        """True while a step of the service runs: its setup, run or teardown.
        A teardown runs as a task of its own, beside the run or after it."""
        task = self._task
        return (task is not None and task.alive()) or self._teardown == TEARING

    def on_state_change(self, hook: StateHook) -> None:
        """Register a callback for state changes; register it before the
        service starts, as one added later may miss transitions.

        Args:
            hook: Callable(service_name, from_state, to_state).
        """
        if self._hooks is None:
            self._hooks = []
        self._hooks.append(hook)

    def _move(self, to: State) -> State:
        """Move to *to* and run the hooks; a failing hook is logged.

        Returns:
            The state moved from.

        Raises:
            InvalidTransitionError: If TRANSITIONS has no move from the current
                state to *to*.
        """
        old = self._state
        if to not in TRANSITIONS.get(old, set()):
            raise InvalidTransitionError(self.name, old, to)
        self._state = to
        for hook in self._hooks or ():
            try:
                hook(self.name, old, to)
            except Exception as e:
                self.service.lg.warning(
                    "state hook failed", extra={"exception": e, "hook": hook}
                )
        return old
