# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
A conversation committed at every LLM step, with compaction: the vector's main workload.

Each step stores only its new messages and the chunks around them; compaction (dropping,
summarizing or trimming old messages) stores about one path; what a compaction replaced
is the diff against the parent commit, and stays stored exactly as long as that history
does.
"""

from __future__ import annotations

import pytest

from appinfra.cas import (
    Blob,
    Commit,
    MemoryStore,
    Repo,
    Splice,
    Tree,
    TreeEntry,
    Vector,
    VectorNode,
    canonical_json,
)
from appinfra.cas.vector import CHUNK_MIN
from appinfra.log import Logger
from tests.helpers.cas_conversation import (
    SYSTEM,
    AgentLoop,
    Message,
    Recorder,
    conversation_at,
    message_blob,
    read_messages,
    stored_bytes,
    summarize,
    trim_tool_results,
    window,
)

LG = Logger("test-cas")


@pytest.fixture
def store() -> MemoryStore:
    """A fresh, empty store."""
    return MemoryStore(LG)


@pytest.fixture
def repo(store: MemoryStore) -> Repo:
    """The repository conversations are committed to."""
    return store.repo("agent")


def _run(
    recorder: Recorder, loop: AgentLoop, messages: list[Message], steps: int
) -> list[Message]:
    """Run ``steps`` LLM steps, committing after each; return the messages."""
    for _ in range(steps):
        messages = messages + loop.step()
        recorder.commit(messages)
    return messages


def _long(recorder: Recorder, loop: AgentLoop, steps: int) -> list[Message]:
    """Commit a conversation of ``steps`` steps at once: setup for the compaction tests."""
    messages = [SYSTEM]
    for _ in range(steps):
        messages += loop.step()
    recorder.commit(messages)
    return messages


def _new_objects(store: MemoryStore, repo: Repo, action) -> set[str]:  # type: ignore[no-untyped-def]
    before = set(store.list_objects(repo.name))
    action()
    return set(store.list_objects(repo.name)) - before


def _depth(repo: Repo, vector: Vector) -> int:
    root = repo.get(vector.id, VectorNode)
    assert root is not None
    return root.level + 1


def test_every_step_is_a_commit_that_reads_back(repo: Repo) -> None:
    """Each commit on the ref holds the conversation exactly as it was at that step."""
    recorder, loop = Recorder(repo, "session"), AgentLoop(seed=1)
    messages, snapshots = [SYSTEM], []
    for step in range(1, 121):
        messages = messages + loop.step()
        if step % 40 == 0:
            messages = summarize(messages, keep=30, step=step)
        snapshots.append(list(messages))
        recorder.commit(messages)
    tip = repo.get_ref("session")
    assert tip is not None
    history = [
        read_messages(repo, conversation_at(repo, c.id))
        for c in repo.first_parents(tip)
    ]
    assert history == snapshots[::-1]


def test_stored_bytes_grow_with_new_messages_not_with_length(repo: Repo) -> None:
    """Committing every step costs about the new messages, not the whole conversation."""
    recorder, loop = Recorder(repo, "session"), AgentLoop(seed=2, tool_bytes=6000)
    messages, rewritten = [SYSTEM], 0
    for _ in range(300):
        messages = messages + loop.step()
        recorder.commit(messages)
        rewritten += len(canonical_json(messages))  # what one blob per step would store
    unique = sum(len(message_blob(m).data) for m in messages)
    stored = stored_bytes(repo)
    assert stored <= 1.5 * unique
    assert stored * 50 < rewritten


def test_window_compaction_stores_about_one_path(
    store: MemoryStore, repo: Repo
) -> None:
    """Dropping old messages rewrites the chunks at the cut, not the kept tail."""
    recorder = Recorder(repo, "session")
    messages = _long(recorder, AgentLoop(seed=3, tool_bytes=200), 1500)
    assert recorder.vector is not None
    bound = 2 * _depth(repo, recorder.vector) + 2  # + tree and commit
    for keep in (2500, 1000, 40):
        messages = window(messages, keep)
        added = _new_objects(store, repo, lambda: recorder.commit(messages))
        assert len(added) <= bound


def test_summary_provenance_is_the_diff_against_the_parent(repo: Repo) -> None:
    """What a summary replaced is exactly the parent commit's messages it cut out."""
    recorder = Recorder(repo, "session")
    messages = _run(recorder, AgentLoop(seed=4), [SYSTEM], 400)
    parent = repo.get_ref("session")
    assert parent is not None
    compacted = summarize(messages, keep=50, step=400)
    child = recorder.commit(compacted)
    before, after = conversation_at(repo, parent), conversation_at(repo, child)
    cut = len(messages) - 50
    summary_id = message_blob(compacted[1]).id
    assert before.diff(after) == [Splice(1, cut, (summary_id,))]
    replaced = read_messages(repo, before)[1:cut]
    assert replaced == messages[1:cut]
    commit = repo.get(child, Commit)
    assert commit is not None and commit.parents == (parent,)


def test_trimming_scattered_tool_results(store: MemoryStore, repo: Repo) -> None:
    """Trimming tool results in place stores the chunks holding them, nothing else."""
    recorder = Recorder(repo, "session")
    messages = _long(recorder, AgentLoop(seed=5, tool_bytes=2000), 1000)
    old = recorder.vector
    assert old is not None
    trimmed = trim_tool_results(messages, limit=1000, every=150)
    changed = sum(1 for a, b in zip(messages, trimmed) if a is not b)
    added = _new_objects(store, repo, lambda: recorder.commit(trimmed))
    nodes = [oid for oid in added if store.object_type(repo.name, oid) == "vector"]
    assert changed == 5
    assert len(nodes) <= 2 * changed + _depth(repo, old)
    result = list(old)
    for splice in reversed(old.diff(recorder.vector)):  # type: ignore[arg-type]
        result[splice.start : splice.stop] = splice.ids
    assert result == [message_blob(m).id for m in trimmed]


def test_repeated_identical_messages_keep_chunks_bounded(repo: Repo) -> None:
    """A loop repeating one message (same id each time) still fills chunks of CHUNK_MIN."""
    recorder = Recorder(repo, "session")
    nudge: Message = {"role": "user", "content": "continue"}
    messages = [SYSTEM]
    for _ in range(100):
        messages = messages + [nudge] * 20
        recorder.commit(messages)
    assert recorder.vector is not None
    leaves = _leaves(repo, recorder.vector)
    assert all(len(leaf.children) >= CHUNK_MIN for leaf in leaves[:-1])
    assert len(leaves) <= len(messages) // CHUNK_MIN + 1


def _leaves(repo: Repo, vector: Vector) -> list[VectorNode]:
    out, stack = [], [repo.get(vector.id, VectorNode)]
    while stack:
        node = stack.pop()
        assert node is not None
        if node.level == 0:
            out.append(node)
        else:
            stack.extend(repo.get(c, VectorNode) for c in reversed(node.children))
    return out


def test_compacted_messages_live_as_long_as_their_history(
    store: MemoryStore, repo: Repo
) -> None:
    """Retention follows history: cutting it releases what compaction replaced."""
    recorder = Recorder(repo, "session")
    messages = _run(recorder, AgentLoop(seed=6), [SYSTEM], 200)
    dropped = {message_blob(m).id for m in messages[1:-20]}
    compacted = summarize(messages, keep=20, step=200)
    tip = recorder.commit(compacted)
    repo.prune(expire=0)
    assert dropped <= set(store.list_objects(repo.name))  # the parent commit keeps them

    commit = repo.get(tip, Commit)
    assert commit is not None
    cut = repo.put(Commit(commit.tree, (), commit.payload))  # same state, no history
    assert repo.set_ref("session", cut, tip)
    repo.prune(expire=0)
    assert not dropped & set(store.list_objects(repo.name))
    assert read_messages(repo, conversation_at(repo, cut)) == compacted


def test_a_fork_shares_the_conversation(store: MemoryStore, repo: Repo) -> None:
    """Branching from a commit shares every chunk; each branch then grows on its own."""
    main = Recorder(repo, "main")
    messages = _run(main, AgentLoop(seed=7), [SYSTEM], 300)
    tip = repo.get_ref("main")
    assert tip is not None and repo.set_ref("retry", tip, None)
    retry, _ = Recorder.resume(repo, "retry")
    other = messages + [{"role": "user", "content": "try another approach"}]
    added = _new_objects(store, repo, lambda: retry.commit(other))
    assert len(added) <= _depth(repo, retry.vector) + 3  # type: ignore[arg-type]  # + message, tree, commit
    main.commit(messages + [{"role": "user", "content": "go on"}])
    assert read_messages(repo, conversation_at(repo, repo.get_ref("retry"))) == other  # type: ignore[arg-type]


def test_resume_continues_the_same_vector(repo: Repo) -> None:
    """A paused conversation picks up from its ref and stays the canonical list."""
    first = Recorder(repo, "session")
    loop = AgentLoop(seed=8)
    messages = _run(first, loop, [SYSTEM], 150)
    resumed, restored = Recorder.resume(repo, "session")
    assert restored == messages
    messages = _run(resumed, loop, restored, 50)
    assert resumed.vector == Vector.build(repo, [message_blob(m).id for m in messages])


def test_a_conversation_tree_can_carry_more_than_messages(repo: Repo) -> None:
    """The vector is one entry of the committed tree; state next to it is the caller's."""
    recorder = Recorder(repo, "session")
    _run(recorder, AgentLoop(seed=9), [SYSTEM], 5)
    assert recorder.vector is not None
    state = repo.put(Blob(canonical_json({"tokens": 1234})))
    tree = repo.put(
        Tree(
            (
                TreeEntry("messages", "vector", recorder.vector.id),
                TreeEntry("state", "blob", state),
            )
        )
    )
    commit = repo.commit("session", tree)
    assert conversation_at(repo, commit) == recorder.vector
