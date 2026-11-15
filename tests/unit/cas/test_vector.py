# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Vector reads, edits, chunk bounds, locality and diff on an in-memory store."""

from __future__ import annotations

import itertools
import random
from collections.abc import Callable

import pytest

from appinfra.cas import (
    Blob,
    Commit,
    CorruptObjectError,
    MemoryStore,
    ObjectNotFoundError,
    Repo,
    Splice,
    Tree,
    TreeEntry,
    Vector,
    VectorNode,
)
from appinfra.cas.objects import VECTOR_NODE_MAX
from appinfra.cas.vector import BOUNDARY_MODULUS, CHUNK_MIN
from appinfra.log import Logger

LG = Logger("test-cas")


@pytest.fixture
def store() -> MemoryStore:
    """A fresh, empty store."""
    return MemoryStore(LG)


@pytest.fixture
def repo(store: MemoryStore) -> Repo:
    """A repository of the store."""
    return store.repo("r")


def _blobs(repo: Repo, n: int, tag: str = "e") -> list[str]:
    """Store ``n`` distinct blobs; return their ids."""
    return [repo.put(Blob(f"{tag}{i}".encode())) for i in range(n)]


def _is_boundary(object_id: str) -> bool:
    return int(object_id[:8], 16) % BOUNDARY_MODULUS == 0


def _blob_where(repo: Repo, boundary: bool, skip: int = 0) -> str:
    """Store the ``skip``-th blob whose id ends a chunk (or does not); return its id."""
    found = (
        Blob(f"x{i}".encode())
        for i in itertools.count()
        if _is_boundary(Blob(f"x{i}".encode()).id) == boundary
    )
    return repo.put(next(itertools.islice(found, skip, None)))


def _leaf_sizes(repo: Repo, vector: Vector) -> list[int]:
    """Return the number of elements in each leaf, in order."""
    sizes: list[int] = []
    stack = [repo.get(vector.id, VectorNode)]
    while stack:
        node = stack.pop()
        assert node is not None
        if node.level == 0:
            sizes.append(len(node.children))
        else:
            stack.extend(repo.get(c, VectorNode) for c in reversed(node.children))
    return sizes


def _growth(store: MemoryStore, edit: Callable[[], Vector]) -> tuple[set[str], Vector]:
    """Run ``edit``; return the ids of the objects it added and its result."""
    before = set(store.list_objects("r"))
    vector = edit()
    return set(store.list_objects("r")) - before, vector


def _depth(repo: Repo, vector: Vector) -> int:
    root = repo.get(vector.id, VectorNode)
    assert root is not None
    return root.level + 1


class TestReading:
    """Length, indexing and iteration."""

    @pytest.mark.parametrize("n", [0, 1, CHUNK_MIN, 1000, 5000])
    def test_build_reads_back(self, repo: Repo, n: int) -> None:
        """A built vector holds its ids in order, at every size."""
        ids = _blobs(repo, n)
        vector = Vector.build(repo, ids)
        assert len(vector) == n
        assert list(vector) == ids
        if n:
            assert (vector[0], vector[n // 2], vector[-1]) == (
                ids[0],
                ids[n // 2],
                ids[-1],
            )

    def test_index_out_of_range(self, repo: Repo) -> None:
        """Indexes past either end raise IndexError."""
        vector = Vector.build(repo, _blobs(repo, 3))
        for index in (3, -4):
            with pytest.raises(IndexError):
                vector[index]

    def test_ids_of_a_range(self, repo: Repo) -> None:
        """ids(start, stop) yields that slice, across leaves."""
        ids = _blobs(repo, 2000)
        vector = Vector.build(repo, ids)
        for start, stop in [(0, 0), (0, 2000), (5, 6), (100, 1900), (1999, 2000)]:
            assert list(vector.ids(start, stop)) == ids[start:stop]
        assert list(vector.ids(1990)) == ids[1990:]

    @pytest.mark.parametrize(("start", "stop"), [(-1, 2), (2, 1), (0, 4)])
    def test_ids_out_of_bounds_raise_at_the_call(
        self, repo: Repo, start: int, stop: int
    ) -> None:
        """A bad range raises when ids() is called, not when it is iterated."""
        vector = Vector.build(repo, _blobs(repo, 3))
        with pytest.raises(IndexError):
            vector.ids(start, stop)

    def test_reopened_by_id(self, repo: Repo) -> None:
        """A vector is its root id: reopening it reads the same list."""
        ids = _blobs(repo, 500)
        vector = Vector(repo, Vector.build(repo, ids).id)
        assert list(vector) == ids
        assert repr(vector) == f"Vector({vector.id!r})"

    def test_missing_root(self, repo: Repo) -> None:
        """A root that is not stored raises on first use."""
        vector = Vector(repo, "a" * 64)
        with pytest.raises(ObjectNotFoundError):
            len(vector)


class TestCanonical:
    """The same list gives the same root, whatever the edits."""

    @pytest.mark.parametrize(("seed", "size"), [(0, 0), (1, 300), (2, 5000)])
    def test_edits_give_the_root_of_a_fresh_build(
        self, repo: Repo, seed: int, size: int
    ) -> None:
        """Appends, inserts, deletes and replaces of any size keep the root canonical."""
        rng = random.Random(seed)
        pool = _blobs(repo, 400)
        model = [rng.choice(pool) for _ in range(size)]
        vector = Vector.build(repo, model)
        for _ in range(60):
            start = rng.randint(0, len(model))
            stop = rng.randint(
                start, min(len(model), start + rng.choice([0, 1, 40, 900]))
            )
            new = [rng.choice(pool) for _ in range(rng.choice([0, 1, 3, 300]))]
            vector = vector.splice(start, stop, new)
            model[start:stop] = new
            assert vector == Vector.build(repo, model)
        assert list(vector) == model

    def test_edits_cut_exactly_at_chunk_boundaries(self, repo: Repo) -> None:
        """Deleting whole leaves or whole subtrees, edges on chunk ends, stays canonical."""
        model = _blobs(repo, 20000)
        vector = Vector.build(repo, model)
        ends = list(itertools.accumulate(_leaf_sizes(repo, vector)))
        root = repo.get(vector.id, VectorNode)
        assert root is not None and root.level == 2
        subtree = root.counts[0]  # elements under the first level-1 node
        cuts = [(ends[3], ends[4]), (ends[3], ends[9]), (0, ends[0]), (0, subtree)]
        cuts += [(subtree, subtree + root.counts[1]), (ends[-2], ends[-1])]
        for start, stop in cuts:
            edited = vector.splice(start, stop)
            assert edited == Vector.build(repo, model[:start] + model[stop:])
        for at in (ends[5], subtree):
            inserted = vector.splice(at, at, model[:CHUNK_MIN])
            assert inserted == Vector.build(
                repo, model[:at] + model[:CHUNK_MIN] + model[at:]
            )

    def test_equal_lists_are_equal_vectors(self, repo: Repo) -> None:
        """Built at once or appended piece by piece: one root, equal and same hash."""
        ids = _blobs(repo, 3000)
        whole = Vector.build(repo, ids)
        pieces = Vector.empty(repo)
        for i in range(0, 3000, 7):
            pieces = pieces.append(ids[i : i + 7])
        assert pieces == whole and hash(pieces) == hash(whole)

    def test_noop_splice_returns_self(self, repo: Repo) -> None:
        """An empty edit stores nothing and returns the same vector."""
        vector = Vector.build(repo, _blobs(repo, 10))
        assert vector.splice(4, 4) is vector
        assert vector.assign(list(vector)) is vector

    def test_emptied_vector_is_the_empty_vector(self, repo: Repo) -> None:
        """Deleting everything gives the one empty vector."""
        vector = Vector.build(repo, _blobs(repo, 2000))
        assert vector.splice(0, 2000) == Vector.empty(repo)
        assert len(Vector.empty(repo)) == 0


class TestChunkBounds:
    """Every chunk but the last holds CHUNK_MIN to VECTOR_NODE_MAX entries, for any ids."""

    def _assert_bounded(self, repo: Repo, vector: Vector) -> None:
        sizes = _leaf_sizes(repo, vector)
        assert all(CHUNK_MIN <= size <= VECTOR_NODE_MAX for size in sizes[:-1])
        assert len(sizes) <= len(vector) // CHUNK_MIN + 1

    def test_run_of_a_boundary_id(self, repo: Repo) -> None:
        """A run of an id that ends chunks still makes chunks of CHUNK_MIN, not of one."""
        boundary = _blob_where(repo, boundary=True)
        vector = Vector.build(repo, [boundary] * 2000)
        self._assert_bounded(repo, vector)
        assert _leaf_sizes(repo, vector) == [CHUNK_MIN] * (2000 // CHUNK_MIN)

    def test_run_of_a_plain_id(self, repo: Repo) -> None:
        """A run of an id that never ends a chunk is cut at VECTOR_NODE_MAX."""
        plain = _blob_where(repo, boundary=False)
        vector = Vector.build(repo, [plain] * 2000)
        assert _leaf_sizes(repo, vector)[:-1] == [VECTOR_NODE_MAX] * (
            2000 // VECTOR_NODE_MAX
        )

    def test_repeating_pattern_of_boundary_ids(self, repo: Repo) -> None:
        """A repeating pattern of boundary ids is bounded the same way."""
        a = _blob_where(repo, boundary=True)
        b = _blob_where(repo, boundary=True, skip=1)
        self._assert_bounded(repo, Vector.build(repo, [a, b] * 1000))

    def test_runs_inserted_by_edits(self, repo: Repo) -> None:
        """Runs spliced into a list keep the bounds and the canonical root."""
        rng = random.Random(7)
        boundary, plain = _blob_where(repo, True), _blob_where(repo, False)
        model = _blobs(repo, 1500)
        vector = Vector.build(repo, model)
        for _ in range(20):
            at = rng.randint(0, len(model))
            run = [rng.choice([boundary, plain])] * rng.randint(1, 600)
            vector, model[at:at] = vector.splice(at, at, run), run
        assert vector == Vector.build(repo, model)
        self._assert_bounded(repo, vector)


class TestLocality:
    """An edit stores about one path of new nodes, not a share of the vector."""

    @pytest.fixture
    def big(self, repo: Repo) -> tuple[Vector, list[str]]:
        """A vector three levels deep and spare ids to edit with."""
        ids = _blobs(repo, 20000)
        return Vector.build(repo, ids), _blobs(repo, 50, tag="new")

    def test_append_stores_one_path(
        self, store: MemoryStore, repo: Repo, big: tuple[Vector, list[str]]
    ) -> None:
        """Appending one element stores one node per level."""
        vector, spare = big
        added, _ = _growth(store, lambda: vector.append(spare[:1]))
        assert len(added) == _depth(repo, vector) == 3

    @pytest.mark.parametrize("cut", [2, 777, 5000, 13333, 19998])
    def test_prefix_drop_and_replace_store_about_one_path(
        self,
        store: MemoryStore,
        repo: Repo,
        big: tuple[Vector, list[str]],
        cut: int,
    ) -> None:
        """Dropping or summarizing a prefix rewrites the cut, not what follows it."""
        vector, spare = big
        bound = 2 * _depth(repo, vector)
        dropped, _ = _growth(store, lambda: vector.splice(1, cut))
        replaced, _ = _growth(store, lambda: vector.splice(1, cut, spare[:1]))
        assert len(dropped) <= bound
        assert len(replaced) <= bound

    def test_point_edit_stores_about_one_path(
        self, store: MemoryStore, repo: Repo, big: tuple[Vector, list[str]]
    ) -> None:
        """Replacing one element in the middle stores about one path."""
        vector, spare = big
        added, _ = _growth(store, lambda: vector.splice(9000, 9001, spare[:1]))
        assert len(added) <= 2 * _depth(repo, vector)

    def test_assign_stores_what_splice_stores(self) -> None:
        """Handing over the whole new list stores the same nodes as the edit itself."""

        def run(edit: Callable[[Vector, list[str]], Vector]) -> set[str]:
            store = MemoryStore(LG)
            repo = store.repo("r")
            ids = _blobs(repo, 5000)
            vector = Vector.build(repo, ids)
            added, _ = _growth(store, lambda: edit(vector, ids))
            return added

        by_splice = run(lambda v, ids: v.splice(1, 2500))
        by_assign = run(lambda v, ids: v.assign(ids[:1] + ids[2500:]))
        assert by_splice == by_assign and by_splice


class TestDiff:
    """Splices between two versions."""

    def test_identical_vectors(self, repo: Repo) -> None:
        """The same list has no differences."""
        vector = Vector.build(repo, _blobs(repo, 100))
        assert vector.diff(Vector(repo, vector.id)) == []

    @pytest.mark.parametrize(
        ("start", "stop", "fresh"),
        [(1, 3000, 1), (4000, 4000, 5), (100, 101, 1), (0, 6000, 0)],
    )
    def test_single_edit_comes_back_exactly(
        self, repo: Repo, start: int, stop: int, fresh: int
    ) -> None:
        """One contiguous edit is reported as exactly that edit."""
        vector = Vector.build(repo, _blobs(repo, 6000))
        new = tuple(_blobs(repo, fresh, tag="fresh"))
        edited = vector.splice(start, stop, new)
        assert vector.diff(edited) == [Splice(start, stop, new)]

    def test_applying_the_diff_gives_the_other(self, repo: Repo) -> None:
        """Applied last to first, the splices turn one list into the other."""
        rng = random.Random(3)
        pool = _blobs(repo, 300)
        model = [rng.choice(pool) for _ in range(8000)]
        vector = Vector.build(repo, model)
        other = vector
        for _ in range(12):
            start = rng.randint(0, len(other))
            stop = min(len(other), start + rng.randint(0, 50))
            other = other.splice(start, stop, rng.sample(pool, rng.randint(0, 4)))
        result = list(model)
        for splice in reversed(vector.diff(other)):
            result[splice.start : splice.stop] = splice.ids
        assert result == list(other)

    def test_reads_only_the_leaves_that_differ(self) -> None:
        """Shared chunks are compared by id, never read."""
        reads: list[str] = []

        class Counting(MemoryStore):
            def read_object(self, repo: str, object_id: str):  # type: ignore[no-untyped-def]
                reads.append(object_id)
                return super().read_object(repo, object_id)

        repo = Counting(LG).repo("r")
        ids = _blobs(repo, 20000)
        old_id = Vector.build(repo, ids).id
        new_id = Vector(repo, old_id).splice(10000, 10001, _blobs(repo, 1, "x")).id
        interior = _interior_count(repo, old_id) + _interior_count(repo, new_id)
        reads.clear()
        Vector(repo, old_id).diff(Vector(repo, new_id))
        assert len(reads) <= interior + 4  # the changed leaf, and a neighbour, per side
        assert len(_leaf_sizes(repo, Vector(repo, old_id))) > 100


def _interior_count(repo: Repo, root_id: str) -> int:
    """Number of interior nodes of the vector at ``root_id``."""
    count, stack = 0, [repo.get(root_id, VectorNode)]
    while stack:
        node = stack.pop()
        assert node is not None
        if node.level:
            count += 1
            if node.level > 1:
                stack.extend(repo.get(c, VectorNode) for c in node.children)
    return count


class TestElementsAndStorage:
    """What elements may be, batches, pruning and corruption."""

    def test_elements_may_be_any_object(self, repo: Repo) -> None:
        """Blobs, trees, commits and other vectors can all be elements."""
        blob = repo.put(Blob(b"b"))
        tree = repo.put(Tree((TreeEntry("b", "blob", blob),)))
        commit = repo.put(Commit(tree))
        inner = Vector.build(repo, [blob]).id
        assert list(Vector.build(repo, [blob, tree, commit, inner])) == [
            blob,
            tree,
            commit,
            inner,
        ]

    def test_unstored_element_raises_and_stores_nothing(
        self, store: MemoryStore, repo: Repo
    ) -> None:
        """A node is stored only when every element it lists is."""
        known = _blobs(repo, 1)
        before = set(store.list_objects("r"))
        with pytest.raises(ObjectNotFoundError):
            Vector.build(repo, [known[0], Blob(b"never stored").id])
        assert set(store.list_objects("r")) == before

    def test_batch_stores_at_block_end(self, store: MemoryStore, repo: Repo) -> None:
        """Edits in a batch read their own nodes back and are stored when it ends."""
        with repo.batch() as batch:
            ids = [batch.put(Blob(f"m{i}".encode())) for i in range(500)]
            vector = Vector.build(batch, ids[:300]).append(ids[300:])
            assert store.list_objects("r") == {}
        assert list(Vector(repo, vector.id)) == ids

    def test_closed_batch_reads_but_does_not_write(self, repo: Repo) -> None:
        """After its block, a batch-bound vector reads through to the repository."""
        with repo.batch() as batch:
            vector = Vector.build(batch, [batch.put(Blob(b"x"))])
        assert len(vector) == 1
        with pytest.raises(RuntimeError):
            vector.append([vector[0]])
        assert len(vector.on(repo).append([vector[0]])) == 2

    def test_prune_keeps_a_committed_vector_and_drops_it_with_its_ref(
        self, store: MemoryStore, repo: Repo
    ) -> None:
        """Through a tree entry, refs reach every node and element of a vector."""
        vector = Vector.build(repo, _blobs(repo, 3000))
        tree = repo.put(Tree((TreeEntry("items", "vector", vector.id),)))
        commit = repo.commit("main", tree)
        assert repo.prune(expire=0) == 0
        assert list(Vector(repo, vector.id)) == list(vector)
        repo.delete_ref("main", commit)
        repo.prune(expire=0)
        assert store.list_objects("r") == {}

    def test_child_with_a_wrong_count_is_corruption(self, repo: Repo) -> None:
        """A child that does not hold the elements its parent counts is refused."""
        leaf = repo.put(VectorNode(0, tuple(_blobs(repo, 3))))
        root = repo.put(VectorNode(1, (leaf, leaf), (3, 4)))
        with pytest.raises(CorruptObjectError):
            list(Vector(repo, root))

    def test_child_at_a_wrong_level_is_corruption(self, repo: Repo) -> None:
        """A child that is not one level down is refused."""
        leaf = repo.put(VectorNode(0, tuple(_blobs(repo, 3))))
        middle = repo.put(VectorNode(1, (leaf,), (3,)))
        root = repo.put(VectorNode(1, (middle, leaf), (3, 3)))
        with pytest.raises(CorruptObjectError):
            Vector(repo, root)[0]
