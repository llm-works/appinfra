# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Content-addressed objects: blobs, trees and commits.

An object's id is the sha256 hex digest of ``"<type> <length>\\0"`` followed by its
serialized bytes. The type is part of the hashed bytes, so a blob and a tree with the
same bytes get different ids, and an id alone names one object.

Serialization:

- Blob: the data as given.
- Tree: canonical JSON of ``[[name, type, id], ...]`` sorted by name, so entry names can
  be any string.
- Commit: a ``tree <id>`` line and one ``parent <id>`` line per parent, a blank line,
  then the payload bytes. There is no author or timestamp, so identical content gives the
  identical commit; the payload is opaque bytes the caller owns.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, ClassVar, Literal, Self

from .errors import CorruptObjectError

ObjectType = Literal["blob", "tree", "commit"]
"""The type of an object."""

TreeEntryType = Literal["blob", "tree"]
"""What a tree entry points at: a blob or a subtree."""

_OBJECT_ID = re.compile(r"[0-9a-f]{64}")


def is_object_id(value: object) -> bool:
    """True when ``value`` has the form of an object id: 64 lowercase hex characters."""
    return isinstance(value, str) and _OBJECT_ID.fullmatch(value) is not None


def content_hash(object_type: ObjectType, data: bytes) -> str:
    """Return the id of an object of ``object_type`` whose serialized bytes are ``data``."""
    digest = hashlib.sha256(f"{object_type} {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


def canonical_json(obj: Any) -> bytes:
    """
    Serialize ``obj`` to canonical UTF-8 JSON: sorted keys, compact separators.

    The same value always gives the same bytes, so its hash is stable. Use it to build
    blob data or commit payloads from structured values. NaN and infinities raise
    ``ValueError``: they have no JSON form.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


class Object(ABC):
    """Base of :class:`Blob`, :class:`Tree` and :class:`Commit`."""

    type: ClassVar[ObjectType]

    @cached_property
    def id(self) -> str:
        """Content hash of the object."""
        return content_hash(self.type, self.serialize())

    @abstractmethod
    def serialize(self) -> bytes:
        """Return the bytes the id is computed over."""

    @classmethod
    @abstractmethod
    def deserialize(cls, data: bytes) -> Self:
        """Rebuild the object from its serialized bytes."""

    def links(self) -> list[tuple[str, ObjectType]]:
        """Return the (id, type) pairs of objects this object points at."""
        return []


@dataclass(frozen=True)
class Blob(Object):
    """Opaque bytes."""

    type: ClassVar[ObjectType] = "blob"

    data: bytes

    def serialize(self) -> bytes:
        """Return the bytes the id is computed over."""
        return self.data

    @classmethod
    def deserialize(cls, data: bytes) -> Blob:
        """Rebuild a blob from its serialized bytes."""
        return cls(data)


@dataclass(frozen=True)
class TreeEntry:
    """One named entry of a tree: a blob or a subtree, by id."""

    name: str
    type: TreeEntryType
    id: str

    def __post_init__(self) -> None:
        """Reject an empty name, a commit entry and a malformed id."""
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(f"entry name must be a non-empty str: {self.name!r}")
        if self.type not in ("blob", "tree"):
            raise ValueError(f"entry {self.name!r} has type {self.type!r}")
        if not is_object_id(self.id):
            raise ValueError(f"entry {self.name!r} has id {self.id!r}")


@dataclass(frozen=True)
class Tree(Object):
    """
    Named entries pointing at blobs and subtrees, like a directory.

    Entries are kept sorted by name, so the same entries in any order give the same tree.
    Names are unique.
    """

    type: ClassVar[ObjectType] = "tree"

    entries: tuple[TreeEntry, ...] = field(default=())

    def __post_init__(self) -> None:
        """Sort the entries by name and reject duplicate names."""
        entries = tuple(sorted(self.entries, key=lambda e: e.name))
        for prev, curr in zip(entries, entries[1:]):
            if prev.name == curr.name:
                raise ValueError(f"duplicate entry name {curr.name!r}")
        object.__setattr__(self, "entries", entries)

    def get(self, name: str) -> TreeEntry | None:
        """Return the entry named ``name``, or ``None``."""
        if not self.entries:
            return None
        idx = bisect.bisect_left(self.entries, name, key=lambda e: e.name)
        if idx < len(self.entries) and self.entries[idx].name == name:
            return self.entries[idx]
        return None

    def serialize(self) -> bytes:
        """Return the bytes the id is computed over."""
        return canonical_json([[e.name, e.type, e.id] for e in self.entries])

    def links(self) -> list[tuple[str, ObjectType]]:
        """Return the (id, type) pairs of entries this tree points at."""
        return [(entry.id, entry.type) for entry in self.entries]

    @classmethod
    def deserialize(cls, data: bytes) -> Tree:
        """Rebuild a tree from its serialized bytes."""
        try:
            body = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise CorruptObjectError("tree", f"not JSON: {e}") from e
        if not isinstance(body, list) or not all(
            isinstance(e, list) and len(e) == 3 for e in body
        ):
            raise CorruptObjectError("tree", "expected a list of [name, type, id]")
        try:
            return cls(tuple(TreeEntry(name, type_, id_) for name, type_, id_ in body))
        except (
            ValueError
        ) as e:  # invalid content read back is corruption, not caller error
            raise CorruptObjectError("tree", str(e)) from e


@dataclass(frozen=True)
class Commit(Object):
    """
    A tree, the commits it follows, and caller-owned payload bytes.

    ``parents`` is empty for a root commit; more than one parent is a merge.
    """

    type: ClassVar[ObjectType] = "commit"

    tree: str
    parents: tuple[str, ...] = ()
    payload: bytes = b""

    def __post_init__(self) -> None:
        """Store parents as a tuple; reject malformed ids and duplicate parents."""
        object.__setattr__(self, "parents", tuple(self.parents))
        if not is_object_id(self.tree):
            raise ValueError(f"tree id {self.tree!r}")
        for parent in self.parents:
            if not is_object_id(parent):
                raise ValueError(f"parent id {parent!r}")
        if len(set(self.parents)) != len(self.parents):
            raise ValueError("duplicate parent")

    def serialize(self) -> bytes:
        """Return the bytes the id is computed over."""
        lines = [f"tree {self.tree}"] + [f"parent {p}" for p in self.parents]
        return ("\n".join(lines) + "\n\n").encode("ascii") + self.payload

    def links(self) -> list[tuple[str, ObjectType]]:
        """Return the (id, type) pairs of the tree and parents this commit points at."""
        return [(self.tree, "tree"), *((parent, "commit") for parent in self.parents)]

    @classmethod
    def deserialize(cls, data: bytes) -> Commit:
        """Rebuild a commit from its serialized bytes."""
        header, sep, payload = data.partition(b"\n\n")
        if not sep:
            raise CorruptObjectError("commit", "no blank line after the header")
        try:
            lines = header.decode("ascii").split("\n")
        except UnicodeDecodeError as e:
            raise CorruptObjectError("commit", "header is not ASCII") from e
        if not lines[0].startswith("tree "):
            raise CorruptObjectError("commit", "header does not start with a tree line")
        if not all(line.startswith("parent ") for line in lines[1:]):
            raise CorruptObjectError("commit", "unexpected header line")
        parents = tuple(line[len("parent ") :] for line in lines[1:])
        try:
            return cls(lines[0][len("tree ") :], parents, payload)
        except (
            ValueError
        ) as e:  # invalid content read back is corruption, not caller error
            raise CorruptObjectError("commit", str(e)) from e


_CLASSES: dict[str, type[Object]] = {"blob": Blob, "tree": Tree, "commit": Commit}


def deserialize(object_type: ObjectType, data: bytes) -> Object:
    """Rebuild an object of ``object_type`` from its serialized bytes."""
    return _CLASSES[object_type].deserialize(data)
