# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The link codec: process Chans inside values sent across a link arrive
as the same Chan, a proxy or the Chan itself. Two endpoints of one link in
one process; a Chan homed at each."""

from __future__ import annotations

import asyncio
import gc
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Chan
from appinfra.runtime.chan import ClosedError
from appinfra.runtime.chan.endpoint import Endpoint
from appinfra.runtime.chan.link import link
from appinfra.runtime.chan.proxy import _ChanProxy

# Seconds a call expected to end now may take: the failure path, not a wait
DUE = 5.0


@dataclass
class Linked:
    """Endpoint *a* homes *requests*; *b* holds its *proxy*."""

    a: Endpoint
    b: Endpoint
    requests: Chan[Any]
    proxy: _ChanProxy[Any]


@pytest.fixture
def linked() -> Iterator[Linked]:
    near, far = link()
    a, b = Endpoint(MagicMock(), near), Endpoint(MagicMock(), far)
    requests: Chan[Any] = Chan(2, process=True)
    proxy: _ChanProxy[Any] = _ChanProxy(b, a.home.register(requests))
    yield Linked(a, b, requests, proxy)
    b.close()
    a.close()


def _exported(endpoint: Endpoint, chan: Chan[Any]) -> bool:
    """Whether *endpoint*'s home still holds *chan* for the other side."""
    return id(chan) in endpoint.home._by_object


def _released(endpoint: Endpoint, chan: Chan[Any]) -> bool:
    """Whether *endpoint*'s home drops *chan* before DUE, its proxies across
    the link collected: the Release is posted by a finalizer, and read by
    the home's reader thread, so nothing signals it here. The deadline is
    the failure path."""
    deadline = time.monotonic() + DUE
    while _exported(endpoint, chan):
        if time.monotonic() > deadline:
            return False
        gc.collect()
        time.sleep(0.01)
    return True


class TestReferences:
    def test_a_reply_chan_in_a_request_is_answered_in_its_home(
        self, linked: Linked
    ) -> None:
        """Request/reply: the reply Chan crosses as a reference, so the
        answer reaches it where it was made."""
        reply: Chan[Any] = Chan(1, process=True)
        linked.proxy.send({"ask": 1, "reply": reply}, timeout=DUE)
        request = linked.requests.recv(timeout=0)
        assert isinstance(request["reply"], _ChanProxy)
        request["reply"].send(request["ask"] + 41, timeout=DUE)
        assert reply.recv(timeout=0) == 42

    def test_a_proxy_sent_to_its_home_arrives_as_the_chan_itself(
        self, linked: Linked
    ) -> None:
        linked.proxy.send({"me": linked.proxy}, timeout=DUE)
        assert linked.requests.recv(timeout=0)["me"] is linked.requests

    def test_one_chan_crossing_twice_arrives_as_one_proxy(self, linked: Linked) -> None:
        """The Result direction too: received through the proxy."""
        extra: Chan[Any] = Chan(1, process=True)
        linked.requests.send({"x": extra})
        linked.requests.send({"x": extra})
        first = linked.proxy.recv(timeout=DUE)["x"]
        second = linked.proxy.recv(timeout=DUE)["x"]
        assert isinstance(first, _ChanProxy)
        assert second is first

    def test_a_chan_given_back_arrives_as_itself_and_is_released(
        self, linked: Linked
    ) -> None:
        """A receive cancelled after the hand-over gives its value back: the
        Chan in it is the home's own again, and once the proxy the caller's
        side decoded is gone, it is no longer held there."""
        extra: Chan[Any] = Chan(1, process=True)
        object_id = linked.a.home.register(linked.requests)  # its own id again

        async def main() -> None:
            waiting = asyncio.create_task(linked.proxy.arecv(timeout=None))
            await asyncio.sleep(0)  # the task posts its call
            await linked.b.acall(object_id, "len", (), DUE)  # parked now
            linked.requests.send({"x": extra}, timeout=0)  # handed to it
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting

        asyncio.run(main())
        assert linked.requests.recv(timeout=DUE)["x"] is extra
        assert _released(linked.a, extra)


class TestRelease:
    def test_a_proxy_gone_releases_its_chan_at_the_home(self, linked: Linked) -> None:
        extra: Chan[Any] = Chan(1, process=True)
        linked.requests.send({"x": extra})
        received = linked.proxy.recv(timeout=DUE)
        assert _exported(linked.a, extra)
        del received
        assert _released(linked.a, extra)

    def test_a_proxy_alive_keeps_its_chan_however_often_handed_over(
        self, linked: Linked
    ) -> None:
        """Two handings over to one proxy: dropping one value keeps it, as the
        proxy lives on in the other; the release counts both."""
        extra: Chan[Any] = Chan(1, process=True)
        linked.requests.send({"x": extra})
        linked.requests.send({"x": extra})
        first = linked.proxy.recv(timeout=DUE)
        second = linked.proxy.recv(timeout=DUE)
        del first
        gc.collect()
        linked.proxy.send(None, timeout=DUE)  # a round trip after any release
        assert linked.requests.recv(timeout=0) is None
        assert _exported(linked.a, extra)
        del second
        assert _released(linked.a, extra)

    def test_a_chan_sent_back_home_arrives_after_its_proxy_is_gone(
        self, linked: Linked
    ) -> None:
        """B's reply Chan reaches A as a proxy, and comes back to B in a
        value: A's proxy is collected as soon as A has encoded it, and its
        Release follows the Result, so B still finds the Chan; then B drops
        it, no proxy of it left."""
        reply: Chan[Any] = Chan(1, process=True)
        linked.proxy.send({"reply": reply}, timeout=DUE)  # held at A as a proxy
        back = linked.proxy.recv(timeout=DUE)
        assert back["reply"] is reply
        assert _released(linked.b, reply)


class TestRefused:
    def test_a_local_chan_cannot_cross(self, linked: Linked) -> None:
        with pytest.raises(TypeError, match="process=True"):
            linked.proxy.send({"c": Chan(1)}, timeout=DUE)
        assert len(linked.requests) == 0

    def test_a_proxy_of_another_link_is_not_relayed(self, linked: Linked) -> None:
        near, far = link()
        c, d = Endpoint(MagicMock(), near), Endpoint(MagicMock(), far)
        try:
            other: _ChanProxy[Any] = _ChanProxy(
                d, c.home.register(Chan(1, process=True))
            )
            with pytest.raises(TypeError, match="third process"):
                linked.proxy.send({"p": other}, timeout=DUE)
        finally:
            d.close()
            c.close()
        assert len(linked.requests) == 0

    def test_an_encoding_that_fails_hands_nothing_over(self, linked: Linked) -> None:
        """The Chan registered before the failure is counted back."""
        mine: Chan[Any] = Chan(1, process=True)
        with pytest.raises(TypeError):
            linked.proxy.send({"c": mine, "bad": threading.Lock()}, timeout=DUE)
        assert not _exported(linked.b, mine)

    def test_a_chan_no_longer_at_its_home_fails_its_call(self, linked: Linked) -> None:
        """Its id released: the call carrying it fails, and the next one runs."""
        gone: Chan[Any] = Chan(1, process=True)
        object_id = linked.a.home.register(gone)
        stale: _ChanProxy[Any] = _ChanProxy(linked.b, object_id)
        linked.a.home.release(object_id, 1)
        with pytest.raises(ClosedError):
            linked.proxy.send({"g": stale}, timeout=DUE)
        linked.proxy.send(1, timeout=DUE)
        assert linked.requests.recv(timeout=0) == 1
