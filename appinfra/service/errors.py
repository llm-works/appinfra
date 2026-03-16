"""Service errors."""

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


class HealthTimeoutError(Error):
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


class ChannelTimeoutError(ChannelError):
    """Timeout waiting for message."""


class ChannelClosedError(ChannelError):
    """Channel has been closed."""
