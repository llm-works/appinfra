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
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from typing import TypeVar, overload

from .. import time as infratime
from ..log import Logger, LoggerFactory
from .errors import (
    CorruptObjectError,
    InvalidNameError,
    ObjectNotFoundError,
    ObjectTypeError,
    RefConflictError,
)
from .objects import (
    Commit,
    Link,
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

    Logs to ``<lg>/cas``, never above debug except for a ``warning`` when cleanup finds
    what a crashed writer left behind. Errors are raised, not logged.
    """

    def __init__(self, lg: Logger) -> None:
        """Log to a ``cas`` logger derived from ``lg``."""
        self._lg = LoggerFactory.derive(lg, "cas")

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

    def object_types(
        self, repo: str, object_ids: Iterable[str]
    ) -> dict[str, ObjectType]:
        """
        Return the type of each of ``object_ids`` that is stored; absent ids are left out.

        :class:`Repo` checks an object's links with one call. The default calls
        :meth:`object_type` once per id; a backend with a cheaper bulk lookup (one query
        for all ids) overrides it.
        """
        found: dict[str, ObjectType] = {}
        for object_id in object_ids:
            object_type = self.object_type(repo, object_id)
            if object_type is not None:
                found[object_id] = object_type
        return found

    def write_objects(
        self, repo: str, objects: Sequence[tuple[str, ObjectType, bytes]]
    ) -> None:
        """
        Store ``(object_id, object_type, data)`` objects, each as :meth:`write_object` does.

        :meth:`Repo.batch` passes children before the objects pointing at them. A backend
        must keep that order on storage, or make the objects visible all at once (one
        transaction), so a crash never leaves an object without its links. The default
        calls :meth:`write_object` once per object, in order; a backend that can write
        several objects for less than one each overrides it.
        """
        for object_id, object_type, data in objects:
            self.write_object(repo, object_id, object_type, data)

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

    def now(self) -> float:
        """
        Return the current time (epoch secs) on the clock that write times use.

        :meth:`Repo.prune` compares :meth:`list_objects` times against it, so a backend
        whose write times come from another clock (a database server's) returns that
        clock here. The default is the local clock.
        """
        return time.time()

    def sweep(self, repo: str, cutoff: float) -> int:
        """
        Remove backend leftovers last touched before ``cutoff`` (epoch secs); return how many.

        Called by :meth:`Repo.prune` under the exclusive lock, so no write through
        :class:`Repo` is in progress. A backend that leaves nothing behind, such as temp
        files of a writer that died, keeps this default, which removes nothing.
        """
        return 0


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
        self._lg = store._lg

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

        What ``obj`` points at (a tree's entries, a commit's tree and parents, a vector
        node's children) must already be in the repository with the right type, so a
        stored object never points at nothing. The check and the write hold the
        repository's shared lock, so :meth:`prune` cannot delete a link in between. To
        store several objects at once, use :meth:`batch`.

        Raises:
            ObjectNotFoundError: A referenced object is missing.
            ObjectTypeError: A referenced object has another type.
        """
        object_id, data = obj.id, obj.serialize()
        with self._store.lock(self._name):
            self._require_links(obj.links(), {})
            self._store.write_object(self._name, object_id, obj.type, data)
        return object_id

    def batch(self) -> AbstractContextManager[Batch]:
        """
        Return a context manager whose :class:`Batch` stores its objects at the block's end.

        Every object put on the batch is written when the ``with`` block ends, under one
        hold of the shared lock, with one lookup for all their links and one
        :meth:`Store.write_objects` call. An exception inside the block writes nothing.
        Refs move afterwards, as usual::

            with repo.batch() as batch:
                blob_id = batch.put(Blob(b"hello"))
                tree_id = batch.put(Tree((TreeEntry("greeting", "blob", blob_id),)))
            repo.commit("main", tree_id)
        """
        return _batch(self)

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

    def _require_links(
        self, links: Sequence[Link], pending: Mapping[str, ObjectType]
    ) -> None:
        """
        Raise unless every link is in ``pending`` or stored, with its required type.

        ``pending`` maps the ids of objects about to be written with them to their types.
        Stored ids are looked up with one :meth:`Store.object_types` call. The first bad
        link, in order, raises.
        """
        lookup = [link_id for link_id, _ in links if link_id not in pending]
        stored = self._store.object_types(self._name, dict.fromkeys(lookup))
        for link_id, link_type in links:
            actual = pending.get(link_id) or stored.get(link_id)
            if actual is None:
                raise ObjectNotFoundError(self._name, link_id)
            if link_type is not None and actual != link_type:
                raise ObjectTypeError(self._name, link_id, link_type, actual)

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
            moved = self._store.write_ref(self._name, name, new, old)
        if moved:
            self._lg.trace(
                "moved ref",
                extra={"repo": self._name, "ref": name, "old": old, "new": new},
            )
        return moved

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
            deleted = self._store.write_ref(self._name, name, None, old)
        if deleted:
            self._lg.trace(
                "deleted ref", extra={"repo": self._name, "ref": name, "old": old}
            )
        return deleted

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
            self._lg.trace(
                "ref moved under commit",
                extra={"repo": self._name, "ref": ref, "expected": tip},
            )
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
        start_t = infratime.start()
        with self._store.lock(self._name, exclusive=True):
            cutoff = self._store.now() - expire
            stored = self._store.list_objects(self._name)
            recent = [oid for oid, mtime in stored.items() if mtime > cutoff]
            roots = [*self._store.list_refs(self._name).values(), *recent]
            reachable = self._reachable(roots)
            garbage = [oid for oid in stored if oid not in reachable]
            self._store.delete_objects(self._name, self._referrers_first(garbage))
            swept = self._store.sweep(self._name, cutoff)
        self._lg.debug(
            "pruned",
            extra={
                "repo": self._name,
                "deleted": len(garbage),
                "kept": len(stored) - len(garbage),
                "swept": swept,
                "after": infratime.since(start_t),
            },
        )
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
        try:
            obj = self.get(object_id)
        except CorruptObjectError:
            self._lg.warning(
                "pruning a corrupt object",
                extra={"repo": self._name, "object_id": object_id},
            )
            return []
        return [link_id for link_id, _ in _links(obj)]

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


def _links(obj: Object | None) -> list[Link]:
    """Return the ids and required types of the objects ``obj`` points at."""
    return obj.links() if obj is not None else []


class Batch:
    """
    Objects queued to be stored together; obtained from :meth:`Repo.batch`.

    :meth:`put` queues an object and returns its id; nothing is written until the batch's
    ``with`` block ends. A queued object may point at objects queued before or after it
    and at objects already stored; they are written children first. :meth:`get` sees
    queued objects, so code that builds on what it just put (a
    :class:`~appinfra.cas.vector.Vector` edited twice in one batch) reads them back
    before they are stored. After the block, reads go to the repository and :meth:`put`
    raises.
    """

    def __init__(self, repo: Repo) -> None:
        self._repo = repo
        self._pending: dict[str, Object] = {}
        self._closed = False

    @property
    def repo(self) -> Repo:
        """The repository the batch writes to."""
        return self._repo

    def put(self, obj: Object) -> str:
        """
        Queue ``obj`` and return its id; queuing the same object again is harmless.

        Raises:
            RuntimeError: The batch's block has ended.
        """
        if self._closed:
            raise RuntimeError("batch is closed")
        object_id = obj.id
        self._pending.setdefault(object_id, obj)
        return object_id

    @overload
    def get(self, object_id: str) -> Object | None:
        """Return the object of any type."""

    @overload
    def get(self, object_id: str, cls: type[T]) -> T | None:
        """Return the object as ``cls``."""

    def get(self, object_id: str, cls: type[Object] | None = None) -> Object | None:
        """Return a queued object, else what :meth:`Repo.get` returns."""
        obj = self._pending.get(object_id)
        if obj is None:
            return (
                self._repo.get(object_id)
                if cls is None
                else self._repo.get(object_id, cls)
            )
        if cls is not None and not isinstance(obj, cls):
            raise ObjectTypeError(self._repo.name, object_id, cls.type, obj.type)
        return obj

    def __len__(self) -> int:
        """Number of objects queued."""
        return len(self._pending)

    def _write(self) -> None:
        """Check every queued object's links and store them all, children first."""
        order = _children_first(self._pending)
        types = {object_id: obj.type for object_id, obj in self._pending.items()}
        links = [link for obj in order for link in obj.links()]
        repo, store = self._repo, self._repo._store
        with store.lock(repo.name):
            repo._require_links(links, types)
            store.write_objects(
                repo.name, [(obj.id, obj.type, obj.serialize()) for obj in order]
            )
        repo._lg.trace("wrote batch", extra={"repo": repo.name, "objects": len(order)})


def _children_first(objects: Mapping[str, Object]) -> list[Object]:
    """Order ``objects`` so each comes after the objects among them it points at."""
    order: list[Object] = []
    done: set[str] = set()
    for root_id in objects:
        stack: list[tuple[str, bool]] = [(root_id, False)]
        while stack:
            object_id, expanded = stack.pop()
            if expanded:
                order.append(objects[object_id])
            elif object_id not in done:
                done.add(object_id)
                stack.append((object_id, True))
                stack.extend(
                    (link_id, False)
                    for link_id, _ in reversed(objects[object_id].links())
                    if link_id in objects and link_id not in done
                )
    return order


@contextmanager
def _batch(repo: Repo) -> Iterator[Batch]:
    """Yield a batch; write it if the block ends normally, drop it if it raises."""
    batch = Batch(repo)
    try:
        yield batch
        batch._write()
    finally:
        batch._closed = True
        batch._pending.clear()
