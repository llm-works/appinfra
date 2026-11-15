# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
An agent conversation committed at every step: the workload vectors are built for.

Messages are chat-style dicts stored as blobs; the conversation is a vector of their ids
in a tree, committed on a ref after every step. Compaction comes in the three shapes
agent loops use: dropping old messages (sliding window), replacing them with a summary
message, and trimming large tool results in place. Shared by the unit, integration and
performance tests.
"""

from __future__ import annotations

import json
import random
from typing import Any

from appinfra.cas import (
    Blob,
    Commit,
    Repo,
    Tree,
    TreeEntry,
    Vector,
    canonical_json,
)

Message = dict[str, Any]


def message_blob(message: Message) -> Blob:
    """The blob a message is stored as."""
    return Blob(canonical_json(message))


class AgentLoop:
    """Generates the messages of an agent loop: user turns, tool calls and their results."""

    def __init__(
        self, seed: int, tool_bytes: int = 1500, text_bytes: int = 300
    ) -> None:
        self._rng = random.Random(seed)
        self._step = 0
        self._tool_bytes = tool_bytes
        self._text_bytes = text_bytes

    def _text(self, size: int) -> str:
        words = (
            self._rng.choice(("alpha", "beta", "gamma", "delta")) for _ in range(size)
        )
        return " ".join(words)[:size]

    def step(self) -> list[Message]:
        """Return the messages one LLM step adds: a tool call and its result, or a reply."""
        self._step += 1
        n, messages = self._step, []
        if n % 5 == 1:
            messages.append({"role": "user", "content": f"turn {n}: {self._text(80)}"})
        if n % 5 == 0:
            messages.append(
                {"role": "assistant", "content": f"{n}: {self._text(self._text_bytes)}"}
            )
            return messages
        call = {
            "id": f"call-{n}",
            "name": "web_fetch",
            "arguments": {"url": f"https://x/{n}"},
        }
        messages.append({"role": "assistant", "content": "", "tool_calls": [call]})
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": self._text(self._tool_bytes),
            }
        )
        return messages


SYSTEM: Message = {"role": "system", "content": "You are a careful research agent."}


def window(messages: list[Message], keep: int) -> list[Message]:
    """Sliding-window compaction: the system message and the last ``keep`` others."""
    return [messages[0], *messages[1:][-keep:]]


def summarize(messages: list[Message], keep: int, step: int) -> list[Message]:
    """Summary compaction: older messages replaced by one summary message."""
    summary = {
        "role": "user",
        "content": f"[summary at step {step}] of {len(messages) - 1 - keep}",
    }
    return [messages[0], summary, *messages[1:][-keep:]]


def trim_tool_results(messages: list[Message], limit: int, every: int) -> list[Message]:
    """Tool-result trimming: every ``every``-th large tool result cut to a stub, in place."""
    trimmed, seen = [], 0
    for message in messages:
        if message["role"] == "tool" and len(message["content"]) > limit:
            seen += 1
            if seen % every == 0:
                message = {
                    **message,
                    "content": f"[trimmed {len(message['content'])} chars]",
                }
        trimmed.append(message)
    return trimmed


class Recorder:
    """
    Commits a conversation at every step, storing each message once.

    The caller hands over the whole message list as it is now (after any compaction);
    message ids are hashed only for messages not seen before, and only new messages are
    stored. ``Vector.assign`` turns the list into a version that shares every unchanged
    chunk with the last one.
    """

    def __init__(self, repo: Repo, ref: str, vector: Vector | None = None) -> None:
        self.repo, self.ref = repo, ref
        self.vector = vector
        self._ids: dict[int, tuple[Message, Blob]] = {}
        self._stored: set[str] = set(vector) if vector is not None else set()

    @classmethod
    def resume(cls, repo: Repo, ref: str) -> tuple[Recorder, list[Message]]:
        """Pick a conversation up from its ref, as a paused turn resumes."""
        commit_id = repo.get_ref(ref)
        assert commit_id is not None
        vector = conversation_at(repo, commit_id)
        return cls(repo, ref, vector), read_messages(repo, vector)

    def _blobs(self, messages: list[Message]) -> list[Blob]:
        known = {id(m): pair for m in messages if (pair := self._ids.get(id(m)))}
        blobs = []
        for message in messages:
            pair = known.get(id(message))
            if pair is None or pair[0] is not message:
                pair = (message, message_blob(message))
                known[id(message)] = pair
            blobs.append(pair[1])
        self._ids = known
        return blobs

    def commit(self, messages: list[Message]) -> str:
        """Store the conversation as it is now and commit it on the ref."""
        blobs = self._blobs(messages)
        ids = [blob.id for blob in blobs]
        with self.repo.batch() as batch:
            for blob in blobs:
                if blob.id not in self._stored:
                    batch.put(blob)
            vector = (
                self.vector.on(batch).assign(ids)
                if self.vector is not None
                else Vector.build(batch, ids)
            )
            tree = batch.put(Tree((TreeEntry("messages", "vector", vector.id),)))
        self.vector = vector.on(self.repo)
        self._stored = set(ids)
        return self.repo.commit(self.ref, tree)


def conversation_at(repo: Repo, commit_id: str) -> Vector:
    """The message vector committed at ``commit_id``."""
    commit = repo.get(commit_id, Commit)
    assert commit is not None
    tree = repo.get(commit.tree, Tree)
    assert tree is not None
    entry = tree.get("messages")
    assert entry is not None
    return Vector(repo, entry.id)


def read_messages(repo: Repo, vector: Vector) -> list[Message]:
    """The messages of a conversation vector, decoded."""
    messages = []
    for element in vector:
        blob = repo.get(element, Blob)
        assert blob is not None
        messages.append(json.loads(blob.data))
    return messages


def stored_bytes(repo: Repo) -> int:
    """Bytes of every object stored in the repository."""
    total = 0
    for object_id in repo._store.list_objects(repo.name):
        found = repo._store.read_object(repo.name, object_id)
        assert found is not None
        total += len(found[1])
    return total
