# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Repositories of content-addressed objects with named refs.

A :class:`Store` holds repositories by name. Each repository has its own objects and
refs, so deleting a repository deletes everything in it and nothing else. Callers work
through :class:`Repo`; the abstract methods of :class:`Store` are the storage primitives
a backend implements.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager
from typing import TypeVar, overload

from .errors import (
    CorruptObjectError,
    InvalidNameError,
    ObjectNotFoundError,
    ObjectTypeError,
    RefConflictError,
)
from .objects import (
    Commit,
    Object,
    ObjectType,
    content_hash,
    deserialize,
    is_object_id,
)

T = TypeVar("T", bound=Object)

MAX_NAME_BYTES = 255
"""Longest repository or ref name, in UTF-8 bytes. A backend may allow less."""


def check_name(what: str, name: object) -> str:
    """
    Return ``name`` if it can name a repository or ref; raise :class:`InvalidNameError`.

    A name is a non-empty string of at most :data:`MAX_NAME_BYTES` UTF-8 bytes, other
    than ``.`` and ``..``, without NUL.
    """
    if not isinstance(name, str) or not name or name in (".", "..") or "\0" in name:
        raise InvalidNameError(what, name)
    try:
        size = len(name.encode("utf-8"))
    except UnicodeEncodeError:  # lone surrogates
        raise InvalidNameError(what, name) from None
    if size > MAX_NAME_BYTES:
        raise InvalidNameError(what, name)
    return name


def check_id(object_id: object) -> str:
    """Return ``object_id`` if it has the form of an object id; raise :class:`InvalidNameError`."""
    if not is_object_id(object_id):
        raise InvalidNameError("object id", object_id)
    return str(object_id)


class Store(ABC):
    """
    Repositories of objects and refs.

    Subclasses implement the storage primitives below; every primitive takes the
    repository name first. A repository exists while it holds an object or a ref; reads,
    locks and failed writes do not make it appear in :meth:`list_repos`. A backend must make
    :meth:`write_ref` atomic: of concurrent writers passing the same ``old``, at most one
    succeeds. :meth:`lock` must exclude across every thread and process that can open the
    store.
    """

    def repo(self, name: str) -> Repo:
        """Return the repository ``name``; it is created by its first write."""
        return Repo(self, check_name("repository", name))

    @abstractmethod
    def lock(self, repo: str, exclusive: bool = False) -> AbstractContextManager[None]:
        """
        Hold the repository's lock for the block: shared, or exclusive.

        :class:`Repo` writes under the shared lock, so a write that checks an object's
        links and then stores it is one step. :meth:`Repo.prune` and :meth:`delete_repo`
        hold it exclusively, so nothing is written while they decide what to delete.
        Shared holders do not exclude each other. Not reentrant.
        """

    @abstractmethod
    def delete_repo(self, name: str) -> None:
        """
        Delete the repository ``name`` with all its objects and refs; no-op if absent.

        Holds the repository's exclusive lock while deleting.
        """

    @abstractmethod
    def list_repos(self) -> list[str]:
        """Return the names of the repositories holding an object or a ref, sorted."""

    @abstractmethod
    def read_object(self, repo: str, object_id: str) -> tuple[ObjectType, bytes] | None:
        """Return the type and serialized bytes of an object, or ``None`` if absent."""

    @abstractmethod
    def object_type(self, repo: str, object_id: str) -> ObjectType | None:
        """Return the type of an object without reading its data, or ``None`` if absent."""

    @abstractmethod
    def write_object(
        self, repo: str, object_id: str, object_type: ObjectType, data: bytes
    ) -> None:
        """
        Store an object under ``object_id``.

        Idempotent. When the object already exists, its write time is refreshed, so
        :meth:`Repo.prune` treats it as recent again.
        """

    @abstractmethod
    def list_objects(self, repo: str) -> dict[str, float]:
        """Return every object id of the repository with its last write time (epoch secs)."""

    @abstractmethod
    def delete_objects(self, repo: str, object_ids: Iterable[str]) -> None:
        """
        Delete the given objects in the given order; ids that do not exist are skipped.

        :meth:`Repo.prune` passes referrers before the objects they point at, so a crash
        partway leaves no stored object pointing at a deleted one.
        """

    @abstractmethod
    def read_ref(self, repo: str, name: str) -> str | None:
        """Return the object id ref ``name`` points at, or ``None`` if it does not exist."""

    @abstractmethod
    def write_ref(self, repo: str, name: str, new: str | None, old: str | None) -> bool:
        """
        Point ref ``name`` at ``new`` if it currently points at ``old``.

        ``old=None`` means the ref must not exist; ``new=None`` deletes it. Returns whether
        the write landed. Must be atomic.
        """

    @abstractmethod
    def list_refs(self, repo: str) -> dict[str, str]:
        """Return every ref of the repository: name to object id."""

    def sweep(self, repo: str, cutoff: float) -> None:  # noqa: B027 - optional hook
        """
        Remove backend leftovers last touched before ``cutoff`` (epoch secs).

        Called by :meth:`Repo.prune` under the exclusive lock, so no write through
        :class:`Repo` is in progress. A backend that leaves nothing behind, such as temp
        files of a writer that died, keeps this no-op.
        """


class Repo:
    """
    One repository of a :class:`Store`: put and get objects, move refs, walk history.

    Obtained from :meth:`Store.repo`. Objects are immutable and identified by content, so
    putting an object twice is harmless. Refs are the only mutable state; they move only
    with compare-and-set, so a second writer is detected instead of silently overwriting.
    """

    def __init__(self, store: Store, name: str) -> None:
        self._store = store
        self._name = name

    @property
    def name(self) -> str:
        """Repository name."""
        return self._name

    def __repr__(self) -> str:
        """Return ``Repo('<name>')``."""
        return f"Repo({self._name!r})"

    # -- objects ----------------------------------------------------------------

    def put(self, obj: Object) -> str:
        """
        Store ``obj`` and return its id.

        A tree's entries and a commit's tree and parents must already be in the
        repository with the right type, so a stored object never points at nothing. The
        check and the write hold the repository's shared lock, so :meth:`prune` cannot
        delete a link in between.

        Raises:
            ObjectNotFoundError: A referenced object is missing.
            ObjectTypeError: A referenced object has another type.
        """
        object_id, data = obj.id, obj.serialize()
        with self._store.lock(self._name):
            for link_id, link_type in _links(obj):
                self._require(link_id, link_type)
            self._store.write_object(self._name, object_id, obj.type, data)
        return object_id

    @overload
    def get(self, object_id: str) -> Object | None:
        """Return the object of any type."""

    @overload
    def get(self, object_id: str, cls: type[T]) -> T | None:
        """Return the object as ``cls``."""

    def get(self, object_id: str, cls: type[Object] | None = None) -> Object | None:
        """
        Return the object ``object_id``, or ``None`` if absent.

        With ``cls``, the object must be of that class. The stored bytes are hashed again
        and must give ``object_id``, so damaged storage raises instead of returning wrong
        content.

        Raises:
            ObjectTypeError: ``cls`` is given and the object is of another type.
            CorruptObjectError: The stored bytes do not hash to ``object_id``.
        """
        found = self._store.read_object(self._name, check_id(object_id))
        if found is None:
            return None
        object_type, data = found
        if content_hash(object_type, data) != object_id:
            raise CorruptObjectError(
                object_type,
                "content does not match id",
                repo=self._name,
                object_id=object_id,
            )
        obj = deserialize(object_type, data)
        if cls is not None and not isinstance(obj, cls):
            raise ObjectTypeError(self._name, object_id, cls.type, object_type)
        return obj

    def __contains__(self, object_id: object) -> bool:
        """True when ``object_id`` is an object of this repository."""
        if not is_object_id(object_id):
            return False
        return self._store.object_type(self._name, str(object_id)) is not None

    def _require(self, object_id: str, object_type: ObjectType) -> None:
        """Raise unless ``object_id`` is stored with type ``object_type``."""
        actual = self._store.object_type(self._name, object_id)
        if actual is None:
            raise ObjectNotFoundError(self._name, object_id)
        if actual != object_type:
            raise ObjectTypeError(self._name, object_id, object_type, actual)

    # -- refs -------------------------------------------------------------------

    def get_ref(self, name: str) -> str | None:
        """Return the commit id ref ``name`` points at, or ``None`` if it does not exist."""
        return self._store.read_ref(self._name, check_name("ref", name))

    def set_ref(self, name: str, new: str, old: str | None) -> bool:
        """
        Point ref ``name`` at commit ``new`` if it currently points at ``old``.

        ``old=None`` means the ref must not exist yet. Returns ``False``, writing nothing,
        when the ref points elsewhere: another writer moved it.

        Raises:
            ObjectNotFoundError: ``new`` is not in the repository.
            ObjectTypeError: ``new`` is not a commit.
        """
        name, new = check_name("ref", name), check_id(new)
        with self._store.lock(self._name):
            self._require(new, "commit")
            return self._store.write_ref(self._name, name, new, old)

    def delete_ref(self, name: str, old: str) -> bool:
        """
        Delete ref ``name`` if it points at ``old``; ``False`` when it points elsewhere.

        Holds the shared lock, so it cannot interleave with :meth:`prune` or
        :meth:`Store.delete_repo`.
        """
        name, old = check_name("ref", name), check_id(old)
        if self._store.read_ref(self._name, name) != old:
            return False  # also spares locking, and so touching, an unknown repository
        with self._store.lock(self._name):
            return self._store.write_ref(self._name, name, None, old)

    def refs(self, prefix: str = "") -> dict[str, str]:
        """Return the refs whose name starts with ``prefix``, sorted by name."""
        refs = self._store.list_refs(self._name)
        return {name: refs[name] for name in sorted(refs) if name.startswith(prefix)}

    def commit(self, ref: str, tree: str, payload: bytes = b"") -> str:
        """
        Add a commit of ``tree`` on top of ref ``ref`` and move the ref to it.

        The parent is the ref's current commit; a ref that does not exist yet gets a root
        commit. Returns the new commit's id.

        Raises:
            RefConflictError: Another writer moved the ref meanwhile. The commit is stored
                but no ref points at it.
        """
        tip = self.get_ref(ref)
        commit_id = self.put(Commit(tree, (tip,) if tip else (), payload))
        if not self.set_ref(ref, commit_id, tip):
            raise RefConflictError(self._name, ref, tip)
        return commit_id

    # -- history ----------------------------------------------------------------

    def ancestors(self, *commit_ids: str) -> Iterator[Commit]:
        """
        Yield the commits ``commit_ids`` and every commit they descend from, each once.

        Follows all parents. A commit comes before all of its parents. Each commit is
        read once; ``commit.id`` gives its id.

        Raises:
            ObjectNotFoundError: A commit in the history is missing.
            ObjectTypeError: An id in the history is not a commit.
        """
        commits = self._load_history(commit_ids)
        children: dict[str, int] = dict.fromkeys(commits, 0)
        for commit in commits.values():
            for parent in commit.parents:
                children[parent] += 1
        ready = deque(cid for cid in dict.fromkeys(commit_ids) if children[cid] == 0)
        while ready:
            commit_id = ready.popleft()
            yield commits[commit_id]
            for parent in commits[commit_id].parents:
                children[parent] -= 1
                if children[parent] == 0:
                    ready.append(parent)

    def first_parents(self, commit_id: str) -> Iterator[Commit]:
        """
        Yield ``commit_id`` and then each first parent, back to a root commit.

        Lazy: one commit is read per step, so a caller that stops early (say, at the first
        commit with what it needs) reads only that far back. Other parents of a merge are
        not followed; :meth:`ancestors` covers the whole history.

        Raises:
            ObjectNotFoundError: A commit on the line is missing.
            ObjectTypeError: An id on the line is not a commit.
        """
        next_id: str | None = check_id(commit_id)
        while next_id is not None:
            commit = self.get(next_id, Commit)
            if commit is None:
                raise ObjectNotFoundError(self._name, next_id)
            yield commit
            next_id = commit.parents[0] if commit.parents else None

    def _load_history(self, commit_ids: Iterable[str]) -> dict[str, Commit]:
        """Load ``commit_ids`` and all their ancestors, keyed by id."""
        commits: dict[str, Commit] = {}
        pending = [check_id(cid) for cid in commit_ids]
        while pending:
            commit_id = pending.pop()
            if commit_id in commits:
                continue
            commit = self.get(commit_id, Commit)
            if commit is None:
                raise ObjectNotFoundError(self._name, commit_id)
            commits[commit_id] = commit
            pending.extend(commit.parents)
        return commits

    def prune(self, expire: float) -> int:
        """
        Delete objects that are unreachable and were last written over ``expire`` secs ago.

        Kept: everything a ref reaches, and everything a recent object (written within
        ``expire``) reaches, so a tree or commit still waiting for its ref keeps what it
        points at, however old. Runs under the repository's exclusive lock, so writers
        wait and nothing is written while it decides. Afterwards every stored object's
        links are still stored. A commit held without a ref for longer than ``expire`` is
        deleted; keep a ref on anything to retain. With ``expire=0`` everything without a
        ref goes, including objects a writer has stored but not yet referenced. Returns
        how many objects were deleted.

        Raises:
            ObjectNotFoundError: An object to keep is missing; nothing is deleted.
        """
        if expire < 0:
            raise ValueError(f"expire must be >= 0, got {expire}")
        if self._name not in self._store.list_repos():
            return 0  # nothing to prune; don't create the repository by locking it
        with self._store.lock(self._name, exclusive=True):
            cutoff = time.time() - expire
            stored = self._store.list_objects(self._name)
            recent = [oid for oid, mtime in stored.items() if mtime > cutoff]
            roots = [*self._store.list_refs(self._name).values(), *recent]
            reachable = self._reachable(roots)
            garbage = [oid for oid in stored if oid not in reachable]
            self._store.delete_objects(self._name, self._referrers_first(garbage))
            self._store.sweep(self._name, cutoff)
        return len(garbage)

    def _referrers_first(self, object_ids: list[str]) -> list[str]:
        """Order ``object_ids`` so each comes before the objects among them it points at."""
        among = set(object_ids)
        links = {
            oid: [lid for lid in self._link_ids(oid) if lid in among]
            for oid in object_ids
        }
        referrers = dict.fromkeys(object_ids, 0)
        for targets in links.values():
            for target in targets:
                referrers[target] += 1
        ready = [oid for oid in object_ids if referrers[oid] == 0]
        order: list[str] = []
        while ready:
            object_id = ready.pop()
            order.append(object_id)
            for target in links[object_id]:
                referrers[target] -= 1
                if referrers[target] == 0:
                    ready.append(target)
        return order

    def _link_ids(self, object_id: str) -> list[str]:
        """Return the ids ``object_id`` points at; a blob is not read, it points at nothing."""
        if self._store.object_type(self._name, object_id) == "blob":
            return []
        return [link_id for link_id, _ in _links(self.get(object_id))]

    def _reachable(self, roots: Iterable[str]) -> set[str]:
        """Return ``roots`` and the ids of every object they reach."""
        reachable: set[str] = set()
        pending = list(roots)
        while pending:
            object_id = pending.pop()
            if object_id in reachable:
                continue
            object_type = self._store.object_type(self._name, object_id)
            if object_type is None:
                raise ObjectNotFoundError(self._name, object_id)
            reachable.add(object_id)
            if object_type != "blob":
                obj = self.get(object_id)
                pending.extend(link_id for link_id, _ in _links(obj))
        return reachable


def _links(obj: Object | None) -> list[tuple[str, ObjectType]]:
    """Return the ids and required types of the objects ``obj`` points at."""
    return obj.links() if obj is not None else []
