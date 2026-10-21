# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Content-addressed store errors."""

from __future__ import annotations

from ..errors import InfraError


class CasError(InfraError):
    """Base error for content-addressed store operations."""


class ObjectNotFoundError(CasError):
    """An object the operation needs is not in the repository."""

    def __init__(self, repo: str, object_id: str) -> None:
        super().__init__(f"object {object_id} not found", repo=repo)
        self.repo = repo
        self.object_id = object_id


class ObjectTypeError(CasError):
    """An object exists but has a different type than the operation needs."""

    def __init__(self, repo: str, object_id: str, expected: str, actual: str) -> None:
        super().__init__(
            f"object {object_id} is a {actual}, not a {expected}", repo=repo
        )
        self.repo = repo
        self.object_id = object_id
        self.expected = expected
        self.actual = actual


class CorruptObjectError(CasError):
    """Stored bytes do not parse as an object of their type."""

    def __init__(self, object_type: str, reason: str) -> None:
        super().__init__(f"corrupt {object_type}: {reason}")
        self.object_type = object_type


class RefConflictError(CasError):
    """A ref no longer points where the writer expected: another writer moved it."""

    def __init__(self, repo: str, ref: str, expected: str | None) -> None:
        super().__init__(f"ref {ref} no longer points at {expected}", repo=repo)
        self.repo = repo
        self.ref = ref
        self.expected = expected


class InvalidNameError(CasError, ValueError):
    """A repository or ref name is empty or unusable as a name."""

    def __init__(self, what: str, name: object) -> None:
        super().__init__(f"invalid {what} name: {name!r}")
        self.name = name
