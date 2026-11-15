# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Repo.batch() and the bulk store primitives it uses."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager

import pytest

from appinfra.cas import (
    Blob,
    Commit,
    MemoryStore,
    ObjectNotFoundError,
    ObjectType,
    ObjectTypeError,
    Tree,
    TreeEntry,
)
from appinfra.log import Logger

LG = Logger("test-cas")


class _Recording(MemoryStore):
    """A store that records lock holds, bulk lookups and bulk writes."""

    def __init__(self) -> None:
        super().__init__(LG)
        self.locks = 0
        self.lookups: list[list[str]] = []
        self.writes: list[list[str]] = []

    @contextmanager
    def lock(self, repo: str, exclusive: bool = False) -> Iterator[None]:
        self.locks += 1
        with super().lock(repo, exclusive):
            yield

    def object_types(
        self, repo: str, object_ids: Iterable[str]
    ) -> dict[str, ObjectType]:
        ids = list(object_ids)
        self.lookups.append(ids)
        return super().object_types(repo, ids)

    def write_objects(
        self, repo: str, objects: Sequence[tuple[str, ObjectType, bytes]]
    ) -> None:
        self.writes.append([object_id for object_id, _, _ in objects])
        super().write_objects(repo, objects)


@pytest.fixture
def store() -> _Recording:
    """A fresh recording store."""
    return _Recording()


def test_nothing_is_stored_before_the_block_ends(store: _Recording) -> None:
    """put() queues; the block's end writes everything with one lock hold and one lookup."""
    repo = store.repo("r")
    with repo.batch() as batch:
        blob = batch.put(Blob(b"x"))
        tree = batch.put(Tree((TreeEntry("x", "blob", blob),)))
        assert len(batch) == 2
        assert store.list_objects("r") == {}
        assert batch.get(tree, Tree) == Tree((TreeEntry("x", "blob", blob),))
    assert set(store.list_objects("r")) == {blob, tree}
    assert (store.locks, len(store.lookups), store.writes) == (1, 1, [[blob, tree]])


def test_children_are_written_first_whatever_the_put_order(store: _Recording) -> None:
    """An object may be queued before the objects it points at."""
    repo = store.repo("r")
    blob = Blob(b"x")
    tree = Tree((TreeEntry("x", "blob", blob.id),))
    commit = Commit(tree.id)
    with repo.batch() as batch:
        for obj in (commit, tree, blob):
            batch.put(obj)
    assert store.writes == [[blob.id, tree.id, commit.id]]
    assert store.lookups == [[]]  # every link was queued: nothing to look up


def test_links_to_stored_objects_are_looked_up_once(store: _Recording) -> None:
    """Links outside the batch are checked with one bulk lookup, each id once."""
    repo = store.repo("r")
    blobs = [repo.put(Blob(f"b{i}".encode())) for i in range(3)]
    store.lookups.clear()
    with repo.batch() as batch:
        entries = tuple(TreeEntry(f"n{i}", "blob", b) for i, b in enumerate(blobs))
        batch.put(Tree(entries))
        batch.put(Tree(entries[:1]))
    assert store.lookups == [blobs]


def test_an_error_in_the_block_writes_nothing(store: _Recording) -> None:
    """Leaving the block by an exception drops the queued objects."""
    repo = store.repo("r")
    with pytest.raises(KeyError), repo.batch() as batch:
        batch.put(Blob(b"x"))
        raise KeyError("stop")
    assert store.list_objects("r") == {} and store.writes == []


def test_a_missing_link_writes_nothing(store: _Recording) -> None:
    """One bad link fails the whole batch before anything is written."""
    repo = store.repo("r")
    with pytest.raises(ObjectNotFoundError), repo.batch() as batch:
        batch.put(Blob(b"fine"))
        batch.put(Tree((TreeEntry("x", "blob", Blob(b"absent").id),)))
    assert store.list_objects("r") == {}


def test_a_link_of_the_wrong_type_writes_nothing(store: _Recording) -> None:
    """Links keep their required type, whether queued or stored."""
    repo = store.repo("r")
    with pytest.raises(ObjectTypeError), repo.batch() as batch:
        blob = batch.put(Blob(b"x"))
        batch.put(Commit(blob))
    assert store.list_objects("r") == {}


def test_closed_batch(store: _Recording) -> None:
    """After the block a batch reads through to the repository and refuses puts."""
    repo = store.repo("r")
    with repo.batch() as batch:
        blob = batch.put(Blob(b"x"))
    assert batch.get(blob) == Blob(b"x") and len(batch) == 0
    assert batch.repo is repo
    with pytest.raises(RuntimeError):
        batch.put(Blob(b"y"))


def test_get_with_the_wrong_class(store: _Recording) -> None:
    """A queued object read as another class raises, as Repo.get does."""
    with store.repo("r").batch() as batch:
        blob = batch.put(Blob(b"x"))
        with pytest.raises(ObjectTypeError):
            batch.get(blob, Tree)


def test_put_checks_links_with_one_lookup(store: _Recording) -> None:
    """Repo.put looks up all of an object's links at once."""
    repo = store.repo("r")
    blobs = [repo.put(Blob(f"b{i}".encode())) for i in range(4)]
    store.lookups.clear()
    repo.put(Tree(tuple(TreeEntry(f"n{i}", "blob", b) for i, b in enumerate(blobs))))
    assert store.lookups == [blobs]
