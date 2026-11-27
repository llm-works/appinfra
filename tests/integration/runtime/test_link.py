# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The link between two processes, and its home side: calls on a Chan homed
on one side, sent by hand here as a proxy will send them."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import os
import pickle
import threading
import time
import weakref
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from appinfra.runtime import Chan, Runtime
from appinfra.runtime.chan import ClosedError, pipe
from appinfra.runtime.chan.home import Home
from appinfra.runtime.chan.link import (
    CAPACITY,
    Call,
    Cancel,
    Codec,
    Link,
    LinkEnd,
    Push,
    Release,
    Result,
    Return,
    link,
)

# Seconds a frame expected now may take: the failure path, not a wait
DUE = 5.0


# The child imports these by name: module level, as the spawn method needs


class _Payload:
    """A value whose copy at the home a test can watch being freed."""


class _Held:
    """A value only a home's parked call holds, watched for by its class."""


def _freed(kind: type) -> bool:
    """Whether every instance of *kind* in this process is freed before DUE.
    A poll: nothing signals the moment the last reference goes."""
    deadline = time.monotonic() + DUE
    while time.monotonic() < deadline:
        gc.collect()
        if not any(isinstance(o, kind) for o in gc.get_objects()):
            return True
    return False


def sends_then_closes(end: LinkEnd) -> None:
    """Open the link, send one frame, close it."""
    opened = end.open()
    opened.send(Release(1, 1))
    opened.close()


def sends_then_exits(end: LinkEnd) -> None:
    """Open the link, send one frame, and end the process without a close,
    once the parent acked the frame: a process that exits before its frames
    are on the pipe may lose them, as pipe() says."""
    opened = end.open()
    opened.send(Release(1, 1))
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
        """Send a call on the homed Chan, its arguments encoded."""
        self.proxy.send(Call(call_id, self.object_id, op, CODEC.encode(args), timeout))

    def result(self) -> Result:
        """The next Result from the home, its value decoded."""
        return _decoded(self.proxy.recv(timeout=DUE))


# Encodes and decodes the payloads, as an endpoint's codec does without
# process Chans in them
CODEC = Codec()


def _decoded(frame: Any) -> Result:
    """*frame*, a Result, with its value decoded if it has one."""
    assert isinstance(frame, Result)
    if frame.error is not None or frame.cancelled:
        return frame
    return replace(frame, value=CODEC.decode(frame.value))


def _serve(home: Home, home_link: Link) -> None:
    """Reader thread: each frame for the home handled, in order."""
    for frame in home_link:
        assert isinstance(frame, Call | Cancel | Release | Return)
        home.handle(frame)


@pytest.fixture
def homed() -> Iterator[Homed]:
    near, far = link()
    home_link, proxy = near.open(), far.open()
    home = Home(MagicMock(), home_link, CODEC)
    threading.Thread(target=_serve, args=(home, home_link), daemon=True).start()
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
            Call(1, 2, "send", CODEC.encode(({"x": [1, 2]},)), 3.0),
            Result(1, value=(4, 5)),
            Result(2, error=ValueError("no")),
            Cancel(3),
            Push(2, 7, "latest"),
            Release(2, 1),
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

    def test_a_link_that_cannot_be_made_leaves_no_pipe_open(self) -> None:
        """The second pipe failing: the first one's ends are released, not
        left to the garbage collector."""
        made: list[Any] = []

        def second_fails(capacity: int) -> Any:
            if made:
                raise OSError("too many open files")
            made.extend(pipe(capacity))
            return tuple(made)

        with (
            patch("appinfra.runtime.chan.link.pipe", side_effect=second_fails),
            pytest.raises(OSError, match="too many open files"),
        ):
            link()
        for end in made:
            with pytest.raises(RuntimeError, match="already opened or released"):
                end.release()

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
            assert opened.recv(timeout=30.0) == Release(1, 1)  # the child has its end
            far.release()  # EOF needs every copy of the child's end closed
            # The ack sends_then_exits waits for; sends_then_closes may have
            # closed its end already, which refuses it
            with contextlib.suppress(ClosedError):
                opened.send(Result(0))
            assert list(opened) == []
        finally:
            opened.close()
            rt.stop()

    def test_both_sides_closing_with_frames_unread_do_not_wait_on_each_other(
        self,
    ) -> None:
        """Each side sent past the link's capacity and read nothing: a close
        drops what is on its way in, so neither waits for the other to read."""
        a, b = _unread_both_ways()
        closers = [threading.Thread(target=end.close, daemon=True) for end in (a, b)]
        for closer in closers:
            closer.start()
        for closer in closers:
            closer.join(DUE)
        assert not any(closer.is_alive() for closer in closers)

    def test_both_sides_aclosing_with_frames_unread_do_not_wait_on_each_other(
        self,
    ) -> None:
        """As close(), awaited on the loop."""
        a, b = _unread_both_ways()

        async def both() -> None:
            await asyncio.wait_for(asyncio.gather(a.aclose(), b.aclose()), DUE)

        asyncio.run(both())


def _unread_both_ways() -> tuple[Link, Link]:
    """Both ends of a link, each having sent one frame more than the link
    carries before the other side reads: their writers wait for room."""
    near, far = link()
    a, b = near.open(), far.open()
    for end in (a, b):
        for i in range(CAPACITY + 1):
            end.send(Release(i, 1), timeout=DUE)
    return a, b


class TestHome:
    def test_a_call_that_can_complete_is_answered_at_once(self, homed: Homed) -> None:
        homed.chan.send(7)
        homed.call(1, "recv", timeout=DUE)
        assert homed.result() == Result(1, value=7, seq=1)
        homed.call(2, "send", 8, timeout=DUE)
        assert homed.result() == Result(2)
        assert homed.chan.recv(timeout=0) == 8

    def test_a_parked_recv_takes_the_next_local_send(self, homed: Homed) -> None:
        homed.call(1, "recv", timeout=DUE)
        homed.chan.send(7)
        assert homed.result() == Result(1, value=7, seq=1)

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

    def test_a_settled_call_is_not_kept_until_its_deadline(self, homed: Homed) -> None:
        """Its waiter, and the value it carried, go as it settles, not when
        its deadline would have passed."""
        homed.chan.send(1)  # full
        homed.call(1, "send", _Payload(), timeout=3600)
        homed.call(2, "recv", timeout=0)  # takes 1; the room goes to call 1
        results = {r.call_id: r for r in (homed.result(), homed.result())}
        assert results == {1: Result(1), 2: Result(2, value=1, seq=1)}
        received = homed.chan.recv(timeout=0)  # the home's copy of the payload
        assert isinstance(received, _Payload)
        gone = weakref.ref(received)
        del received
        gc.collect()
        assert gone() is None

    def test_an_expired_call_is_not_kept_after_its_deadline(self, homed: Homed) -> None:
        """Its waiter, and the value a send carried, go as it times out: the
        timer keeps nothing of it while it waits for the next deadline."""
        homed.chan.send(1)  # full
        homed.call(1, "send", _Held(), timeout=0.05)
        result = homed.result()
        assert result.call_id == 1
        assert isinstance(result.error, TimeoutError)
        # A frame after it: the fixture's reader holds the last frame it read,
        # which here would be the call, its value in args. No deadline: the
        # timer goes on waiting, with whatever it still holds
        homed.call(2, "recv", timeout=0)
        assert homed.result().call_id == 2
        assert _freed(_Held)

    def test_an_unbounded_timeout_leaves_the_other_deadlines_kept(
        self, homed: Homed
    ) -> None:
        """A deadline past what a wait can take (inf here) is waited out in
        slices: the timer goes on, and the calls after it still time out."""
        homed.call(1, "recv", timeout=float("inf"))
        for call_id in (2, 3):  # 3 comes once the timer is back at call 1's
            homed.call(call_id, "recv", timeout=0.05)
            result = homed.result()
            assert result.call_id == call_id
            assert isinstance(result.error, TimeoutError)
        homed.chan.send(7)  # call 1 is still parked
        assert homed.result() == Result(1, value=7, seq=1)

    def test_timeout_zero_does_not_park(self, homed: Homed) -> None:
        homed.call(1, "recv", timeout=0)
        assert isinstance(homed.result().error, TimeoutError)
        homed.chan.send(7)
        assert homed.chan.recv(timeout=0) == 7

    def test_a_negative_timeout_is_refused_before_anything_is_taken(
        self, homed: Homed
    ) -> None:
        """As Chan.recv() refuses it: the value stays in the Chan."""
        homed.chan.send(7)
        homed.call(1, "recv", timeout=-1)
        assert isinstance(homed.result().error, ValueError)
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
        assert homed.result() == Result(1, value=7, seq=1)
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
        assert homed.result() == Result(2, value=7, seq=1)

    def test_a_result_that_cannot_be_pickled_fails_its_call_alone(
        self, homed: Homed
    ) -> None:
        """Its call gets an error in its place, and the results after it are
        still sent: one bad value does not end the link."""
        homed.chan.send(threading.Lock())
        homed.call(1, "recv", timeout=DUE)
        result = homed.result()
        assert result.call_id == 1
        assert isinstance(result.error, pickle.PicklingError)
        homed.chan.send(7)
        homed.call(2, "recv", timeout=DUE)
        assert homed.result() == Result(2, value=7, seq=2)  # the lock was 1

    def test_values_given_back_are_received_in_their_send_order(self) -> None:
        """Taken by calls whose callers left, and given back out of order:
        received again as sent, before the rest of the buffer."""
        near, far = link()
        home_link, proxy = near.open(), far.open()
        home = Home(MagicMock(), home_link, CODEC)
        threading.Thread(target=_serve, args=(home, home_link), daemon=True).start()
        chan: Chan[Any] = Chan(3)
        object_id = home.register(chan)
        no_args = CODEC.encode(())
        try:
            for value in (1, 2, 3):
                chan.send(value)
            taken = []
            for call_id in (1, 2):
                proxy.send(Call(call_id, object_id, "recv", no_args, DUE))
                result = proxy.recv(timeout=DUE)
                assert isinstance(result, Result)
                taken.append(result)  # its value as encoded, as a Return sends it
            assert [(_decoded(r).value, r.seq) for r in taken] == [(1, 1), (2, 2)]
            for result in reversed(taken):
                proxy.send(Return(object_id, result.value, result.seq))
            proxy.send(Call(3, object_id, "recv", no_args, 0))  # after both Returns
            assert _decoded(proxy.recv(timeout=DUE)) == Result(3, value=1, seq=1)
            assert [chan.recv(timeout=0) for _ in range(2)] == [2, 3]
        finally:
            home.close()
            proxy.close()
            home_link.close()

    def test_a_chan_handed_over_twice_has_one_id(self, homed: Homed) -> None:
        assert homed.home.register(homed.chan) == homed.object_id

    def test_a_chan_is_dropped_once_every_handing_over_is_released(
        self, homed: Homed
    ) -> None:
        """Handed over twice, released once: a release can cross a second
        handing over still on its way, so the Chan stays until both are."""
        homed.home.register(homed.chan)
        homed.proxy.send(Release(homed.object_id, 1))
        homed.call(1, "recv", timeout=0)
        assert isinstance(homed.result().error, TimeoutError)  # still there
        homed.proxy.send(Release(homed.object_id, 1))
        homed.call(2, "recv", timeout=0)
        assert isinstance(homed.result().error, ClosedError)

    def test_arguments_that_cannot_be_decoded_fail_their_call_alone(
        self, homed: Homed
    ) -> None:
        """The frame arrives, so the call is answered: with the error, and
        the calls after it go on."""
        homed.proxy.send(Call(1, homed.object_id, "send", b"not a pickle", DUE))
        assert homed.result().error is not None
        homed.call(2, "len", timeout=DUE)
        assert homed.result() == Result(2, value=0)

    def test_a_released_chan_is_closed_to_calls(self, homed: Homed) -> None:
        homed.proxy.send(Release(homed.object_id, 1))
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

    def test_a_call_parking_after_the_home_closed_takes_nothing(
        self, homed: Homed
    ) -> None:
        """The window between a call finding its Chan and parking in it: a
        close there refuses the call, which would otherwise wait in the Chan
        for a value whose Result no one reads."""
        homed.home.close()
        call = Call(1, homed.object_id, "recv", CODEC.encode(()), None)
        with pytest.raises(ClosedError):
            homed.home._park(call, homed.chan, ())  # Private: the park in that window
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
