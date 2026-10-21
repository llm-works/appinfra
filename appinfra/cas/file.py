# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Filesystem :class:`~appinfra.cas.store.Store`: one directory per repository.

Layout under the root::

    <root>/<repo>/
        objects/<id[:2]>/<id[2:]>    "<type> <length>\\0" followed by the serialized bytes
        refs/<ref>                   the object id the ref points at
        repo.lock                    flock: shared for writers, exclusive for prune and delete
        refs.lock                    flock held while a ref is compared and written
        tmp/                         files being written, renamed into place when complete

Repository and ref names are URL-quoted into one path segment, so a ``/`` in a ref name
is part of the name. A quoted ref name must fit 255 bytes and a quoted repository name
214 (room for the delete rename); each byte outside ``A-Z a-z 0-9 - . _ ~`` takes three.
Longer names raise :class:`~appinfra.cas.errors.InvalidNameError`. Every file is written to ``tmp/``, fsynced and renamed into place,
so a reader never sees a partial file. Each rename, unlink and new directory is flushed
to its parent directory before the call returns, so a completed write or delete survives
power loss and prune's delete order holds on disk. The locks are ``flock`` locks, which hold across
threads and processes on a local filesystem, not on NFS.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import cast, get_args
from urllib.parse import quote, unquote

from .errors import CorruptObjectError, InvalidNameError
from .objects import ObjectType, is_object_id
from .store import Store, check_id, check_name

_HEADER_MAX = 32
"""Upper bound of an object header: ``commit`` plus a 20-digit length plus NUL."""

_DELETED = "%deleted-"
"""Infix of a repository directory being deleted; quote() never writes lowercase escapes."""

_MAX_REF_SEGMENT = 255
"""Longest quoted ref name: the usual filesystem limit on one path segment."""

_MAX_REPO_SEGMENT = _MAX_REF_SEGMENT - len(_DELETED) - 32
"""Longest quoted repository name: room for the rename that :meth:`delete_repo` does."""


def _segment(what: str, name: str, limit: int) -> str:
    """URL-quote ``name`` into one path segment; raise if it would be longer than ``limit``."""
    segment = quote(check_name(what, name), safe="")
    if len(segment) > limit:
        raise InvalidNameError(what, name)
    return segment


def _has_content(repo_dir: Path) -> bool:
    """True when a repository directory holds a ref or an object."""
    refs_dir, objects_dir = repo_dir / "refs", repo_dir / "objects"
    if refs_dir.is_dir() and any(refs_dir.iterdir()):
        return True
    if not objects_dir.is_dir():
        return False
    return any(any(fan_out.iterdir()) for fan_out in objects_dir.iterdir())


def _parse_header(raw: bytes, repo: str, object_id: str) -> tuple[ObjectType, int, int]:
    """Return the type, the data length and the data offset of a stored object."""
    head, sep, _ = raw[:_HEADER_MAX].partition(b"\0")
    type_name, _, length = head.decode("ascii", errors="replace").partition(" ")
    if not sep or type_name not in get_args(ObjectType) or not length.isdigit():
        raise CorruptObjectError(
            "object",
            f"bad header {head[:_HEADER_MAX]!r}",
            repo=repo,
            object_id=object_id,
        )
    return cast(ObjectType, type_name), int(length), len(head) + 1


def _fsync_dir(path: Path, fsync: bool) -> None:
    """Flush a directory's entries, so a create, rename or unlink in it survives power loss."""
    if not fsync:
        return
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _makedirs(path: Path, fsync: bool) -> None:
    """Create ``path`` and its missing parents, each one flushed to its parent directory."""
    missing: list[Path] = []
    while not path.is_dir():
        missing.append(path)
        path = path.parent
    for directory in reversed(missing):
        with contextlib.suppress(FileExistsError):
            directory.mkdir()
        _fsync_dir(directory.parent, fsync)


def _is_current(fd: int, path: Path) -> bool:
    """True when ``fd`` is still the file at ``path`` (not renamed away or deleted)."""
    try:
        on_disk = os.stat(path)
    except FileNotFoundError:
        return False
    held = os.fstat(fd)
    return (held.st_dev, held.st_ino) == (on_disk.st_dev, on_disk.st_ino)


@contextlib.contextmanager
def _locked(lock_file: Path, exclusive: bool, fsync: bool) -> Iterator[None]:
    """
    Hold a ``flock`` on ``lock_file`` (created with its directory if absent) for the block.

    Each call opens its own file description, so the lock also excludes other threads
    of the same process. If the file was renamed away or deleted while this call waited
    (:meth:`FileStore.delete_repo` renames the directory holding it), the lock it got
    guards nothing: it is released and the file at ``lock_file`` is locked instead.
    """
    while True:
        _makedirs(lock_file.parent, fsync)
        fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            if _is_current(fd, lock_file):
                yield
                return
        finally:
            os.close(fd)


class FileStore(Store):
    """Repositories as directories under ``root``; safe across threads and processes."""

    def __init__(self, root: str | os.PathLike[str], *, fsync: bool = True) -> None:
        """
        Use ``root`` as the store's directory; it is created by the first write.

        With ``fsync=False`` nothing is flushed to disk: writes are still atomic and
        locked, but a power loss can lose or reorder them. Meant for test suites, where
        flushing dominates the run time.
        """
        self._root = Path(root)
        self._fsync = fsync

    # -- repositories -----------------------------------------------------------

    @contextlib.contextmanager
    def lock(self, repo: str, exclusive: bool = False) -> Iterator[None]:
        """Hold ``repo.lock``, shared or exclusive, for the block."""
        with _locked(self._repo_dir(repo) / "repo.lock", exclusive, self._fsync):
            yield

    def delete_repo(self, name: str) -> None:
        """
        Delete the repository's directory under its exclusive lock; no-op if absent.

        The directory is first renamed to a name no repository can have, then removed, so
        a crash leaves either the whole repository or a hidden leftover, never part of it.
        Leftovers of earlier deletes of this name that failed partway are removed too.
        """
        repo_dir = self._repo_dir(name)
        prefix = f"{repo_dir.name}{_DELETED}"
        if repo_dir.is_dir():
            doomed = repo_dir.with_name(f"{prefix}{uuid.uuid4().hex}")
            with self.lock(name, exclusive=True):
                with contextlib.suppress(FileNotFoundError):
                    repo_dir.rename(doomed)
                    _fsync_dir(self._root, self._fsync)
        if self._root.is_dir():
            for leftover in self._root.iterdir():
                if leftover.name.startswith(prefix):
                    with contextlib.suppress(FileNotFoundError):  # a concurrent delete
                        shutil.rmtree(leftover)

    def sweep(self, repo: str, cutoff: float) -> None:
        """Delete temp files of writers that died, last modified before ``cutoff``."""
        tmp_dir = self._repo_dir(repo) / "tmp"
        if not tmp_dir.is_dir():
            return
        for path in tmp_dir.iterdir():
            with contextlib.suppress(FileNotFoundError):
                if path.stat().st_mtime <= cutoff:
                    path.unlink()

    def list_repos(self) -> list[str]:
        """
        Return the names of the repositories holding an object or a ref, sorted.

        Directories that hold neither (left by a lock or a failed write) and leftovers of
        a delete are not repositories.
        """
        if not self._root.is_dir():
            return []
        return sorted(
            unquote(p.name)
            for p in self._root.iterdir()
            if p.is_dir()
            and quote(unquote(p.name), safe="") == p.name
            and _has_content(p)
        )

    # -- objects ----------------------------------------------------------------

    def read_object(self, repo: str, object_id: str) -> tuple[ObjectType, bytes] | None:
        """Return the type and serialized bytes of an object, or ``None``."""
        try:
            raw = self._object_path(repo, object_id).read_bytes()
        except FileNotFoundError:
            return None
        object_type, length, offset = _parse_header(raw, repo, object_id)
        if len(raw) - offset != length:
            raise CorruptObjectError(
                object_type,
                "length does not match header",
                repo=repo,
                object_id=object_id,
            )
        return object_type, raw[offset:]

    def object_type(self, repo: str, object_id: str) -> ObjectType | None:
        """Return the type of an object from its header, or ``None``."""
        try:
            with self._object_path(repo, object_id).open("rb") as f:
                raw = f.read(_HEADER_MAX)
        except FileNotFoundError:
            return None
        return _parse_header(raw, repo, object_id)[0]

    def write_object(
        self, repo: str, object_id: str, object_type: ObjectType, data: bytes
    ) -> None:
        """Store an object; for an existing one, only refresh its modification time."""
        path = self._object_path(repo, object_id)
        with contextlib.suppress(FileNotFoundError):
            os.utime(path)
            return
        header = f"{object_type} {len(data)}\0".encode("ascii")
        self._write_file(repo, path, header, data)

    def list_objects(self, repo: str) -> dict[str, float]:
        """Return every object id of the repository with its modification time."""
        objects: dict[str, float] = {}
        objects_dir = self._repo_dir(repo) / "objects"
        if not objects_dir.is_dir():
            return objects
        for fan_out in objects_dir.iterdir():
            for path in fan_out.iterdir():
                object_id = fan_out.name + path.name
                if is_object_id(object_id):
                    with contextlib.suppress(FileNotFoundError):
                        objects[object_id] = path.stat().st_mtime
        return objects

    def delete_objects(self, repo: str, object_ids: Iterable[str]) -> None:
        """
        Delete the given object files in order; missing ones are skipped.

        Each unlink is flushed before the next, so the order survives power loss too.
        """
        for object_id in object_ids:
            path = self._object_path(repo, object_id)
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
                _fsync_dir(path.parent, self._fsync)

    # -- refs -------------------------------------------------------------------

    def read_ref(self, repo: str, name: str) -> str | None:
        """Return the object id ref ``name`` points at, or ``None``."""
        try:
            return (
                self._ref_path(repo, name).read_text(encoding="ascii").strip() or None
            )
        except FileNotFoundError:
            return None

    def write_ref(self, repo: str, name: str, new: str | None, old: str | None) -> bool:
        """Point ref ``name`` at ``new`` (``None``: delete) if it points at ``old``."""
        path = self._ref_path(repo, name)
        if new is None and not path.parent.is_dir():
            return old is None  # nothing to delete; and nothing gets created
        _makedirs(path.parent, self._fsync)
        with _locked(self._repo_dir(repo) / "refs.lock", True, self._fsync):
            if self.read_ref(repo, name) != old:
                return False
            if new is None:
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
                    _fsync_dir(path.parent, self._fsync)
            else:
                self._write_file(repo, path, check_id(new).encode("ascii"))
            return True

    def list_refs(self, repo: str) -> dict[str, str]:
        """Return every ref of the repository."""
        refs_dir = self._repo_dir(repo) / "refs"
        if not refs_dir.is_dir():
            return {}
        refs: dict[str, str] = {}
        for path in refs_dir.iterdir():
            with contextlib.suppress(FileNotFoundError):
                refs[unquote(path.name)] = path.read_text(encoding="ascii").strip()
        return refs

    # -- paths and writes -------------------------------------------------------

    def _repo_dir(self, repo: str) -> Path:
        """Return ``<root>/<quoted repo>``."""
        return self._root / _segment("repository", repo, _MAX_REPO_SEGMENT)

    def _object_path(self, repo: str, object_id: str) -> Path:
        """Return ``objects/<id[:2]>/<id[2:]>`` under the repository."""
        object_id = check_id(object_id)
        return self._repo_dir(repo) / "objects" / object_id[:2] / object_id[2:]

    def _ref_path(self, repo: str, name: str) -> Path:
        """Return ``refs/<quoted name>`` under the repository."""
        return self._repo_dir(repo) / "refs" / _segment("ref", name, _MAX_REF_SEGMENT)

    def _write_file(self, repo: str, target: Path, *chunks: bytes) -> None:
        """
        Write ``chunks`` to a temp file, fsync it, rename it to ``target``, fsync the dir.

        When this returns, the file and its name survive power loss (unless ``fsync=False``).
        """
        tmp_dir = self._repo_dir(repo) / "tmp"
        _makedirs(tmp_dir, self._fsync)
        _makedirs(target.parent, self._fsync)
        fd, tmp_path = tempfile.mkstemp(dir=tmp_dir)
        try:
            with os.fdopen(fd, "wb") as f:
                for chunk in chunks:
                    f.write(chunk)
                f.flush()
                if self._fsync:
                    os.fsync(f.fileno())
            os.replace(tmp_path, target)
            _fsync_dir(target.parent, self._fsync)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
