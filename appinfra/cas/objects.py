# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Content-addressed objects: blobs, trees, commits and vector nodes.

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
- Vector node: one byte for the level, then per entry the 32-byte binary digest of the
  id; an interior node follows each digest with the number of elements under that child,
  as 8 bytes big-endian. Binary, not JSON: a node is nothing but ids, and appending to a
  vector rewrites its last leaf, so the encoding's size is most of what an append costs.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, ClassVar, Literal, Self, get_args

from .errors import CorruptObjectError

ObjectType = Literal["blob", "tree", "commit", "vector"]
"""The type of an object."""

TreeEntryType = Literal["blob", "tree", "vector"]
"""What a tree entry points at: a blob, a subtree or the root node of a vector."""

Link = tuple[str, ObjectType | None]
"""An id an object points at, with the type it must have; ``None`` accepts any type."""

VECTOR_NODE_MAX = 256
"""Most entries in a vector node; :mod:`appinfra.cas.vector` ends a node that reaches it."""

_VECTOR_LEVEL_MAX = 255
"""Highest vector node level: it is stored in one byte."""

_DIGEST = 32
"""Bytes of a binary id."""

_COUNT = 8
"""Bytes of an interior entry's element count."""

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
    """Base of :class:`Blob`, :class:`Tree`, :class:`Commit` and :class:`VectorNode`."""

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

    def links(self) -> list[Link]:
        """Return the ids this object points at, each with the type it must have."""
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
    """One named entry of a tree: a blob, a subtree or a vector, by id."""

    name: str
    type: TreeEntryType
    id: str

    def __post_init__(self) -> None:
        """Reject an empty name, a commit entry and a malformed id."""
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(f"entry name must be a non-empty str: {self.name!r}")
        if self.type not in get_args(TreeEntryType):
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

    def links(self) -> list[Link]:
        """Return the ids and types of the entries this tree points at."""
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

    def links(self) -> list[Link]:
        """Return the ids and types of the tree and parents this commit points at."""
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


@dataclass(frozen=True)
class VectorNode(Object):
    """
    One node of a vector: a leaf holding element ids, or an interior node above them.

    A leaf (``level`` 0) lists the ids of its elements, which can be objects of any type.
    An interior node lists the ids of its child nodes, one level down, in ``children`` and
    the number of elements under each in ``counts``. :class:`~appinfra.cas.vector.Vector`
    builds and reads these; build them by hand only to inspect or test the format.
    """

    type: ClassVar[ObjectType] = "vector"

    level: int
    children: tuple[str, ...] = ()
    counts: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """Store tuples; reject a bad level, malformed ids, too many entries, bad counts."""
        object.__setattr__(self, "children", tuple(self.children))
        object.__setattr__(self, "counts", tuple(self.counts))
        if type(self.level) is not int or not 0 <= self.level <= _VECTOR_LEVEL_MAX:
            raise ValueError(f"level must be an int in 0..255: {self.level!r}")
        if len(self.children) > VECTOR_NODE_MAX:
            raise ValueError(f"{len(self.children)} entries, at most {VECTOR_NODE_MAX}")
        for child in self.children:
            if not is_object_id(child):
                raise ValueError(f"child id {child!r}")
        self._check_counts()

    def _check_counts(self) -> None:
        """A leaf has no counts; an interior node has a positive count per child."""
        if self.level == 0:
            if self.counts:
                raise ValueError("a leaf has no counts")
            return
        if not self.children:
            raise ValueError("an interior node has no children")
        if len(self.counts) != len(self.children):
            raise ValueError("an interior node needs one count per child")
        if any(
            type(n) is not int or not 1 <= n < 2 ** (8 * _COUNT) for n in self.counts
        ):
            raise ValueError(f"counts must be ints in 1..2**64-1: {self.counts!r}")

    @property
    def count(self) -> int:
        """Number of elements under this node."""
        return sum(self.counts) if self.level else len(self.children)

    def serialize(self) -> bytes:
        """Return the bytes the id is computed over."""
        parts = [bytes((self.level,))]
        if self.level == 0:
            parts.extend(bytes.fromhex(child) for child in self.children)
        else:
            for child, count in zip(self.children, self.counts):
                parts.append(bytes.fromhex(child))
                parts.append(count.to_bytes(_COUNT, "big"))
        return b"".join(parts)

    def links(self) -> list[Link]:
        """Return the element ids (any type) of a leaf, the child nodes of an interior node."""
        child_type: ObjectType | None = None if self.level == 0 else "vector"
        return [(child, child_type) for child in self.children]

    @classmethod
    def deserialize(cls, data: bytes) -> VectorNode:
        """Rebuild a vector node from its serialized bytes."""
        if not data:
            raise CorruptObjectError("vector", "no level byte")
        level, body = data[0], data[1:]
        width = _DIGEST if level == 0 else _DIGEST + _COUNT
        if len(body) % width:
            raise CorruptObjectError(
                "vector", f"{len(body)} bytes of entries, not a multiple of {width}"
            )
        entries = [body[i : i + width] for i in range(0, len(body), width)]
        children = tuple(entry[:_DIGEST].hex() for entry in entries)
        counts = (
            tuple(int.from_bytes(entry[_DIGEST:], "big") for entry in entries)
            if level
            else ()
        )
        try:
            return cls(level, children, counts)
        except ValueError as e:  # invalid content read back is corruption
            raise CorruptObjectError("vector", str(e)) from e


_CLASSES: dict[str, type[Object]] = {
    "blob": Blob,
    "tree": Tree,
    "commit": Commit,
    "vector": VectorNode,
}


def deserialize(object_type: ObjectType, data: bytes) -> Object:
    """Rebuild an object of ``object_type`` from its serialized bytes."""
    return _CLASSES[object_type].deserialize(data)
