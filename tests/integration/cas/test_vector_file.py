# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A conversation committed at every step on a FileStore: restarts, crashes, disk usage."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from appinfra.cas import Commit, FileStore, Repo, Vector
from appinfra.cas.conformance import dangling_links
from appinfra.log import Logger
from tests.helpers.cas_conversation import (
    SYSTEM,
    AgentLoop,
    Message,
    Recorder,
    conversation_at,
    message_blob,
    read_messages,
    summarize,
    window,
)

LG = Logger("test-cas")


def _disk_bytes(root: Path) -> int:
    """Bytes of every object file under a store root."""
    return sum(p.stat().st_size for p in root.glob("*/objects/*/*"))


def _steps(
    recorder: Recorder, loop: AgentLoop, messages: list[Message], steps: int
) -> list[Message]:
    for step in range(1, steps + 1):
        messages = messages + loop.step()
        if step % 60 == 0:
            messages = summarize(messages, keep=40, step=step)
        recorder.commit(messages)
    return messages


@pytest.mark.parametrize("fsync", [True, False])
def test_conversation_survives_a_restart(tmp_path: Path, fsync: bool) -> None:
    """A new store on the same directory resumes the conversation where it stopped."""
    loop = AgentLoop(seed=11)
    first = Recorder(FileStore(LG, tmp_path, fsync=fsync).repo("agent"), "session")
    messages = _steps(first, loop, [SYSTEM], 100)

    repo = FileStore(LG, tmp_path, fsync=fsync).repo("agent")
    resumed, restored = Recorder.resume(repo, "session")
    assert restored == messages
    messages = _steps(resumed, loop, restored, 30)
    assert (
        read_messages(repo, conversation_at(repo, repo.get_ref("session"))) == messages
    )  # type: ignore[arg-type]
    assert dangling_links(repo._store, "agent") == []


def test_disk_usage_follows_the_new_messages(tmp_path: Path) -> None:
    """Object files on disk stay within a small factor of the messages they hold."""
    repo = FileStore(LG, tmp_path, fsync=False).repo("agent")
    recorder, loop = Recorder(repo, "session"), AgentLoop(seed=12, tool_bytes=6000)
    messages = [SYSTEM]
    for _ in range(200):
        messages = messages + loop.step()
        recorder.commit(messages)
    unique = sum(len(message_blob(m).data) for m in messages)
    assert _disk_bytes(tmp_path) <= 1.6 * unique  # object headers included


def test_a_crash_inside_a_batch_leaves_no_dangling_link(tmp_path: Path) -> None:
    """A batch cut short after any number of writes leaves every stored link stored."""
    store = FileStore(LG, tmp_path, fsync=False)
    repo = store.repo("agent")
    recorder, loop = Recorder(repo, "session"), AgentLoop(seed=13)
    messages = _steps(recorder, loop, [SYSTEM], 80)
    attempt = window(messages + loop.step(), keep=30)
    write = FileStore.write_object
    failures = 0
    while True:
        calls = 0

        def failing(self: FileStore, *args: object) -> None:
            nonlocal calls
            calls += 1
            if calls > failures + 1:
                raise OSError("disk gone")
            write(self, *args)  # type: ignore[arg-type]

        try:
            with mock.patch.object(FileStore, "write_object", failing):
                Recorder(repo, "session", recorder.vector).commit(attempt)
            break
        except OSError:
            failures += 1
            assert dangling_links(store, "agent") == []
    assert failures >= 4  # cut after each of the batch's writes, then the commit's
    assert (
        read_messages(repo, conversation_at(repo, repo.get_ref("session"))) == attempt
    )  # type: ignore[arg-type]


def test_cutting_history_frees_compacted_messages_on_disk(tmp_path: Path) -> None:
    """With the history before a summary gone, prune deletes the summarized messages."""
    repo: Repo = FileStore(LG, tmp_path, fsync=False).repo("agent")
    recorder, loop = Recorder(repo, "session"), AgentLoop(seed=14, tool_bytes=4000)
    messages = [SYSTEM]
    for _ in range(150):
        messages = messages + loop.step()
        recorder.commit(messages)
    compacted = summarize(messages, keep=20, step=150)
    tip = recorder.commit(compacted)
    before = _disk_bytes(tmp_path)

    commit = repo.get(tip, Commit)
    assert commit is not None
    cut = repo.put(Commit(commit.tree, (), commit.payload))
    assert repo.set_ref("session", cut, tip)
    repo.prune(expire=0)
    kept = sum(len(message_blob(m).data) for m in compacted)
    assert _disk_bytes(tmp_path) < before / 10
    assert _disk_bytes(tmp_path) <= 2 * kept + 4096
    assert Vector(repo, conversation_at(repo, cut).id) == recorder.vector
