# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Vector benchmark: a commit at every step, on the file store (fsync on) and in memory.

Two parts. Each edit shape on its own (append, prefix drop, prefix replace, scattered
point edits) against a long vector, one commit per edit. Then the conversation profile:
an agent loop committed at all 1,000 steps until about a million tokens (4 MB of
messages) passed through it, with tool-result trimming, summaries and window drops along
the way, against the bytes one blob per step would store. Each part prints its numbers;
run with ``make test.perf.v`` to see them.
"""

from __future__ import annotations

import random
import statistics
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from appinfra.cas import (
    Blob,
    FileStore,
    MemoryStore,
    Repo,
    Tree,
    TreeEntry,
    Vector,
    VectorNode,
    canonical_json,
)
from appinfra.log import Logger
from tests.helpers.cas_conversation import (
    SYSTEM,
    AgentLoop,
    Message,
    Recorder,
    message_blob,
    summarize,
    trim_tool_results,
    window,
)

LG = Logger("perf-cas")

BASE_SIZE = 20_000
"""Elements of the vector the edit shapes run against (three levels deep)."""

REPEATS = 100
"""Commits per edit shape."""

STEPS = 1000
"""Steps of the conversation profile."""


@dataclass
class Stats:
    """Times, bytes and objects of a series of commits."""

    name: str
    times: list[float] = field(default_factory=list)
    bytes: list[int] = field(default_factory=list)
    objects: list[int] = field(default_factory=list)

    def pct(self, q: float) -> float:
        ordered = sorted(self.times)
        return ordered[min(len(ordered) - 1, int(q * len(ordered)))]

    def line(self) -> str:
        return (
            f"{self.name:<28} p50 {self.pct(0.5) * 1e3:6.2f} ms  p99 {self.pct(0.99) * 1e3:6.2f} ms"
            f"  bytes/commit {statistics.mean(self.bytes):8.0f}"
            f"  objects/commit {statistics.mean(self.objects):5.1f}"
        )


class _Counting:
    """Counts the objects a store writes for the first time, and their bytes."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[call-arg]
        self.known: set[str] = set()
        self.new_bytes = 0
        self.new_objects = 0

    def write_object(
        self, repo: str, object_id: str, object_type: str, data: bytes
    ) -> None:
        super().write_object(repo, object_id, object_type, data)  # type: ignore[misc]
        if object_id not in self.known:
            self.known.add(object_id)
            self.new_bytes += len(data)
            self.new_objects += 1


class _CountingFile(_Counting, FileStore):
    pass


class _CountingMemory(_Counting, MemoryStore):
    pass


@contextmanager
def _measured(stats: Stats, store: _Counting) -> Iterator[None]:
    size, count = store.new_bytes, store.new_objects
    start = time.perf_counter()
    yield
    stats.times.append(time.perf_counter() - start)
    stats.bytes.append(store.new_bytes - size)
    stats.objects.append(store.new_objects - count)


def _store(tmp_path: Path, backend: str, fsync: bool = True) -> _Counting:
    if backend == "file":
        return _CountingFile(LG, tmp_path / "file", fsync=fsync)
    return _CountingMemory(LG)


def _commit(
    repo: Repo,
    ref: str,
    edit: Callable[[Vector], Vector],
    vector: Vector,
    blobs: list[Blob],
) -> Vector:
    """Store new blobs, apply the edit and commit, in one batch plus the commit."""
    with repo.batch() as batch:
        for blob in blobs:
            batch.put(blob)
        edited = edit(vector.on(batch))
        tree = batch.put(Tree((TreeEntry("items", "vector", edited.id),)))
    repo.commit(ref, tree)
    return edited.on(repo)


def _base(repo: Repo) -> Vector:
    with repo.batch() as batch:
        ids = [
            batch.put(Blob(canonical_json({"i": i, "pad": "x" * 200})))
            for i in range(BASE_SIZE)
        ]
        return Vector.build(batch, ids).on(repo)


@dataclass
class Shape:
    """An edit shape: how many new elements a commit stores, how many splices it makes."""

    edit: Callable[[Vector, list[str]], Vector]
    fresh: Callable[[], int]
    splices: int = 1


def _shapes(rng: random.Random) -> dict[str, Shape]:
    """Each edit shape, applied as (vector, new element ids) -> edited vector."""

    def scattered(v: Vector, new: list[str]) -> Vector:
        for element in new:
            at = rng.randrange(len(v))
            v = v.splice(at, at + 1, [element])
        return v

    return {
        "append": Shape(lambda v, new: v.append(new), lambda: rng.randint(1, 3)),
        "prefix drop": Shape(
            lambda v, new: v.splice(1, rng.randint(2, 200)), lambda: 0
        ),
        "prefix replace (summary)": Shape(
            lambda v, new: v.splice(1, rng.randint(2, 200), new), lambda: 1
        ),
        "scattered point edits (5)": Shape(scattered, lambda: 5, splices=5),
    }


def _prepared(
    tmp_path: Path, backend: str, count: int
) -> tuple[_Counting, list[Vector]]:
    """``count`` repositories holding a committed base vector; built without fsync."""
    builder = _store(tmp_path, backend, fsync=False)
    roots = []
    for i in range(count):
        repo = builder.repo(f"shape{i}")  # type: ignore[attr-defined]
        vector = _base(repo)
        repo.commit("main", repo.put(Tree((TreeEntry("items", "vector", vector.id),))))
        roots.append(vector.id)
    store = builder if backend == "memory" else _store(tmp_path, backend)
    store.known = set(builder.known)
    return store, [
        Vector(store.repo(f"shape{i}"), root) for i, root in enumerate(roots)
    ]  # type: ignore[attr-defined]


@pytest.mark.parametrize("backend", ["file", "memory"])
def test_edit_shapes(tmp_path: Path, backend: str) -> None:
    """Each edit shape committed REPEATS times: time, bytes and objects per commit."""
    rng = random.Random(1)
    shapes = _shapes(rng)
    store, bases = _prepared(tmp_path, backend, len(shapes))
    print(f"\n-- edit shapes on {BASE_SIZE} elements, {backend} store --")
    for (name, shape), vector in zip(shapes.items(), bases):
        repo, stats, fresh = vector._source, Stats(name), []
        for i in range(REPEATS):
            blobs = [
                Blob(f"{name} {i} {k}".encode() * 50) for k in range(shape.fresh())
            ]
            new = [b.id for b in blobs]
            fresh.append(len(blobs))
            with _measured(stats, store):
                vector = _commit(
                    repo, "main", lambda v: shape.edit(v, new), vector, blobs
                )  # type: ignore[arg-type]
        print(stats.line())
        root = repo.get(vector.id, VectorNode)
        assert root is not None
        nodes = [
            n - f - 2 for n, f in zip(stats.objects, fresh)
        ]  # minus blobs, tree, commit
        assert statistics.mean(nodes) <= shape.splices * (root.level + 1) * 1.5


def _conversation(
    recorder: Recorder, stats: Stats, store: _Counting
) -> tuple[list[Message], int, int]:
    """Run the agent loop STEPS steps, compacting along the way; commit at every step."""
    loop = AgentLoop(seed=7, tool_bytes=4500, text_bytes=1200)
    messages, seen, rewritten = [SYSTEM], 0, 0
    for step in range(1, STEPS + 1):
        new = loop.step()
        seen += sum(len(message_blob(m).data) for m in new)
        messages = messages + new
        if step % 50 == 0:
            messages = trim_tool_results(messages, limit=4000, every=7)
        if step % 150 == 0:
            messages = summarize(messages, keep=len(messages) * 3 // 4, step=step)
        if step % 400 == 0:
            messages = window(messages, keep=len(messages) * 9 // 10)
        with _measured(stats, store):
            recorder.commit(messages)
        rewritten += len(canonical_json(messages))
    return messages, seen, rewritten


@pytest.mark.parametrize("backend", ["file", "memory"])
def test_conversation_profile(tmp_path: Path, backend: str) -> None:
    """1,000 steps, ~1M tokens through the loop, one commit per step, compaction mixed in."""
    store = _store(tmp_path, backend)
    recorder = Recorder(store.repo("agent"), "session")  # type: ignore[attr-defined]
    stats = Stats(f"conversation ({backend})")
    messages, seen, rewritten = _conversation(recorder, stats, store)
    stored = store.new_bytes
    print(f"\n-- conversation profile, {STEPS} steps, {backend} store --")
    print(stats.line())
    print(
        f"message bytes through the loop {seen:,}  live at the end {len(messages)} messages\n"
        f"stored {stored:,} ({stored / seen:.2f}x the messages)  "
        f"one blob per step would store {rewritten:,} ({rewritten / stored:.0f}x more)"
    )
    assert seen > 3_500_000  # about a million tokens
    assert stored <= 3 * seen
    assert rewritten > 50 * stored
