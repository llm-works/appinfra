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
    State.STOPPED: {State.INITD, State.STARTING, State.DONE},
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


@dataclass
class RestartPolicy:
    """Defines restart behavior for failed services.

    Attributes:
        max_retries: Maximum restart attempts before giving up.
        backoff: Initial backoff delay in seconds.
        backoff_multiplier: Multiplier for exponential backoff.
        max_backoff: Maximum backoff delay cap.
        restart_on_failure: Whether to attempt restarts at all.
    """

    max_retries: int = 3
    backoff: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff: float = 60.0
    restart_on_failure: bool = True
