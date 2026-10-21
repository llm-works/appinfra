# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""In-memory :class:`~appinfra.cas.store.Store`: for tests and single-process use."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from ..log import Logger
from .objects import ObjectType
from .store import Store


@dataclass
class _Repo:
    """One repository's objects (id to type, data, write time) and refs."""

    objects: dict[str, tuple[ObjectType, bytes, float]] = field(default_factory=dict)
    refs: dict[str, str] = field(default_factory=dict)


class _SharedExclusiveLock:
    """
    Many shared holders or one exclusive holder.

    A waiting exclusive request blocks new shared holders, so a steady stream of
    writers cannot starve a prune.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._shared = 0
        self._exclusive = False
        self._waiting = 0

    @contextmanager
    def hold(self, exclusive: bool) -> Iterator[None]:
        """Hold the lock, shared or exclusive, for the block."""
        with self._cond:
            if exclusive:
                self._waiting += 1
                self._cond.wait_for(lambda: not self._exclusive and self._shared == 0)
                self._waiting -= 1
                self._exclusive = True
            else:
                self._cond.wait_for(lambda: not self._exclusive and self._waiting == 0)
                self._shared += 1
        try:
            yield
        finally:
            with self._cond:
                if exclusive:
                    self._exclusive = False
                else:
                    self._shared -= 1
                self._cond.notify_all()


class MemoryStore(Store):
    """Repositories held in a dict; thread-safe, gone when the process ends."""

    def __init__(self, lg: Logger) -> None:
        super().__init__(lg)
        self._lock = threading.Lock()
        self._repos: dict[str, _Repo] = {}
        self._repo_locks: dict[str, _SharedExclusiveLock] = {}

    @contextmanager
    def lock(self, repo: str, exclusive: bool = False) -> Iterator[None]:
        """Hold the repository's lock, shared or exclusive, for the block."""
        with self._lock:
            repo_lock = self._repo_locks.setdefault(repo, _SharedExclusiveLock())
        with repo_lock.hold(exclusive):
            yield

    def delete_repo(self, name: str) -> None:
        """Delete the repository ``name`` under its exclusive lock; no-op if absent."""
        with self.lock(name, exclusive=True), self._lock:
            deleted = self._repos.pop(name, None) is not None
        if deleted:
            self._lg.debug("deleted repository", extra={"repo": name})

    def list_repos(self) -> list[str]:
        """Return the names of the repositories holding an object or a ref, sorted."""
        with self._lock:
            return sorted(
                name for name, data in self._repos.items() if data.objects or data.refs
            )

    def read_object(self, repo: str, object_id: str) -> tuple[ObjectType, bytes] | None:
        """Return the type and serialized bytes of an object, or ``None``."""
        with self._lock:
            found = self._repos.get(repo, _Repo()).objects.get(object_id)
        return None if found is None else (found[0], found[1])

    def object_type(self, repo: str, object_id: str) -> ObjectType | None:
        """Return the type of an object, or ``None``."""
        with self._lock:
            found = self._repos.get(repo, _Repo()).objects.get(object_id)
        return None if found is None else found[0]

    def write_object(
        self, repo: str, object_id: str, object_type: ObjectType, data: bytes
    ) -> None:
        """Store an object; rewriting an existing one refreshes its write time."""
        with self._lock:
            objects = self._repos.setdefault(repo, _Repo()).objects
            objects[object_id] = (object_type, bytes(data), time.time())

    def list_objects(self, repo: str) -> dict[str, float]:
        """Return every object id of the repository with its last write time."""
        with self._lock:
            objects = self._repos.get(repo, _Repo()).objects
            return {object_id: mtime for object_id, (_, _, mtime) in objects.items()}

    def delete_objects(self, repo: str, object_ids: Iterable[str]) -> None:
        """Delete the given objects; missing ids are skipped."""
        with self._lock:
            objects = self._repos.get(repo, _Repo()).objects
            for object_id in object_ids:
                objects.pop(object_id, None)

    def read_ref(self, repo: str, name: str) -> str | None:
        """Return the object id ref ``name`` points at, or ``None``."""
        with self._lock:
            return self._repos.get(repo, _Repo()).refs.get(name)

    def write_ref(self, repo: str, name: str, new: str | None, old: str | None) -> bool:
        """Point ref ``name`` at ``new`` (``None``: delete) if it points at ``old``."""
        with self._lock:
            refs = self._repos.get(repo, _Repo()).refs
            if refs.get(name) != old:
                return False
            if new is None:
                refs.pop(name, None)
            else:
                self._repos.setdefault(repo, _Repo()).refs[name] = new
            return True

    def list_refs(self, repo: str) -> dict[str, str]:
        """Return every ref of the repository."""
        with self._lock:
            return dict(self._repos.get(repo, _Repo()).refs)
