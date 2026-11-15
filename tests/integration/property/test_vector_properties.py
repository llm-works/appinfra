# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Property-based tests for Vector: any edit sequence, any ids, the same canonical result."""

from __future__ import annotations

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from appinfra.cas import Blob, MemoryStore, Repo, Vector
from appinfra.log import Logger

LG = Logger("test-cas")

POOL_SIZE = 64
"""Distinct elements: few enough that runs and repeats are common."""

edit = st.tuples(
    st.floats(min_value=0, max_value=1),  # where the edit starts, as a fraction
    st.sampled_from([0, 1, 2, 17, 300, 5000]),  # how many elements it removes, at most
    st.lists(st.integers(0, POOL_SIZE - 1), max_size=40),  # what it inserts
    st.integers(0, 600),  # a run of one element appended to the insert
)


def _setup(seed: int, size: int) -> tuple[Repo, list[str], list[str]]:
    """A repository with a pool of stored blobs, and a list of ``size`` of them."""
    repo = MemoryStore(LG).repo("r")
    pool = [repo.put(Blob(f"p{i}".encode())) for i in range(POOL_SIZE)]
    rng = random.Random(seed)
    return repo, pool, [rng.choice(pool) for _ in range(size)]


def _apply(
    model: list[str], pool: list[str], e: tuple[float, int, list[int], int]
) -> tuple[int, int, list[str]]:
    """Turn a drawn edit into (start, stop, ids) on ``model``."""
    where, remove, insert, run = e
    start = int(where * len(model))
    stop = min(len(model), start + remove)
    return (
        start,
        stop,
        [pool[i] for i in insert] + [pool[run % POOL_SIZE]] * (run // 10),
    )


@settings(max_examples=60, deadline=None)
@given(
    seed=st.integers(0, 2**16),
    size=st.sampled_from([0, 5, 300, 6000]),
    edits=st.lists(edit, min_size=1, max_size=8),
)
def test_edits_match_a_fresh_build(seed: int, size: int, edits: list) -> None:  # type: ignore[type-arg]
    """After any edits, the vector reads as the edited list and has its fresh-build root."""
    repo, pool, model = _setup(seed, size)
    vector = Vector.build(repo, model)
    for e in edits:
        start, stop, ids = _apply(model, pool, e)
        vector = vector.splice(start, stop, ids)
        model[start:stop] = ids
    assert vector == Vector.build(repo, model)
    assert list(vector) == model
    assert vector.assign(model) is vector


@settings(max_examples=60, deadline=None)
@given(
    seed=st.integers(0, 2**16),
    size=st.sampled_from([0, 5, 300, 6000]),
    edits=st.lists(edit, max_size=6),
    window=st.tuples(st.floats(0, 1), st.floats(0, 1)),
)
def test_diff_turns_one_version_into_the_other(
    seed: int,
    size: int,
    edits: list,
    window: tuple[float, float],  # type: ignore[type-arg]
) -> None:
    """Applying diff(a, b) to a gives b; slices read the same as the list."""
    repo, pool, model = _setup(seed, size)
    before = Vector.build(repo, model)
    after, edited = before, list(model)
    for e in edits:
        start, stop, ids = _apply(edited, pool, e)
        after = after.splice(start, stop, ids)
        edited[start:stop] = ids
    result = list(model)
    for splice in reversed(before.diff(after)):
        result[splice.start : splice.stop] = splice.ids
    assert result == edited
    lo, hi = sorted(int(f * len(edited)) for f in window)
    assert list(after.ids(lo, hi)) == edited[lo:hi]
