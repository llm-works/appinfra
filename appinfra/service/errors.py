# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Service errors."""

from typing import Any

from appinfra.errors import InfraError


class Error(InfraError):
    """Base error for service operations."""

    pass


class CycleError(Error):
    """Dependency cycle detected in service graph."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        path = " → ".join(cycle + [cycle[0]])
        super().__init__(f"Dependency cycle detected: {path}")


class SetupError(Error):
    """Service setup() failed."""

    def __init__(self, name: str, message: str) -> None:
        self.service_name = name
        super().__init__(f"{name}: setup failed: {message}")


class RunError(Error):
    """Service run() failed."""

    def __init__(self, name: str, message: str) -> None:
        self.service_name = name
        super().__init__(f"{name}: {message}")


class HealthTimeoutError(Error, TimeoutError):
    """Service health check timed out."""

    def __init__(self, name: str, timeout: float) -> None:
        self.service_name = name
        self.timeout = timeout
        super().__init__(f"{name}: health check timed out after {timeout}s")


class DependencyFailedError(Error):
    """A dependency failed to start."""

    def __init__(self, name: str, dependency: str) -> None:
        self.service_name = name
        self.dependency = dependency
        super().__init__(f"{name}: dependency '{dependency}' failed to start")


class InvalidTransitionError(Error):
    """Invalid state transition attempted."""

    def __init__(self, name: str, from_state: object, to_state: object) -> None:
        self.service_name = name
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"{name}: invalid transition {from_state} -> {to_state}")


# Channel errors


class ChannelError(Error):
    """Base error for channel operations."""


class ChannelTimeoutError(ChannelError, TimeoutError):
    """
    Timeout waiting for message.

    Also a builtin TimeoutError, so generic ``except TimeoutError`` handlers
    (and handlers registered for TimeoutError) catch channel timeouts.
    """


class ChannelClosedError(ChannelError):
    """Channel has been closed."""


class ChannelResponseError(ChannelError):
    """
    Response message carried an error.

    ``response`` is the message as received, so callers can read fields
    beyond the error text, e.g. a status that tells a rejection from a failure.
    """

    def __init__(self, response: Any) -> None:
        self.response = response
        super().__init__(f"Request failed: {response.error}")


class ChannelFullError(ChannelError, BlockingIOError):
    """
    Outbound queue stayed full for the whole send timeout.

    Also a builtin BlockingIOError, so generic ``except BlockingIOError``
    handlers catch channel full errors.
    """
