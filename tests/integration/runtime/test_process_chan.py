# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Process Chans in a process task's arguments: they cross into the child
as references, over a link made for the run, and work there as here."""

from __future__ import annotations

import threading
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


def send_range(out: Chan[int], start: int, count: int) -> None:
    for x in range(start, start + count):
        out.send(x, timeout=DUE)


def collect(inbox: Chan[int]) -> list[int]:
    """Every value this child received, until the Chan was closed."""
    return list(inbox)


def home_and_wait(out: Chan[Chan[int]]) -> None:
    """Make a Chan homed here, hand it to the parent, and wait on it."""
    mine: Chan[int] = Chan(1, process=True)
    out.send(mine, timeout=DUE)
    mine.recv()


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


CHILDREN = 4
VALUES = 20


class TestMany:
    """One Chan, its senders or its receivers in several processes."""

    def test_the_values_of_many_child_senders_each_arrive_once(
        self, rt: Runtime
    ) -> None:
        out: Chan[int] = Chan(0, process=True)
        tasks = [
            rt.spawn(send_range, out, i * VALUES, VALUES, process=True)
            for i in range(CHILDREN)
        ]
        got = [out.recv(timeout=DUE) for _ in range(CHILDREN * VALUES)]
        for t in tasks:
            t.wait(timeout=DUE)
        assert sorted(got) == list(range(CHILDREN * VALUES))

    def test_each_value_goes_to_exactly_one_of_many_child_receivers(
        self, rt: Runtime
    ) -> None:
        """Capacity 0: a send completes only once a child took the value, so
        the close after the last one leaves none behind."""
        inbox: Chan[int] = Chan(0, process=True)
        tasks = [rt.spawn(collect, inbox, process=True) for _ in range(CHILDREN)]
        for x in range(CHILDREN * VALUES):
            inbox.send(x, timeout=DUE)
        inbox.close()  # ends every child's iteration
        got = [x for t in tasks for x in t.wait(timeout=DUE)]
        assert sorted(got) == list(range(CHILDREN * VALUES))


class TestEnds:
    def test_a_home_killed_fails_the_calls_on_its_chan(self, rt: Runtime) -> None:
        """Its link at EOF: a receive under way and a send after both raise
        ClosedError, not wait out their timeout."""
        out: Chan[Chan[int]] = Chan(1, process=True)
        t = rt.spawn(home_and_wait, out, process=True)
        theirs = out.recv(timeout=DUE)
        errors: list[type[BaseException]] = []

        def receive() -> None:
            try:
                theirs.recv(timeout=DUE * 6)
            except BaseException as e:  # what ended it, whatever it is
                errors.append(type(e))

        receiving = threading.Thread(target=receive)
        receiving.start()
        assert t.process is not None
        t.process.kill()
        with pytest.raises(ProcessExitError):
            t.wait(timeout=DUE)
        receiving.join(DUE)
        assert errors == [ClosedError]
        with pytest.raises(ClosedError):
            theirs.send(1, timeout=DUE)

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
