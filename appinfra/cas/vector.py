# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Vectors: lists of object ids stored as trees of chunks, so a new version of a list
stores only what changed.

A :class:`Vector` is an immutable list of object ids. Its elements live in leaf
:class:`~appinfra.cas.objects.VectorNode` chunks, with interior nodes above them, so a
version shares every unchanged chunk with the versions before it. Appending stores the
new elements' leaf and the path above it; replacing or deleting a range stores the chunks
around the range; a point edit stores one path.

Where a chunk ends depends on the ids in it, not on positions: an entry whose id's first
32 bits are divisible by :data:`BOUNDARY_MODULUS` ends its chunk, once the chunk holds
:data:`CHUNK_MIN` entries; a chunk that reaches
:data:`~appinfra.cas.objects.VECTOR_NODE_MAX` entries ends there. Interior levels are
chunked the same way over their child ids. So:

- The same list always gives the same root id, however it was edited into shape.
- Dropping or replacing a prefix rewrites the chunks at the cut, not every chunk after
  it, as position-based chunking would.
- Every chunk but the last of its level holds at least :data:`CHUNK_MIN` entries,
  whatever the ids: a run of one id cannot make a chunk per element.

These three numbers are part of the format: changing them changes every root id.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from .errors import CorruptObjectError, ObjectNotFoundError
from .objects import VECTOR_NODE_MAX, VectorNode
from .store import Batch, Repo, check_id

CHUNK_MIN = 16
"""Fewest entries in a chunk other than the last of its level."""

BOUNDARY_MODULUS = 48
"""An entry whose id's first 32 bits are divisible by this ends its chunk (mean ~63)."""

Source = Repo | Batch
"""Where a vector reads and writes its nodes: a repository, or a batch of one."""

_Entry = tuple[str, int]
"""One entry of a level: an id and the number of elements under it (1 in a leaf)."""


class Splice(NamedTuple):
    """Replace the elements ``start:stop`` of a vector with ``ids``."""

    start: int
    stop: int
    ids: tuple[str, ...]


@dataclass
class _Frame:
    """A node on a path from the root, and the index of the entry the path is at."""

    node: VectorNode
    idx: int


def _is_boundary(entry_id: str) -> bool:
    """True when ``entry_id`` ends its chunk (once the chunk is long enough)."""
    return int(entry_id[:8], 16) % BOUNDARY_MODULUS == 0


def _entries(node: VectorNode) -> list[_Entry]:
    """Return a node's entries: (element id, 1) in a leaf, (child id, count) above."""
    if node.level == 0:
        return [(child, 1) for child in node.children]
    return list(zip(node.children, node.counts))


class _Chunker:
    """Cuts a stream of entries of one level into nodes."""

    def __init__(self, level: int) -> None:
        self.level = level
        self.pending: list[_Entry] = []
        self.nodes: list[VectorNode] = []

    def add(self, entry: _Entry) -> None:
        """Add an entry; end the node here if the chunk rule says so."""
        self.pending.append(entry)
        size = len(self.pending)
        if size >= CHUNK_MIN and (size >= VECTOR_NODE_MAX or _is_boundary(entry[0])):
            self._close()

    def flush(self) -> None:
        """End the last node: the level ends."""
        if self.pending:
            self._close()

    def _close(self) -> None:
        children = tuple(child for child, _ in self.pending)
        counts = tuple(count for _, count in self.pending) if self.level else ()
        self.nodes.append(VectorNode(self.level, children, counts))
        self.pending = []


def _chunk(level: int, entries: Iterable[_Entry]) -> list[VectorNode]:
    """Cut a whole level into nodes."""
    chunker = _Chunker(level)
    for entry in entries:
        chunker.add(entry)
    chunker.flush()
    return chunker.nodes


def _build_up(level: int, nodes: list[VectorNode]) -> list[VectorNode]:
    """Add levels above ``nodes`` (at ``level``) until one node is left; return all new."""
    created: list[VectorNode] = []
    while len(nodes) > 1:
        level += 1
        nodes = _chunk(level, ((node.id, node.count) for node in nodes))
        created.extend(nodes)
    return created


def _build(ids: Sequence[str]) -> tuple[VectorNode, list[VectorNode]]:
    """Build the nodes of a list from scratch; return the root and every node."""
    leaves = _chunk(0, ((element, 1) for element in ids))
    if not leaves:
        empty = VectorNode(0)
        return empty, [empty]
    created = leaves + _build_up(0, leaves)
    return created[-1], created


def _after(frames: list[_Frame]) -> list[_Frame]:
    """Return a copy of ``frames`` moved one entry on at its lowest level."""
    if not frames:
        return []
    return [_Frame(frames[0].node, frames[0].idx + 1), *frames[1:]]


class Vector:
    """
    An immutable list of object ids, stored as a tree of chunks that versions share.

    A vector is its root node's id plus the :class:`~appinfra.cas.store.Repo` or
    :class:`~appinfra.cas.store.Batch` it reads and writes through. Edits return a new
    vector and store only the nodes the new version does not share with this one. With
    a batch, the nodes are written when the batch's block ends; with a repository, each
    is stored right away. Elements are ids of objects of any type, which must be stored
    (or queued on the same batch) when the nodes pointing at them are written.

    Put a vector in a :class:`~appinfra.cas.objects.Tree` entry of type ``"vector"`` to
    commit it, so refs reach it and :meth:`~appinfra.cas.store.Repo.prune` keeps it.
    Two vectors are equal when their roots are: when they hold the same list.
    """

    def __init__(self, source: Source, root: str) -> None:
        """Use the vector whose root node is ``root``; it is read on first use."""
        self._source = source
        self._root_id = check_id(root)
        self._nodes: dict[str, VectorNode] = {}

    @classmethod
    def build(cls, source: Source, ids: Iterable[str]) -> Vector:
        """Store a vector holding ``ids`` and return it."""
        root, created = _build([check_id(element) for element in ids])
        return cls._stored(source, root, created)

    @classmethod
    def empty(cls, source: Source) -> Vector:
        """Store the empty vector and return it."""
        return cls.build(source, ())

    @property
    def id(self) -> str:
        """Id of the root node: the same list always has the same id."""
        return self._root_id

    def on(self, source: Source) -> Vector:
        """Return this vector reading and writing through ``source`` instead."""
        return Vector(source, self._root_id)

    def __repr__(self) -> str:
        """Return ``Vector('<root id>')``."""
        return f"Vector({self._root_id!r})"

    def __eq__(self, other: object) -> bool:
        """True when ``other`` is a vector with the same root: the same list."""
        return isinstance(other, Vector) and other._root_id == self._root_id

    def __hash__(self) -> int:
        """Hash of the root id."""
        return hash(self._root_id)

    # -- reading ----------------------------------------------------------------

    def __len__(self) -> int:
        """Number of elements; reads only the root."""
        return self._root.count

    def __getitem__(self, index: int) -> str:
        """Return the element at ``index`` (negative counts from the end)."""
        size = len(self)
        if index < 0:
            index += size
        if not 0 <= index < size:
            raise IndexError(f"vector index {index} out of range for length {size}")
        frame = self._seek(index)[0]
        return frame.node.children[frame.idx]

    def __iter__(self) -> Iterator[str]:
        """Iterate over the elements, reading one leaf at a time."""
        return self.ids()

    def ids(self, start: int = 0, stop: int | None = None) -> Iterator[str]:
        """Iterate over the elements ``start:stop``, reading only the leaves they are in."""
        stop = len(self) if stop is None else stop
        self._check_range(start, stop)
        return self._iter(start, stop - start)

    def _iter(self, start: int, remaining: int) -> Iterator[str]:
        if not remaining:
            return
        frames = self._seek(start)
        while True:
            leaf = frames[0]
            for element in leaf.node.children[leaf.idx : leaf.idx + remaining]:
                yield element
                remaining -= 1
            if not remaining:
                return
            self._next_node(frames)

    # -- editing ----------------------------------------------------------------

    def append(self, ids: Iterable[str]) -> Vector:
        """Return the vector with ``ids`` added at the end."""
        size = len(self)
        return self.splice(size, size, ids)

    def splice(self, start: int, stop: int, ids: Iterable[str] = ()) -> Vector:
        """
        Return the vector with the elements ``start:stop`` replaced by ``ids``.

        Covers insert (``start == stop``), delete (no ``ids``), replace and point edit.
        Reads the paths to ``start`` and ``stop`` and the chunks the edit touches; the
        cost grows with the size of the edit and the depth of the tree, not the length.
        """
        self._check_range(start, stop)
        items: list[_Entry] = [(check_id(element), 1) for element in ids]
        if start == stop and not items:
            return self
        lower, upper = self._seek(start), self._seek(stop)
        created: list[VectorNode] = []
        while True:
            nodes, lower_up, upper_up = self._rechunk(lower, upper, items)
            created.extend(nodes)
            if not lower_up:
                break
            items = [(node.id, node.count) for node in nodes]
            lower, upper = lower_up, upper_up
        root = self._top(nodes, lower[0].node.level, created)
        return self._stored(self._source, root, created)

    def assign(self, ids: Iterable[str]) -> Vector:
        """
        Return the vector holding ``ids``, sharing every chunk it has in common with this one.

        For a caller that has the whole new list rather than the edit, such as a list
        rebuilt after compaction: the new version stores the same nodes :meth:`splice`
        would. Hashing is linear in the length; reads cover this vector's interior nodes
        only, never its leaves.
        """
        root, created = _build([check_id(element) for element in ids])
        if root.id == self._root_id:
            return self
        known = self._node_ids()
        return self._stored(
            self._source, root, [node for node in created if node.id not in known]
        )

    def diff(self, other: Vector) -> list[Splice]:
        """
        Return splices that turn this vector into ``other``, in ascending order.

        Positions are in this vector; apply them from last to first. Chunks the two share
        are skipped unread; within the chunks that differ, the common start and end are
        trimmed, so a single contiguous edit comes back as exactly that edit. Edits that
        land in the same chunks may come back as one splice covering them.
        """
        if other._root_id == self._root_id:
            return []
        mine, theirs = self._leaves(), other._leaves()
        offsets = [0]
        for _, count in mine:
            offsets.append(offsets[-1] + count)
        matcher = difflib.SequenceMatcher(
            None,
            [leaf for leaf, _ in mine],
            [leaf for leaf, _ in theirs],
            autojunk=False,
        )
        splices: list[Splice] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "equal":
                old = self._elements(leaf for leaf, _ in mine[i1:i2])
                new = other._elements(leaf for leaf, _ in theirs[j1:j2])
                splices.append(_trimmed(offsets[i1], old, new))
        return splices

    # -- nodes ------------------------------------------------------------------

    @property
    def _root(self) -> VectorNode:
        return self._load(self._root_id)

    def _repo_name(self) -> str:
        source = self._source
        return source.repo.name if isinstance(source, Batch) else source.name

    def _load(self, node_id: str) -> VectorNode:
        node = self._nodes.get(node_id)
        if node is None:
            node = self._source.get(node_id, VectorNode)
            if node is None:
                raise ObjectNotFoundError(self._repo_name(), node_id)
            self._nodes[node_id] = node
        return node

    def _child(self, node: VectorNode, idx: int) -> VectorNode:
        """Load child ``idx`` of an interior node; it must sit one level down, as counted."""
        child = self._load(node.children[idx])
        if child.level != node.level - 1 or child.count != node.counts[idx]:
            raise CorruptObjectError(
                "vector",
                "child node does not match its parent's level or count",
                repo=self._repo_name(),
                object_id=node.children[idx],
            )
        return child

    def _check_range(self, start: int, stop: int) -> None:
        size = len(self)
        if not 0 <= start <= stop <= size:
            raise IndexError(f"range {start}:{stop} out of bounds for length {size}")

    def _seek(self, pos: int) -> list[_Frame]:
        """Return the path to element position ``pos`` (0..len), leaf frame first."""
        node, frames = self._root, []
        while node.level:
            last = len(node.counts) - 1
            for idx, count in enumerate(node.counts):
                if pos < count or idx == last:  # pos == len ends in the last child
                    break
                pos -= count
            frames.append(_Frame(node, idx))
            node = self._child(node, idx)
        frames.append(_Frame(node, pos))
        frames.reverse()
        return frames

    def _next_node(self, frames: list[_Frame]) -> bool:
        """Move ``frames`` to the first entry of the next node at its level; False at the end."""
        for k in range(1, len(frames)):
            if frames[k].idx + 1 < len(frames[k].node.children):
                frames[k].idx += 1
                for m in range(k - 1, -1, -1):
                    parent = frames[m + 1]
                    frames[m] = _Frame(self._child(parent.node, parent.idx), 0)
                return True
        return False

    def _rechunk(
        self, lower: list[_Frame], upper: list[_Frame], items: list[_Entry]
    ) -> tuple[list[VectorNode], list[_Frame], list[_Frame]]:
        """
        Replace the entries between ``lower`` and ``upper`` (one level) with ``items``.

        Chunking restarts at the node holding ``lower`` and stops where a new node ends at
        the end of an old one: from there on, old and new chunks are the same. Returns the
        new nodes and, one level up, the positions of the first replaced node and of the
        node after the last one (empty at the root level).
        """
        first = lower[0]
        chunker = _Chunker(first.node.level)
        for entry in [*_entries(first.node)[: first.idx], *items]:
            chunker.add(entry)
        cur = [_Frame(frame.node, frame.idx) for frame in upper]
        while True:
            if cur[0].idx == 0 and not chunker.pending:
                return chunker.nodes, lower[1:], cur[1:]
            for entry in _entries(cur[0].node)[cur[0].idx :]:
                chunker.add(entry)
            if not chunker.pending:
                return chunker.nodes, lower[1:], _after(cur[1:])
            if not self._next_node(cur):
                chunker.flush()
                return chunker.nodes, lower[1:], _after(cur[1:])

    def _top(
        self, nodes: list[VectorNode], level: int, created: list[VectorNode]
    ) -> VectorNode:
        """Return the root over ``nodes``, the new nodes of the old root's level."""
        if not nodes:
            empty = VectorNode(0)
            created.append(empty)
            return empty
        above = _build_up(level, nodes)
        created.extend(above)
        root = above[-1] if above else nodes[0]
        new = {node.id: node for node in created}
        while root.level and len(root.children) == 1:
            child_id = root.children[0]
            root = new[child_id] if child_id in new else self._child(root, 0)
        return root

    @classmethod
    def _stored(
        cls, source: Source, root: VectorNode, created: list[VectorNode]
    ) -> Vector:
        """Store the nodes of ``created`` that ``root`` reaches, children first."""
        new = {node.id: node for node in created}
        order: list[VectorNode] = []
        stack: list[tuple[VectorNode, bool]] = [(root, False)] if root.id in new else []
        seen: set[str] = set()
        while stack:
            node, expanded = stack.pop()
            if expanded:
                order.append(node)
            elif node.id not in seen:
                seen.add(node.id)
                stack.append((node, True))
                if node.level:
                    stack.extend((new[c], False) for c in node.children if c in new)
        for node in order:
            source.put(node)
        vector = cls(source, root.id)
        vector._nodes = {node.id: node for node in order}
        vector._nodes[root.id] = root
        return vector

    def _node_ids(self) -> set[str]:
        """Return the ids of every node of this vector, reading interior nodes only."""
        known = {self._root_id}
        pending = [self._root] if self._root.level else []
        while pending:
            node = pending.pop()
            known.update(node.children)
            if node.level > 1:
                pending.extend(self._child(node, i) for i in range(len(node.children)))
        return known

    def _leaves(self) -> list[tuple[str, int]]:
        """Return (leaf id, element count) of every leaf, in order, reading no leaf."""
        root = self._root
        if not root.level:
            return [(root.id, root.count)]
        leaves: list[tuple[str, int]] = []
        stack = [root]
        while stack:
            node = stack.pop()
            if node.level == 1:
                leaves.extend(zip(node.children, node.counts))
            else:
                stack.extend(
                    self._child(node, i) for i in reversed(range(len(node.children)))
                )
        return leaves

    def _elements(self, leaf_ids: Iterable[str]) -> list[str]:
        """Return the elements of the given leaves, in order."""
        return [element for leaf in leaf_ids for element in self._load(leaf).children]


def _trimmed(offset: int, old: list[str], new: list[str]) -> Splice:
    """Return the splice turning ``old`` (at ``offset``) into ``new``, minus their common ends."""
    head = 0
    while head < min(len(old), len(new)) and old[head] == new[head]:
        head += 1
    tail = 0
    while tail < min(len(old), len(new)) - head and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    return Splice(
        offset + head, offset + len(old) - tail, tuple(new[head : len(new) - tail])
    )
