# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Correlator: one stream of messages routed by key to the calls waiting on
them, the rest to an inbox. The peer here answers inside send(), before the
call starts waiting: a route registered after sending would miss it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

from appinfra.runtime import ChanClosedError, ChanResponseError, Correlator


@dataclass(frozen=True)
class Msg:
    id: str
    body: Any = None
    error: str | None = None
    final: bool = True


@dataclass
class Peer:
    """The far side of the transport: what was sent, and the answers it gives
    to each request id, delivered as the request is sent; *on_send* runs in
    the send instead."""

    answers: dict[str, list[Msg]] = field(default_factory=dict)
    sent: list[Msg] = field(default_factory=list)
    correlator: Correlator[Msg] | None = None
    on_send: Callable[[], None] | None = None

    def send(self, message: Msg, timeout: float | None) -> None:
        if self.on_send is not None:
            self.on_send()
            return
        self.sent.append(message)
        assert self.correlator is not None
        for answer in self.answers.get(message.id, []):
            self.correlator.deliver(answer)


def _correlator(peer: Peer) -> Correlator[Msg]:
    correlator: Correlator[Msg] = Correlator(
        peer.send,
        key=lambda m: m.id,
        failed=lambda m: m.error is not None,
        final=lambda m: m.final,
    )
    peer.correlator = correlator
    return correlator


@pytest.fixture
def peer() -> Peer:
    return Peer()


class TestSubmit:
    def test_the_reply_with_the_requests_key_is_returned(self, peer: Peer) -> None:
        peer.answers["a"] = [Msg("a", 42)]
        c = _correlator(peer)
        assert c.submit(Msg("a"), timeout=1.0) == Msg("a", 42)
        assert peer.sent == [Msg("a")]

    def test_another_key_goes_to_the_inbox_not_to_the_call(self, peer: Peer) -> None:
        """A request from the peer, sent on the same stream ahead of the
        reply."""
        peer.answers["a"] = [Msg("x", "theirs"), Msg("a", "mine")]
        c = _correlator(peer)
        assert c.submit(Msg("a"), timeout=1.0).body == "mine"
        assert c.recv(timeout=0) == Msg("x", "theirs")

    def test_a_failed_reply_raises_with_it(self, peer: Peer) -> None:
        peer.answers["a"] = [Msg("a", error="no")]
        c = _correlator(peer)
        with pytest.raises(ChanResponseError) as caught:
            c.submit(Msg("a"), timeout=1.0)
        assert caught.value.response == Msg("a", error="no")

    def test_no_reply_in_time_raises_and_leaves_no_route(self, peer: Peer) -> None:
        """The reply arriving after: no call waits for it, so it is the inbox's."""
        c = _correlator(peer)
        with pytest.raises(TimeoutError):
            c.submit(Msg("a"), timeout=0)
        c.deliver(Msg("a", "late"))
        assert c.recv(timeout=0) == Msg("a", "late")

    def test_a_key_already_waited_on_is_refused(self, peer: Peer) -> None:
        c = _correlator(peer)

        def submit_again() -> None:
            c.submit(Msg("a"), timeout=0)

        peer.on_send = submit_again
        with pytest.raises(ValueError, match="'a'"):
            c.submit(Msg("a"), timeout=0)

    def test_a_send_that_raises_leaves_no_route(self, peer: Peer) -> None:
        c = _correlator(peer)

        def full() -> None:
            raise OSError("full")

        peer.on_send = full
        with pytest.raises(OSError, match="full"):
            c.submit(Msg("a"), timeout=1.0)
        c.deliver(Msg("a", "after"))
        assert c.recv(timeout=0) == Msg("a", "after")


class TestStream:
    def test_chunks_until_the_final_one(self, peer: Peer) -> None:
        peer.answers["s"] = [Msg("s", 1, final=False), Msg("s", 2, final=False)]
        peer.answers["s"].append(Msg("s", 3))
        c = _correlator(peer)
        assert [m.body for m in c.stream(Msg("s"), timeout=1.0)] == [1, 2, 3]

    def test_a_failed_chunk_raises_with_it(self, peer: Peer) -> None:
        peer.answers["s"] = [Msg("s", 1, final=False), Msg("s", error="broke")]
        c = _correlator(peer)
        chunks = c.stream(Msg("s"), timeout=1.0)
        assert next(chunks).body == 1
        with pytest.raises(ChanResponseError):
            next(chunks)

    def test_a_stream_left_early_leaves_no_route(self, peer: Peer) -> None:
        peer.answers["s"] = [Msg("s", 1, final=False)]
        c = _correlator(peer)
        chunks = c.stream(Msg("s"), timeout=1.0)
        assert next(chunks).body == 1
        chunks.close()
        c.deliver(Msg("s", 2))
        assert c.recv(timeout=0) == Msg("s", 2)


class TestClose:
    def test_a_waiting_call_fails(self, peer: Peer) -> None:
        c = _correlator(peer)

        peer.on_send = c.close
        with pytest.raises(ChanClosedError):
            c.submit(Msg("a"), timeout=1.0)

    def test_calls_after_it_fail_and_deliver_drops(self, peer: Peer) -> None:
        c = _correlator(peer)
        c.close()
        c.close()  # idempotent
        c.deliver(Msg("x"))  # the poll thread is not told: dropped
        with pytest.raises(ChanClosedError):
            c.submit(Msg("a"), timeout=1.0)
        with pytest.raises(ChanClosedError):
            c.recv(timeout=0)
        assert peer.sent == []

    def test_the_inbox_drains_before_it_reports_closed(self, peer: Peer) -> None:
        c = _correlator(peer)
        c.deliver(Msg("x"))
        c.close()
        assert c.recv(timeout=0) == Msg("x")
        with pytest.raises(ChanClosedError):
            c.recv(timeout=0)


def test_send_goes_straight_through(peer: Peer) -> None:
    c = _correlator(peer)
    c.send(Msg("r", "reply"), timeout=1.0)
    assert peer.sent == [Msg("r", "reply")]
