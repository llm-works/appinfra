# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Service state and restart policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class State(Enum):
    """Service lifecycle states."""

    CREATED = "created"
    INITD = "initd"
    STARTING = "starting"
    RUNNING = "running"
    IDLE = "idle"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    DONE = "done"


# Valid state transitions
TRANSITIONS: dict[State, set[State]] = {
    State.CREATED: {State.INITD, State.FAILED, State.DONE},
    State.INITD: {State.STARTING, State.DONE},
    State.STARTING: {State.RUNNING, State.FAILED, State.STOPPING},
    State.RUNNING: {State.IDLE, State.STOPPING, State.FAILED, State.DONE},
    State.IDLE: {State.RUNNING, State.STOPPING, State.FAILED},
    State.STOPPING: {State.STOPPED, State.FAILED, State.DONE},
    # FAILED: a start whose setup() fails, as from CREATED
    State.STOPPED: {State.INITD, State.STARTING, State.FAILED, State.DONE},
    State.FAILED: {
        State.INITD,
        State.STARTING,
        State.STOPPING,
        State.STOPPED,
        State.DONE,
    },
    State.DONE: set(),  # Terminal state
}

# Hook signature: (service_name, from_state, to_state) -> None
StateHook = Callable[[str, State, State], None]


@dataclass(frozen=True)
class RestartPolicy:
    """Defines restart and stop behavior for a service.

    Frozen: one policy is shared by every runner given it (and the default by
    every runner given none), so a change to one would change them all. Use
    dataclasses.replace() for a variant.

    Attributes:
        max_retries: Maximum restart attempts before giving up.
        backoff: Initial backoff delay in seconds.
        backoff_multiplier: Multiplier for exponential backoff.
        max_backoff: Maximum backoff delay cap.
        restart_on_failure: Whether to attempt restarts at all.
        stop_timeout: Seconds an isolated service's run gets to end once the
            runtime stops it on its own (a failed health check, a ready()
            given up on), before its process is terminated. stop_service()
            and stop() give their own timeout instead.
    """

    max_retries: int = 3
    backoff: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff: float = 60.0
    restart_on_failure: bool = True
    stop_timeout: float = 5.0

    def __post_init__(self) -> None:
        """Refuse a negative stop_timeout, which would reach Task.stop() only
        on the runtime's task, when the service is stopped.

        Raises:
            ValueError: If stop_timeout is negative.
        """
        if self.stop_timeout < 0:
            raise ValueError(f"stop_timeout must not be negative: {self.stop_timeout}")
