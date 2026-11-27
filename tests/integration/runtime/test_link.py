# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The link between two processes, and its home side: calls on a Chan homed
on one side, sent by hand here as a proxy will send them."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Chan, Runtime
from appinfra.runtime.chan import ClosedError
from appinfra.runtime.chan.home import Home
from appinfra.runtime.chan.link import (
    Call,
    Cancel,
    Link,
    LinkEnd,
    Push,
    Release,
    Result,
    link,
)

# Seconds a frame expected now may take: the failure path, not a wait
DUE = 5.0


# The child imports these by name: module level, as the spawn method needs


def sends_then_closes(end: LinkEnd) -> None:
    """Open the link, send one frame, close it."""
    opened = end.open()
    opened.send(Release(1))
    opened.close()


def sends_then_exits(end: LinkEnd) -> None:
    """Open the link, send one frame, and end the process without a close,
    once the parent acked the frame: a process that exits before its frames
    are on the pipe may lose them, as pipe() says."""
    opened = end.open()
    opened.send(Release(1))
    opened.recv(timeout=DUE)  # the ack
    os._exit(0)


@dataclass
class Homed:
    """A home on one end of a link, its frames handled by a reader thread,
    and the other end, from which the test sends calls by hand."""

    home: Home
    proxy: Link
    chan: Chan[Any]
    object_id: int

    def call(self, call_id: int, op: str, *args: Any, timeout: float | None) -> None:
        """Send a call on the homed Chan."""
        self.proxy.send(Call(call_id, self.object_id, op, args, timeout))

    def result(self) -> Result:
        """The next Result from the home."""
        frame = self.proxy.recv(timeout=DUE)
        assert isinstance(frame, Result)
        return frame


@pytest.fixture
def homed() -> Iterator[Homed]:
    near, far = link()
    home_link, proxy = near.open(), far.open()
    home = Home(home_link)

    def read() -> None:
        for frame in home_link:
            assert isinstance(frame, Call | Cancel | Release)
            home.handle(frame)

    threading.Thread(target=read, daemon=True).start()
    chan: Chan[Any] = Chan(1)
    yield Homed(home, proxy, chan, home.register(chan))
    home.close()
    proxy.close()
    home_link.close()


class TestLink:
    def test_frames_cross_both_ways_intact(self) -> None:
        near, far = link()
        a, b = near.open(), far.open()
        frames = [
            Call(1, 2, "send", ({"x": [1, 2]},), 3.0),
            Result(1, value=(4, 5)),
            Result(2, error=ValueError("no")),
            Cancel(3),
            Push(2, 7, "latest"),
            Release(2),
        ]
        try:
            for frame in frames:
                a.send(frame)
            got = [b.recv(timeout=DUE) for _ in frames]
            b.send(Result(9, cancelled=True))
            back = a.recv(timeout=DUE)
        finally:
            a.close()
            b.close()
        assert got[:1] + got[3:] == frames[:1] + frames[3:]
        assert got[1] == frames[1]
        assert isinstance(got[2], Result) and str(got[2].error) == "no"
        assert back == Result(9, cancelled=True)

    @pytest.mark.parametrize("child", [sends_then_closes, sends_then_exits])
    def test_the_other_process_ending_ends_the_iteration(self, child: Any) -> None:
        """Its frames are taken first; then the link reads as closed, whether
        the child closed its end or its process just ended."""
        near, far = link()
        opened = near.open()
        rt = Runtime(MagicMock())
        rt.start()
        try:
            rt.spawn(child, far, process=True)
            assert opened.recv(timeout=30.0) == Release(1)  # the child has its end
            far.release()  # EOF needs every copy of the child's end closed
            opened.send(Result(0))  # the ack sends_then_exits waits for
            assert list(opened) == []
        finally:
            opened.close()
            rt.stop()


class TestHome:
    def test_a_call_that_can_complete_is_answered_at_once(self, homed: Homed) -> None:
        homed.chan.send(7)
        homed.call(1, "recv", timeout=DUE)
        assert homed.result() == Result(1, value=7)
        homed.call(2, "send", 8, timeout=DUE)
        assert homed.result() == Result(2)
        assert homed.chan.recv(timeout=0) == 8

    def test_a_parked_recv_takes_the_next_local_send(self, homed: Homed) -> None:
        homed.call(1, "recv", timeout=DUE)
        homed.chan.send(7)
        assert homed.result() == Result(1, value=7)

    def test_a_parked_send_completes_as_room_is_made(self, homed: Homed) -> None:
        homed.chan.send(1)  # full
        homed.call(2, "send", 2, timeout=DUE)
        assert homed.chan.recv(timeout=0) == 1  # its slot goes to the parked send
        assert homed.result() == Result(2)
        assert homed.chan.recv(timeout=0) == 2

    def test_a_call_past_its_deadline_takes_nothing(self, homed: Homed) -> None:
        homed.call(1, "recv", timeout=0.05)
        result = homed.result()
        assert isinstance(result.error, TimeoutError)
        homed.chan.send(7)  # after the timeout: stays in the Chan
        assert homed.chan.recv(timeout=0) == 7

    def test_timeout_zero_does_not_park(self, homed: Homed) -> None:
        homed.call(1, "recv", timeout=0)
        assert isinstance(homed.result().error, TimeoutError)
        homed.chan.send(7)
        assert homed.chan.recv(timeout=0) == 7

    def test_a_cancelled_call_takes_nothing(self, homed: Homed) -> None:
        homed.call(1, "recv", timeout=None)
        homed.proxy.send(Cancel(1))
        assert homed.result() == Result(1, cancelled=True)
        homed.chan.send(7)
        assert homed.chan.recv(timeout=0) == 7

    def test_a_cancel_after_the_hand_over_changes_nothing(self, homed: Homed) -> None:
        """The value was handed over first: its Result stands, and the Cancel
        adds no second one. The sentinel's Result comes next, as results are
        answered in order, so there was none in between."""
        homed.call(1, "recv", timeout=None)
        homed.chan.send(7)
        assert homed.result() == Result(1, value=7)
        homed.proxy.send(Cancel(1))
        homed.call(2, "recv", timeout=0)  # the sentinel
        assert homed.result().call_id == 2
        assert len(homed.chan) == 0  # the value was not given back either

    def test_a_cancel_before_the_hand_over_leaves_the_value(self, homed: Homed) -> None:
        homed.call(1, "recv", timeout=None)
        homed.proxy.send(Cancel(1))
        assert homed.result() == Result(1, cancelled=True)
        homed.chan.send(7)
        homed.call(2, "recv", timeout=0)
        assert homed.result() == Result(2, value=7)

    def test_a_released_chan_is_closed_to_calls(self, homed: Homed) -> None:
        homed.proxy.send(Release(homed.object_id))
        homed.call(1, "recv", timeout=DUE)
        assert isinstance(homed.result().error, ClosedError)

    def test_a_close_ends_the_parked_calls(self, homed: Homed) -> None:
        homed.call(1, "recv", timeout=None)
        homed.call(2, "close", timeout=None)
        results = {r.call_id: r for r in (homed.result(), homed.result())}
        assert isinstance(results[1].error, ClosedError)
        assert results[2] == Result(2)
        homed.call(3, "send", 1, timeout=DUE)
        assert isinstance(homed.result().error, ClosedError)

    def test_a_home_closed_ends_its_parked_calls_quietly(self, homed: Homed) -> None:
        """The link ended: no one is left to answer, and a local send that
        would have woken a parked call just buffers its value."""
        homed.call(1, "recv", timeout=None)
        homed.call(2, "recv", timeout=0)  # once answered, call 1 is parked
        assert homed.result().call_id == 2
        homed.home.close()
        homed.chan.send(7)
        assert homed.chan.recv(timeout=0) == 7

    def test_a_wake_after_the_outbox_closed_raises_nothing(self, homed: Homed) -> None:
        """The window between the home's closed check and its outbox closing:
        the waker settling a parked call there is an unrelated send, which
        must not fail on the closed outbox."""
        homed.call(1, "recv", timeout=None)
        homed.call(2, "recv", timeout=0)
        assert homed.result().call_id == 2
        homed.home._outbox.close()  # Private: closed, the home not yet marked
        homed.chan.send(7)  # wakes call 1; its Result has nowhere to go
        assert len(homed.chan) == 0  # handed to the parked call, not buffered
