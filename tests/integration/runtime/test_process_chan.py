# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Process Chans in a process task's arguments: they cross into the child
as references, over a link made for the run, and work there as here."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest

from appinfra.log import LogConfig, LoggerFactory
from appinfra.runtime import Chan, ProcessExitError, Runtime
from appinfra.runtime.chan import ClosedError

# Seconds a call expected to end now may take: the failure path, not a wait
DUE = 10.0


@pytest.fixture
def rt() -> Iterator[Runtime]:
    """A runtime with a real logger: the runtime carries it into a child
    its Chans cross to, which a mock cannot be."""
    runtime = Runtime(LoggerFactory.create_root(LogConfig.from_params(level="warning")))
    runtime.start()
    yield runtime
    runtime.stop()


# The children run these by name: module level, as the spawn method needs


def greet(out: Chan[str]) -> None:
    out.send("hello", timeout=DUE)


def double_each(requests: Chan[tuple[int, Chan[int]]]) -> None:
    for x, reply in requests:
        reply.send(2 * x, timeout=DUE)


def ask(requests: Chan[tuple[str, Chan[str]]]) -> str:
    reply: Chan[str] = Chan(1, process=True)
    requests.send(("ping", reply), timeout=DUE)
    return reply.recv(timeout=DUE)


def wait_forever(inbox: Chan[Any]) -> None:
    inbox.recv()


def close_it(chan: Chan[Any]) -> None:
    chan.close()  # posted: the child returns without waiting for it


def set_and_send(event: Any, out: Chan[int]) -> None:
    event.set()
    out.send(1, timeout=DUE)


def _parked(chan: Chan[Any], receivers: int) -> bool:
    """Whether *receivers* receives wait at *chan* before DUE: a child's call
    parks here after its frame crosses, which signals nothing. The deadline
    is the failure path."""
    deadline = time.monotonic() + DUE
    while len(chan._receivers) != receivers:  # Private
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


class TestCrossing:
    def test_a_child_sends_on_a_chan_of_the_parent(self, rt: Runtime) -> None:
        out: Chan[str] = Chan(1, process=True)
        t = rt.spawn(greet, out, process=True)
        assert out.recv(timeout=DUE) == "hello"
        t.wait(timeout=DUE)

    def test_a_reply_chan_of_the_parent_is_answered_by_the_child(
        self, rt: Runtime
    ) -> None:
        """Capacity 0: each request handed straight to the child's receive."""
        requests: Chan[tuple[int, Chan[int]]] = Chan(0, process=True)
        t = rt.spawn(double_each, requests, process=True)
        for x in (1, 21):
            reply: Chan[int] = Chan(1, process=True)
            requests.send((x, reply), timeout=DUE)
            assert reply.recv(timeout=DUE) == 2 * x
        requests.close()  # ends the child's iteration
        t.wait(timeout=DUE)

    def test_a_reply_chan_of_the_child_is_answered_by_the_parent(
        self, rt: Runtime
    ) -> None:
        requests: Chan[tuple[str, Chan[str]]] = Chan(1, process=True)
        t = rt.spawn(ask, requests, process=True)
        message, reply = requests.recv(timeout=DUE)
        reply.send(message + "-pong", timeout=DUE)
        assert t.wait(timeout=DUE) == "ping-pong"

    def test_a_shared_event_crosses_next_to_a_chan(self, rt: Runtime) -> None:
        """Made from the children's context, it pickles only as the child
        starts: the Chan's link does not change that."""
        event = rt.process_context.Event()
        out: Chan[int] = Chan(1, process=True)
        t = rt.spawn(set_and_send, event, out, process=True)
        assert out.recv(timeout=DUE) == 1
        t.wait(timeout=DUE)
        assert event.is_set()


class TestEnds:
    def test_a_close_the_child_posts_last_reaches_the_chan(self, rt: Runtime) -> None:
        """Posted, not waited for, then the child ends: the run's end here
        still applies it before dropping what it handed the child."""
        chan: Chan[int] = Chan(1, process=True)
        t = rt.spawn(close_it, chan, process=True)
        t.wait(timeout=DUE)
        with pytest.raises(ClosedError):
            chan.recv(timeout=0)

    def test_a_child_killed_leaves_the_chan_whole(self, rt: Runtime) -> None:
        """Its waiting receive goes with its link; a value sent after is
        kept for the next receiver."""
        inbox: Chan[int] = Chan(1, process=True)
        t = rt.spawn(wait_forever, inbox, process=True)
        assert _parked(inbox, receivers=1)
        assert t.process is not None
        t.process.kill()
        with pytest.raises(ProcessExitError):
            t.wait(timeout=DUE)
        assert _parked(inbox, receivers=0)
        inbox.send(5, timeout=0)
        assert inbox.recv(timeout=0) == 5

    def test_a_local_chan_cannot_cross(self, rt: Runtime) -> None:
        t = rt.spawn(greet, Chan(1), process=True)
        with pytest.raises(TypeError, match="process=True"):
            t.wait(timeout=DUE)
