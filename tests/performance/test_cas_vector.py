# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Vector benchmark: a commit at every step, on the file store (fsync on) and in memory.

Two parts. Each edit shape on its own (append, prefix drop, prefix replace, scattered
point edits) against a long vector, one commit per edit. Then the conversation profile:
an agent loop committed at every step, with tool-result trimming, summaries and window
drops along the way, against the bytes one blob per step would store. Each part prints
its numbers; run with ``make test.perf.v`` to see them.

By default the benchmark runs small, as a regression check that fits ``make check``.
``APPINFRA_CAS_BENCH=full`` runs it at full size: a 20,000-element vector, 100 commits
per edit shape, and 1,000 conversation steps that put about a million tokens (4 MB of
messages) through the loop.
"""

from __future__ import annotations

import os
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


@dataclass(frozen=True)
class Scale:
    """How big a benchmark run is, and what it must show at that size."""

    base: int  # elements of the vector the edit shapes run against
    repeats: int  # commits per edit shape
    steps: int  # steps of the conversation profile
    min_seen: int  # message bytes the profile must put through the loop
    min_saving: int  # how many times less than one blob per step it must store


SMALL = Scale(base=5_000, repeats=20, steps=200, min_seen=600_000, min_saving=10)
FULL = Scale(base=20_000, repeats=100, steps=1000, min_seen=3_500_000, min_saving=50)
SCALE = FULL if os.environ.get("APPINFRA_CAS_BENCH") == "full" else SMALL


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
            for i in range(SCALE.base)
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


def _prepared(tmp_path: Path, backend: str) -> tuple[_Counting, Vector]:
    """A store holding the base vector, built without fsync; the store measured, with it."""
    builder = _store(tmp_path, backend, fsync=False)
    vector = _base(builder.repo("bench"))  # type: ignore[attr-defined]
    store = builder if backend == "memory" else _store(tmp_path, backend)
    store.known = set(builder.known)
    return store, vector.on(store.repo("bench"))  # type: ignore[attr-defined]


@pytest.mark.parametrize("backend", ["file", "memory"])
def test_edit_shapes(tmp_path: Path, backend: str) -> None:
    """Each edit shape committed on its own ref: time, bytes and objects per commit."""
    rng = random.Random(1)
    store, base = _prepared(tmp_path, backend)
    print(f"\n-- edit shapes on {SCALE.base} elements, {backend} store --")
    for name, shape in _shapes(rng).items():
        repo, vector, stats, fresh = base._source, base, Stats(name), []
        for i in range(SCALE.repeats):
            blobs = [
                Blob(f"{name} {i} {k}".encode() * 50) for k in range(shape.fresh())
            ]
            new = [b.id for b in blobs]
            fresh.append(len(blobs))
            with _measured(stats, store):
                vector = _commit(
                    repo, name, lambda v: shape.edit(v, new), vector, blobs
                )  # type: ignore[arg-type]
        print(stats.line())
        root = repo.get(vector.id, VectorNode)
        assert root is not None
        nodes = [
            n - f - 2 for n, f in zip(stats.objects, fresh)
        ]  # minus blobs, tree, commit
        assert statistics.mean(nodes) <= shape.splices * (root.level + 1) * 1.5


class _ListBytes:
    """Size of ``canonical_json(messages)``, from each message's size computed once."""

    def __init__(self) -> None:
        self._sizes: dict[int, tuple[Message, int]] = {}

    def __call__(self, messages: list[Message]) -> int:
        sizes = {}
        for m in messages:
            known = self._sizes.get(id(m))
            sizes[id(m)] = (
                known if known and known[0] is m else (m, len(canonical_json(m)))
            )
        self._sizes = sizes
        return 2 + sum(sizes[id(m)][1] for m in messages) + max(0, len(messages) - 1)


def _conversation(
    recorder: Recorder, stats: Stats, store: _Counting
) -> tuple[list[Message], int, int]:
    """Run the agent loop, compacting along the way; commit at every step."""
    loop = AgentLoop(seed=7, tool_bytes=4500, text_bytes=1200)
    messages, seen, rewritten, list_bytes = [SYSTEM], 0, 0, _ListBytes()
    trim, summary, drop = SCALE.steps // 20, SCALE.steps * 3 // 20, SCALE.steps * 2 // 5
    for step in range(1, SCALE.steps + 1):
        new = loop.step()
        seen += sum(len(message_blob(m).data) for m in new)
        messages = messages + new
        if step % trim == 0:
            messages = trim_tool_results(messages, limit=4000, every=7)
        if step % summary == 0:
            messages = summarize(messages, keep=len(messages) * 3 // 4, step=step)
        if step % drop == 0:
            messages = window(messages, keep=len(messages) * 9 // 10)
        with _measured(stats, store):
            recorder.commit(messages)
        rewritten += list_bytes(messages)  # what one blob per step would store
    return messages, seen, rewritten


@pytest.mark.parametrize("backend", ["file", "memory"])
def test_conversation_profile(tmp_path: Path, backend: str) -> None:
    """One commit per step, compaction mixed in; ~1M tokens through the loop at full size."""
    store = _store(tmp_path, backend)
    recorder = Recorder(store.repo("agent"), "session")  # type: ignore[attr-defined]
    stats = Stats(f"conversation ({backend})")
    messages, seen, rewritten = _conversation(recorder, stats, store)
    stored = store.new_bytes
    print(f"\n-- conversation profile, {SCALE.steps} steps, {backend} store --")
    print(stats.line())
    print(
        f"message bytes through the loop {seen:,}  live at the end {len(messages)} messages\n"
        f"stored {stored:,} ({stored / seen:.2f}x the messages)  "
        f"one blob per step would store {rewritten:,} ({rewritten / stored:.0f}x more)"
    )
    assert seen > SCALE.min_seen
    assert stored <= 3 * seen
    assert rewritten > SCALE.min_saving * stored
