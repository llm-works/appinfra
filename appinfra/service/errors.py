# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Service errors."""

from __future__ import annotations

from typing import Any

from appinfra.errors import InfraError


class Error(InfraError):
    """Base error for service operations.

    It pickles whole, as an isolated service's process sends its errors to
    the parent: unpickling does not call a subclass's __init__, whose
    arguments are not those Exception keeps (its args hold the message), but
    restores the message and the attributes as they were."""

    def __reduce__(self) -> tuple[Any, ...]:
        return (_restore, (type(self), self.args, self.__dict__))


def _restore(cls: type[Error], args: tuple[Any, ...], state: dict[str, Any]) -> Error:
    """An Error of type *cls* with *args* and the attributes *state*, as it
    was pickled; see Error.__reduce__()."""
    error = cls.__new__(cls)
    Exception.__init__(error, *args)
    error.__dict__.update(state)
    return error


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

    @classmethod
    def of(cls, name: str, error: Exception) -> SetupError:
        """*error*, which service *name*'s setup() raised, as a SetupError:
        itself if it is one, else a new one caused by it."""
        if isinstance(error, SetupError):
            return error
        wrapped = cls(name, str(error))
        wrapped.__cause__ = error
        return wrapped


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


class DependencyNotRunningError(Error, TimeoutError):
    """A service still waited for a dependency to run when the wait for it ended."""

    def __init__(self, name: str, dependency: str) -> None:
        self.name = name
        self.dependency = dependency
        super().__init__(f"{name}: dependency '{dependency}' is not running")


class InvalidTransitionError(Error):
    """Invalid state transition attempted."""

    def __init__(self, name: str, from_state: object, to_state: object) -> None:
        self.service_name = name
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"{name}: invalid transition {from_state} -> {to_state}")
