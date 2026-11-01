# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Prune deletes referrers first, so a crash partway leaves no dangling link."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from appinfra.cas import Blob, Commit, MemoryStore, Repo, Tree, TreeEntry
from appinfra.cas.conformance import dangling_links
from appinfra.log import Logger

LG = Logger("test-cas")


class _CrashingStore(MemoryStore):
    """Records delete order; raises after ``crash_after`` deletes when set."""

    def __init__(self, crash_after: int | None = None) -> None:
        super().__init__(LG)
        self.deleted: list[str] = []
        self._crash_after = crash_after

    def delete_objects(self, repo: str, object_ids: Iterable[str]) -> None:
        """Delete one by one, recording each; crash when the budget runs out."""
        for object_id in object_ids:
            if self._crash_after is not None and len(self.deleted) == self._crash_after:
                raise RuntimeError("crash")
            super().delete_objects(repo, [object_id])
            self.deleted.append(object_id)


def _orphan_history(repo: Repo) -> list[str]:
    """Two orphan commits on a tree with a subtree; return all six object ids."""
    blob = repo.put(Blob(b"leaf"))
    sub = repo.put(Tree((TreeEntry("leaf", "blob", blob),)))
    top = repo.put(Tree((TreeEntry("sub", "tree", sub),)))
    first = repo.put(Commit(top, (), b"1"))
    second = repo.put(Commit(top, (first,), b"2"))
    other = repo.put(Blob(b"loose"))
    return [blob, sub, top, first, second, other]


def test_referrers_deleted_before_their_links() -> None:
    """Every object is deleted before anything it points at."""
    store = _CrashingStore()
    repo = store.repo("r")
    blob, sub, top, first, second, _ = _orphan_history(repo)
    assert repo.prune(expire=0) == 6
    position = {object_id: i for i, object_id in enumerate(store.deleted)}
    for referrer, target in [
        (second, first),
        (second, top),
        (first, top),
        (top, sub),
        (sub, blob),
    ]:
        assert position[referrer] < position[target]


@pytest.mark.parametrize("crash_after", range(6))
def test_crash_partway_leaves_no_dangling_link(crash_after: int) -> None:
    """Whenever prune dies, the remaining objects' links are all stored."""
    store = _CrashingStore(crash_after)
    repo = store.repo("r")
    _orphan_history(repo)
    with pytest.raises(RuntimeError):
        repo.prune(expire=0)
    assert len(store.deleted) == crash_after
    assert dangling_links(store, "r") == []
