# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Conformance tests every :class:`~appinfra.cas.store.Store` must pass.

A store's test module subclasses :class:`StoreConformance` as ``Test...`` and provides two
fixtures: ``store``, a fresh, empty store, and ``age``, a callable
``age(repo, object_id, seconds)`` that moves an object's write time ``seconds`` into the
past::

    from appinfra.cas.conformance import StoreConformance

    class TestMyStore(StoreConformance):
        @pytest.fixture
        def store(self, tmp_path):
            return MyStore(tmp_path)

        @pytest.fixture
        def age(self, store):
            def age(repo, object_id, seconds):
                ...  # move the object's stored write time back by `seconds`
            return age

The class name has no ``Test`` prefix, so pytest collects it only through subclasses.
Requires pytest.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest

from .errors import (
    CorruptObjectError,
    InvalidNameError,
    ObjectNotFoundError,
    ObjectTypeError,
    RefConflictError,
)
from .objects import Blob, Commit, Tree, TreeEntry
from .store import Repo, Store, _links


def dangling_links(store: Store, repo: str) -> list[tuple[str, str]]:
    """Return ``(object, missing link)`` pairs among a repository's stored objects."""
    stored = store.list_objects(repo)
    pairs: list[tuple[str, str]] = []
    for object_id in stored:
        obj = store.repo(repo).get(object_id)
        pairs.extend(
            (object_id, link_id) for link_id, _ in _links(obj) if link_id not in stored
        )
    return pairs


def _tree(repo: Repo, **files: bytes) -> str:
    """Put a blob per keyword and a tree naming them; return the tree id."""
    entries = [
        TreeEntry(name, "blob", repo.put(Blob(data))) for name, data in files.items()
    ]
    return repo.put(Tree(tuple(entries)))


Age = Callable[[str, str, float], None]
"""``age(repo, object_id, seconds)``: move an object's write time into the past."""

_HOLD = 0.3
"""Seconds a test waits to see that a blocked call stays blocked."""


def _blocked_while(store: Store, exclusive: bool, call: Callable[[], object]) -> bool:
    """Run ``call`` in a thread while holding the lock; True if it waited for the release."""
    thread = threading.Thread(target=call)
    with store.lock("r", exclusive=exclusive):
        thread.start()
        thread.join(_HOLD)
        blocked = thread.is_alive()
    thread.join(5.0)
    assert not thread.is_alive(), "call did not finish after the lock was released"
    return blocked


class StoreConformance:
    """Store tests; subclasses supply the ``store`` and ``age`` fixtures."""

    # -- objects ----------------------------------------------------------------

    def test_put_get_round_trip(self, store: Store) -> None:
        """Each object type comes back equal to what was put."""
        repo = store.repo("r")
        blob = Blob(b"data")
        tree = Tree((TreeEntry("f", "blob", repo.put(blob)),))
        commit = Commit(repo.put(tree), (), b"payload")
        assert repo.put(commit) == commit.id
        assert repo.get(blob.id) == blob
        assert repo.get(tree.id) == tree
        assert repo.get(commit.id) == commit

    def test_put_is_idempotent(self, store: Store) -> None:
        """Putting the same object twice stores it once."""
        repo = store.repo("r")
        assert repo.put(Blob(b"x")) == repo.put(Blob(b"x"))
        assert len(store.list_objects("r")) == 1

    def test_get_absent_returns_none(self, store: Store) -> None:
        """An unknown id is not an error."""
        assert store.repo("r").get(Blob(b"never put").id) is None

    def test_get_with_class_checks_type(self, store: Store) -> None:
        """get(id, cls) returns that class or raises ObjectTypeError."""
        repo = store.repo("r")
        blob_id = repo.put(Blob(b"x"))
        assert repo.get(blob_id, Blob) == Blob(b"x")
        with pytest.raises(ObjectTypeError):
            repo.get(blob_id, Commit)

    def test_get_rejects_malformed_id(self, store: Store) -> None:
        """An id that is not 64 hex characters is refused, not looked up."""
        with pytest.raises(InvalidNameError):
            store.repo("r").get("../escape")

    def test_contains(self, store: Store) -> None:
        """``id in repo`` reflects presence; a malformed id is simply absent."""
        repo = store.repo("r")
        blob_id = repo.put(Blob(b"x"))
        assert blob_id in repo
        assert Blob(b"y").id not in repo
        assert "not-an-id" not in repo

    def test_tree_entries_must_exist(self, store: Store) -> None:
        """A tree cannot point at a missing object or at the wrong type."""
        repo = store.repo("r")
        with pytest.raises(ObjectNotFoundError):
            repo.put(Tree((TreeEntry("f", "blob", Blob(b"missing").id),)))
        blob_id = repo.put(Blob(b"x"))
        with pytest.raises(ObjectTypeError):
            repo.put(Tree((TreeEntry("d", "tree", blob_id),)))

    def test_commit_links_must_exist(self, store: Store) -> None:
        """A commit's tree and parents must be stored with the right type."""
        repo = store.repo("r")
        tree_id = _tree(repo, f=b"x")
        with pytest.raises(ObjectNotFoundError):
            repo.put(Commit(Tree().id))
        with pytest.raises(ObjectTypeError):
            repo.put(Commit(tree_id, (tree_id,)))

    def test_repos_do_not_share_objects(self, store: Store) -> None:
        """An object put in one repository is absent from another."""
        blob_id = store.repo("a").put(Blob(b"x"))
        assert blob_id not in store.repo("b")

    # -- refs -------------------------------------------------------------------

    def test_get_ref_absent(self, store: Store) -> None:
        """A ref that was never set is None."""
        assert store.repo("r").get_ref("main") is None

    def test_set_ref_create_and_move(self, store: Store) -> None:
        """old=None creates; moving needs the current target."""
        repo = store.repo("r")
        c1 = repo.put(Commit(_tree(repo, f=b"1")))
        c2 = repo.put(Commit(_tree(repo, f=b"2"), (c1,)))
        assert repo.set_ref("main", c1, None)
        assert not repo.set_ref("main", c2, None)
        assert repo.set_ref("main", c2, c1)
        assert repo.get_ref("main") == c2

    def test_set_ref_refuses_stale_old(self, store: Store) -> None:
        """A writer with a stale view of the ref changes nothing."""
        repo = store.repo("r")
        c1 = repo.put(Commit(_tree(repo, f=b"1")))
        c2 = repo.put(Commit(_tree(repo, f=b"2"), (c1,)))
        repo.set_ref("main", c2, None)
        assert not repo.set_ref("main", c1, c1)
        assert not repo.set_ref("other", c1, c2)
        assert repo.get_ref("main") == c2
        assert repo.get_ref("other") is None

    def test_set_ref_target_must_be_a_commit(self, store: Store) -> None:
        """A ref points at a stored commit, nothing else."""
        repo = store.repo("r")
        tree_id = _tree(repo, f=b"x")
        with pytest.raises(ObjectTypeError):
            repo.set_ref("main", tree_id, None)
        with pytest.raises(ObjectNotFoundError):
            repo.set_ref("main", Commit(tree_id).id, None)

    def test_delete_ref(self, store: Store) -> None:
        """delete_ref needs the current target."""
        repo = store.repo("r")
        c1 = repo.commit("main", _tree(repo, f=b"1"))
        c2 = repo.commit("main", _tree(repo, f=b"2"))
        assert not repo.delete_ref("main", c1)
        assert repo.delete_ref("main", c2)
        assert repo.get_ref("main") is None

    def test_refs_lists_by_prefix(self, store: Store) -> None:
        """A slash is part of a ref name; refs() filters by prefix and sorts."""
        repo = store.repo("r")
        c = repo.put(Commit(_tree(repo, f=b"x")))
        for name in ("branches/b", "branches/a", "tags/v1", "branches"):
            repo.set_ref(name, c, None)
        assert list(repo.refs("branches/")) == ["branches/a", "branches/b"]
        assert list(repo.refs()) == ["branches", "branches/a", "branches/b", "tags/v1"]

    def test_invalid_names_rejected(self, store: Store) -> None:
        """Empty, '.', '..' and NUL-containing names are refused."""
        for name in ("", ".", "..", "a\0b"):
            with pytest.raises(InvalidNameError):
                store.repo(name)
            with pytest.raises(InvalidNameError):
                store.repo("r").get_ref(name)

    def test_concurrent_moves_have_one_winner(self, store: Store) -> None:
        """Of writers moving a ref from the same commit, exactly one lands."""
        repo = store.repo("r")
        base = repo.commit("main", _tree(repo, f=b"base"))
        heads = [
            repo.put(Commit(_tree(repo, f=str(i).encode()), (base,))) for i in range(16)
        ]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda h: repo.set_ref("main", h, base), heads))
        assert results.count(True) == 1
        assert repo.get_ref("main") == heads[results.index(True)]

    # -- commit -----------------------------------------------------------------

    def test_commit_chains_on_the_ref(self, store: Store) -> None:
        """commit() parents on the ref's tip and moves the ref."""
        repo = store.repo("r")
        c1 = repo.commit("main", _tree(repo, f=b"1"), b"first")
        c2 = repo.commit("main", _tree(repo, f=b"2"), b"second")
        assert repo.get(c1, Commit) == Commit(_tree(repo, f=b"1"), (), b"first")
        commit2 = repo.get(c2, Commit)
        assert commit2 is not None and commit2.parents == (c1,)
        assert repo.get_ref("main") == c2

    def test_identical_content_gives_identical_commit(self, store: Store) -> None:
        """No timestamp: the same tree, parents and payload give the same id."""
        a, b = store.repo("a"), store.repo("b")
        assert a.commit("main", _tree(a, f=b"x"), b"p") == b.commit(
            "main", _tree(b, f=b"x"), b"p"
        )

    def test_commit_conflict_raises(self, store: Store) -> None:
        """commit() raises RefConflictError when the ref moved under it."""
        repo = store.repo("r")
        tree_id = _tree(repo, f=b"x")
        base = repo.commit("main", tree_id)
        other = repo.put(Commit(tree_id, (base,), b"other"))

        real_get_ref = repo.get_ref

        def stale_get_ref(name: str) -> str | None:
            """Read the ref, then move it as a second writer would."""
            tip = real_get_ref(name)
            repo.set_ref(name, other, tip)
            return tip

        repo.get_ref = stale_get_ref  # type: ignore[method-assign]
        with pytest.raises(RefConflictError):
            repo.commit("main", tree_id, b"mine")

    # -- repositories -----------------------------------------------------------

    def test_list_and_delete_repos(self, store: Store) -> None:
        """delete_repo removes one repository's objects and refs, idempotently."""
        for name in ("b", "a"):
            repo = store.repo(name)
            repo.commit("main", _tree(repo, f=name.encode()))
        assert store.list_repos() == ["a", "b"]
        store.delete_repo("a")
        store.delete_repo("a")
        store.delete_repo("never")
        assert store.list_repos() == ["b"]
        assert store.repo("a").get_ref("main") is None
        assert store.list_objects("a") == {}
        assert store.repo("b").get_ref("main") is not None

    # -- history ----------------------------------------------------------------

    def test_ancestors_of_a_merge(self, store: Store) -> None:
        """Every commit once, each before its parents."""
        repo = store.repo("r")
        tree_id = _tree(repo, f=b"x")
        root = repo.put(Commit(tree_id, (), b"root"))
        left = repo.put(Commit(tree_id, (root,), b"left"))
        right = repo.put(Commit(tree_id, (root,), b"right"))
        merge = repo.put(Commit(tree_id, (left, right), b"merge"))
        commits = list(repo.ancestors(merge))
        assert all(isinstance(c, Commit) for c in commits)
        order = [c.id for c in commits]
        assert sorted(order) == sorted([root, left, right, merge])
        assert order[0] == merge and order[-1] == root

    def test_ancestors_of_several_heads(self, store: Store) -> None:
        """Shared history is yielded once."""
        repo = store.repo("r")
        tree_id = _tree(repo, f=b"x")
        root = repo.put(Commit(tree_id, (), b"root"))
        a = repo.put(Commit(tree_id, (root,), b"a"))
        b = repo.put(Commit(tree_id, (root,), b"b"))
        order = [c.id for c in repo.ancestors(a, b, a)]
        assert order[:2] == [a, b] and order[2:] == [root]

    def test_ancestors_missing_commit_raises(self, store: Store) -> None:
        """A history with a hole is reported, not silently cut."""
        repo = store.repo("r")
        base = repo.commit("main", _tree(repo, f=b"x"))
        head = repo.commit("main", _tree(repo, f=b"y"))
        store.delete_objects("r", [base])
        with pytest.raises(ObjectNotFoundError):
            list(repo.ancestors(head))

    # -- prune ------------------------------------------------------------------

    def test_prune_keeps_what_refs_reach(self, store: Store) -> None:
        """Commits, trees, subtrees and blobs a ref reaches survive."""
        repo = store.repo("r")
        sub = _tree(repo, inner=b"inner")
        blob = repo.put(Blob(b"outer"))
        top = repo.put(
            Tree((TreeEntry("sub", "tree", sub), TreeEntry("f", "blob", blob)))
        )
        repo.commit("main", repo.put(Tree()))
        repo.commit("main", top)
        before = set(store.list_objects("r"))
        assert repo.prune(expire=0) == 0
        assert set(store.list_objects("r")) == before

    def test_prune_deletes_unreachable(self, store: Store) -> None:
        """An abandoned commit with its own tree and blob goes; shared objects stay."""
        repo = store.repo("r")
        shared = _tree(repo, f=b"shared")
        base = repo.commit("main", shared)
        orphan = repo.put(Commit(_tree(repo, g=b"orphan"), (base,)))
        assert repo.prune(expire=0) == 3
        assert orphan not in repo
        assert base in repo and shared in repo

    def test_prune_spares_recent_objects(self, store: Store) -> None:
        """Unreachable objects younger than ``expire`` stay."""
        repo = store.repo("r")
        orphan = repo.put(Commit(_tree(repo, f=b"x")))
        assert repo.prune(expire=3600) == 0
        assert orphan in repo

    def test_prune_with_missing_reachable_object_deletes_nothing(
        self, store: Store
    ) -> None:
        """A ref reaching a missing object aborts the prune."""
        repo = store.repo("r")
        blob = repo.put(Blob(b"x"))
        repo.commit("main", repo.put(Tree((TreeEntry("f", "blob", blob),))))
        repo.put(Blob(b"garbage"))
        store.delete_objects("r", [blob])
        with pytest.raises(ObjectNotFoundError):
            repo.prune(expire=0)
        assert Blob(b"garbage").id in repo

    def test_prune_rejects_negative_expire(self, store: Store) -> None:
        """A negative grace window is a caller error."""
        with pytest.raises(ValueError):
            store.repo("r").prune(expire=-1)

    def test_prune_deletes_old_unreachable(self, store: Store, age: Age) -> None:
        """Unreachable objects older than ``expire`` go."""
        repo = store.repo("r")
        tree_id = _tree(repo, f=b"x")
        commit_id = repo.put(Commit(tree_id))
        for object_id in store.list_objects("r"):
            age("r", object_id, 7200)
        assert repo.prune(expire=3600) == 3
        assert commit_id not in repo

    def test_prune_keeps_old_objects_under_recent_ones(
        self, store: Store, age: Age
    ) -> None:
        """A recent tree without a ref keeps its old subtree and blobs."""
        repo = store.repo("r")
        sub = _tree(repo, inner=b"inner")
        for object_id in store.list_objects("r"):
            age("r", object_id, 7200)
        top = repo.put(Tree((TreeEntry("sub", "tree", sub),)))
        assert repo.prune(expire=3600) == 0
        assert {top, sub, Blob(b"inner").id} <= set(store.list_objects("r"))

    def test_put_after_prune_reports_the_missing_link(
        self, store: Store, age: Age
    ) -> None:
        """A writer referencing a pruned object gets an error, not a dangling link."""
        repo = store.repo("r")
        blob_id = repo.put(Blob(b"x"))
        age("r", blob_id, 7200)
        assert repo.prune(expire=3600) == 1
        with pytest.raises(ObjectNotFoundError):
            repo.put(Tree((TreeEntry("f", "blob", blob_id),)))

    # -- locking ----------------------------------------------------------------

    def test_writes_wait_for_the_exclusive_lock(self, store: Store) -> None:
        """put, set_ref and delete_ref block while prune or delete holds the repository."""
        repo = store.repo("r")
        tree_id = _tree(repo, f=b"x")
        commit_id = repo.put(Commit(tree_id))
        assert _blocked_while(store, True, lambda: repo.put(Blob(b"y")))
        assert _blocked_while(
            store, True, lambda: repo.set_ref("main", commit_id, None)
        )
        assert _blocked_while(store, True, lambda: repo.delete_ref("main", commit_id))

    def test_shared_holders_do_not_wait(self, store: Store) -> None:
        """Writers do not exclude each other."""
        repo = store.repo("r")
        assert not _blocked_while(store, False, lambda: repo.put(Blob(b"y")))

    def test_prune_and_delete_wait_for_writers(self, store: Store) -> None:
        """prune and delete_repo block while a writer holds the shared lock."""
        repo = store.repo("r")
        repo.put(Blob(b"x"))
        assert _blocked_while(store, False, lambda: repo.prune(expire=0))
        assert _blocked_while(store, False, lambda: store.delete_repo("r"))

    # -- isolation and names ----------------------------------------------------

    def test_same_bytes_as_blob_and_tree_are_two_objects(self, store: Store) -> None:
        """The type is part of the id, so equal bytes of two types do not collide."""
        repo = store.repo("r")
        blob_id, tree_id = repo.put(Blob(b"[]")), repo.put(Tree())
        assert blob_id != tree_id
        assert repo.get(blob_id) == Blob(b"[]") and repo.get(tree_id) == Tree()

    def test_refs_do_not_leak_across_repos(self, store: Store) -> None:
        """A ref set in one repository does not exist in another."""
        a = store.repo("a")
        a.commit("main", _tree(a, f=b"x"))
        assert store.repo("b").get_ref("main") is None
        assert store.repo("b").refs() == {}

    def test_ref_names_are_not_a_hierarchy(self, store: Store) -> None:
        """'branches' and 'branches/a' are unrelated names."""
        repo = store.repo("r")
        repo.commit("branches/a", _tree(repo, f=b"x"))
        assert repo.get_ref("branches") is None
        assert repo.get_ref("branches/a/b") is None

    def test_unusual_names_round_trip(self, store: Store) -> None:
        """Names that look like paths, escapes or a store's own files are plain names."""
        repo_names = ["a b", "a/b", "é", "x%2Fy", "x%deleted-1", ".hidden", "-"]
        ref_names = [".lock", "refs.lock", "repo.lock", "x.tmp", "tags/v1:2", "é", "%"]
        for name in repo_names:
            repo = store.repo(name)
            tree_id = _tree(repo, f=name.encode())
            for ref in ref_names:
                repo.commit(ref, tree_id)
        assert store.list_repos() == sorted(repo_names)
        assert list(store.repo("a b").refs()) == sorted(ref_names)
        store.delete_repo("x")
        store.delete_repo("x%2Fy")
        assert store.list_repos() == sorted(set(repo_names) - {"x%2Fy"})

    def test_primitives_on_an_unknown_repo(self, store: Store) -> None:
        """Reads of a repository never written are empty, and do not create it."""
        some_id = Blob(b"x").id
        assert store.read_object("r", some_id) is None
        assert store.object_type("r", some_id) is None
        assert store.list_objects("r") == {}
        assert store.read_ref("r", "main") is None
        assert store.list_refs("r") == {}
        store.delete_objects("r", [some_id])
        assert store.repo("r").prune(expire=0) == 0
        assert list(store.repo("r").ancestors()) == []
        assert store.list_repos() == []

    def test_delete_objects_removes_only_the_given_ids(self, store: Store) -> None:
        """Other objects and other repositories are untouched; missing ids are skipped."""
        a, b = store.repo("a"), store.repo("b")
        keep, drop = a.put(Blob(b"keep")), a.put(Blob(b"drop"))
        b.put(Blob(b"drop"))
        store.delete_objects("a", [drop, Blob(b"never").id])
        assert set(store.list_objects("a")) == {keep}
        assert drop in b

    # -- sizes ------------------------------------------------------------------

    def test_empty_and_large_blobs_round_trip(self, store: Store) -> None:
        """Zero bytes and several MiB come back unchanged."""
        repo = store.repo("r")
        large = bytes(range(256)) * (4 * 4096)
        for data in (b"", large):
            assert repo.get(repo.put(Blob(data))) == Blob(data)

    # -- contention -------------------------------------------------------------

    def test_concurrent_puts_of_one_object(self, store: Store) -> None:
        """Many writers storing the same object all succeed; it is stored once."""
        repo = store.repo("r")
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = set(pool.map(lambda _: repo.put(Blob(b"same")), range(32)))
        assert ids == {Blob(b"same").id}
        assert list(store.list_objects("r")) == [Blob(b"same").id]

    def test_interleaved_reads_and_writes_lose_nothing(self, store: Store) -> None:
        """Readers running beside writers neither raise nor hide a completed write."""
        repo = store.repo("r")
        commit_id = repo.put(Commit(_tree(repo, f=b"x")))

        def work(i: int) -> None:
            if i % 2:
                repo.put(Blob(str(i).encode()))
                repo.set_ref(f"ref-{i}", commit_id, None)
            else:
                repo.get_ref(f"ref-{i - 1}")
                _ = Blob(str(i - 1).encode()).id in repo

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(work, range(200)))
        odd = range(1, 200, 2)
        assert all(repo.get_ref(f"ref-{i}") == commit_id for i in odd)
        assert all(Blob(str(i).encode()).id in repo for i in odd)

    def test_concurrent_commits_form_one_chain(self, store: Store) -> None:
        """Writers that retry on RefConflictError line up into one linear history."""
        repo = store.repo("r")

        def commit(i: int) -> str:
            tree_id = _tree(repo, f=str(i).encode())
            while True:
                try:
                    return repo.commit("main", tree_id, str(i).encode())
                except RefConflictError:
                    continue

        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = set(pool.map(commit, range(16)))
        tip = repo.get_ref("main")
        assert tip is not None
        chain = list(repo.ancestors(tip))
        assert {c.id for c in chain} == ids
        assert all(len(c.parents) <= 1 for c in chain)

    def test_prune_racing_writers_leaves_no_dangling_link(self, store: Store) -> None:
        """Writers committing while prune runs with expire=0 never leave a broken link."""
        repo = store.repo("r")
        repo.put(Blob(b"seed"))
        stop = threading.Event()

        def writer(i: int) -> None:
            for n in range(10):
                try:
                    repo.commit(f"w{i}", _tree(repo, f=f"{i}-{n}".encode()))
                except ObjectNotFoundError:
                    pass  # prune took an object this writer had not referenced yet

        def pruner() -> None:
            while not stop.is_set():
                repo.prune(expire=0)

        thread = threading.Thread(target=pruner)
        thread.start()
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(writer, range(4)))
        finally:
            stop.set()
            thread.join()
        assert dangling_links(store, "r") == []
        for tip in repo.refs().values():
            list(repo.ancestors(tip))

    # -- lifecycle --------------------------------------------------------------

    def test_repo_reused_after_delete_starts_fresh(self, store: Store) -> None:
        """A Repo handle kept across delete_repo writes a new history from a root commit."""
        repo = store.repo("r")
        old = repo.commit("main", _tree(repo, f=b"old"))
        store.delete_repo("r")
        new = repo.commit("main", _tree(repo, f=b"new"))
        assert old not in repo
        assert repo.get(new, Commit).parents == ()  # type: ignore[union-attr]

    def test_prune_after_a_ref_moved_back(self, store: Store, age: Age) -> None:
        """Commits left behind by moving a ref to an ancestor are collected; the rest reads."""
        repo = store.repo("r")
        base = repo.commit("main", _tree(repo, f=b"1"))
        ahead = repo.commit("main", _tree(repo, f=b"2"))
        assert repo.set_ref("main", base, ahead)
        for object_id in store.list_objects("r"):
            age("r", object_id, 7200)
        assert repo.prune(expire=3600) == 3  # the commit, its tree and its blob
        assert ahead not in repo
        assert [c.id for c in repo.ancestors(base)] == [base]
        assert repo.prune(expire=3600) == 0

    def test_ancestors_of_a_root_commit(self, store: Store) -> None:
        """A root commit's history is itself."""
        repo = store.repo("r")
        root = repo.commit("main", _tree(repo, f=b"x"))
        assert [c.id for c in repo.ancestors(root)] == [root]

    def test_first_parents_follows_the_first_parent_lazily(self, store: Store) -> None:
        """Merged-in side branches are skipped; only the steps taken are read."""
        repo = store.repo("r")
        tree_id = _tree(repo, f=b"x")
        root = repo.put(Commit(tree_id, (), b"root"))
        main = repo.put(Commit(tree_id, (root,), b"main"))
        side = repo.put(Commit(tree_id, (root,), b"side"))
        merge = repo.put(Commit(tree_id, (main, side), b"merge"))
        assert [c.id for c in repo.first_parents(merge)] == [merge, main, root]
        store.delete_objects("r", [root])
        walk = repo.first_parents(merge)
        assert [next(walk).id, next(walk).id] == [merge, main]
        with pytest.raises(ObjectNotFoundError):
            next(walk)

    # -- integrity --------------------------------------------------------------

    def test_get_rejects_content_that_does_not_match_its_id(self, store: Store) -> None:
        """Bytes damaged in storage raise instead of coming back as the object."""
        object_id = Blob(b"original").id
        store.write_object("r", object_id, "blob", b"damaged")
        with pytest.raises(CorruptObjectError):
            store.repo("r").get(object_id)

    # -- existence and names ----------------------------------------------------

    def test_reads_locks_and_failed_writes_create_no_repo(self, store: Store) -> None:
        """Only a stored object or ref makes a repository exist."""
        repo = store.repo("r")
        missing_commit = Commit(Tree().id).id
        assert not repo.delete_ref("main", missing_commit)
        with pytest.raises(ObjectNotFoundError):
            repo.set_ref("main", missing_commit, None)
        with pytest.raises(ObjectNotFoundError):
            repo.put(Tree((TreeEntry("f", "blob", Blob(b"x").id),)))
        with store.lock("r", exclusive=True):
            pass
        assert repo.prune(expire=0) == 0
        assert store.list_repos() == []

    def test_emptied_repo_is_not_listed(self, store: Store) -> None:
        """A repository whose refs are deleted and objects pruned no longer exists."""
        repo = store.repo("r")
        commit_id = repo.commit("main", _tree(repo, f=b"x"))
        assert repo.delete_ref("main", commit_id)
        assert repo.prune(expire=0) == 3
        assert store.list_repos() == []

    def test_name_length_and_encoding(self, store: Store) -> None:
        """Names over 255 UTF-8 bytes or not encodable as UTF-8 are refused."""
        repo = store.repo("r")
        for bad in ("a" * 256, "é" * 128, "\ud800"):
            with pytest.raises(InvalidNameError):
                store.repo(bad)
            with pytest.raises(InvalidNameError):
                repo.get_ref(bad)
        name = "a" * 100
        store.repo(name).commit(name, _tree(store.repo(name), f=b"x"))
        assert store.repo(name).get_ref(name) is not None
