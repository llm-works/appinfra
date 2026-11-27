# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A proxy of a process Chan: two endpoints of one link in one process, the
Chan homed at one, its proxy at the other."""

from __future__ import annotations

import asyncio
import pickle
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Chan
from appinfra.runtime.chan import ClosedError, Recv, Send
from appinfra.runtime.chan.endpoint import Endpoint
from appinfra.runtime.chan.link import link
from appinfra.runtime.chan.proxy import _ChanProxy

# Seconds a call expected to end now may take: the failure path, not a wait
DUE = 5.0


@dataclass
class Homed:
    """A Chan at the home's endpoint, and its proxy at the caller's."""

    home: Endpoint
    caller: Endpoint
    chan: Chan[Any]
    proxy: _ChanProxy[Any]


@pytest.fixture
def homed() -> Iterator[Callable[[int | None], Homed]]:
    """Makes a Chan of the given capacity at a home, with its proxy."""
    made: list[Homed] = []

    def make(capacity: int | None) -> Homed:
        near, far = link()
        home, caller = Endpoint(MagicMock(), near), Endpoint(MagicMock(), far)
        chan: Chan[Any] = Chan(capacity, process=True)
        proxy: _ChanProxy[Any] = _ChanProxy(caller, home.home.register(chan))
        made.append(Homed(home, caller, chan, proxy))
        return made[-1]

    yield make
    for each in made:
        each.caller.close()
        each.home.close()


def _in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, list[Any]]:
    """Run *fn* on a thread; its result, or the exception it raised, in the list."""
    out: list[Any] = []

    def run() -> None:
        try:
            out.append(fn())
        except BaseException as e:
            out.append(e)

    thread = threading.Thread(target=run)
    thread.start()
    return thread, out


class TestThread:
    def test_a_send_reaches_the_home_and_a_recv_takes_from_it(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(1)
        h.proxy.send({"x": [1]}, timeout=DUE)
        assert h.chan.recv(timeout=0) == {"x": [1]}
        h.chan.send(8)
        assert h.proxy.recv(timeout=DUE) == 8

    def test_the_home_stores_a_copy_made_at_the_sender(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(1)
        value = [1]
        h.proxy.send(value, timeout=DUE)
        value.append(2)
        assert h.chan.recv(timeout=0) == [1]

    def test_a_value_that_cannot_cross_fails_at_the_sender(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(1)
        with pytest.raises(TypeError):
            h.proxy.send(threading.Lock(), timeout=DUE)
        assert len(h.chan) == 0

    def test_a_timeout_is_kept_at_the_home(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(1)
        with pytest.raises(TimeoutError):
            h.proxy.recv(timeout=0)
        h.proxy.send(1, timeout=DUE)
        with pytest.raises(TimeoutError):
            h.proxy.send(2, timeout=0)
        assert h.chan.recv(timeout=0) == 1
        assert len(h.chan) == 0  # the send that timed out stored nothing

    def test_with_no_buffer_a_send_waits_for_a_receiver(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(0)
        sender, sent = _in_thread(lambda: h.proxy.send(5, timeout=DUE))
        assert h.chan.recv(timeout=DUE) == 5
        sender.join(DUE)
        assert sent == [None]

    def test_with_no_buffer_a_recv_waits_for_a_sender(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(0)
        receiver, received = _in_thread(lambda: h.proxy.recv(timeout=DUE))
        h.chan.send(6, timeout=DUE)
        receiver.join(DUE)
        assert received == [6]

    def test_len_is_the_values_waiting_at_the_home(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(2)
        h.chan.send(1)
        h.chan.send(2)
        assert len(h.proxy) == 2

    def test_iteration_ends_once_closed_and_drained(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(2)
        h.chan.send(1)
        h.chan.send(2)
        h.chan.close()
        assert list(h.proxy) == [1, 2]


class TestClose:
    def test_a_close_through_the_proxy_closes_the_chan_at_its_home(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(1)
        h.proxy.close()
        with pytest.raises(ClosedError):  # made after the close: runs after it
            h.proxy.send(1, timeout=DUE)
        with pytest.raises(ClosedError):
            h.chan.send(1)

    def test_a_close_at_the_home_ends_a_waiting_recv(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(1)
        receiver, received = _in_thread(lambda: h.proxy.recv(timeout=None))
        h.chan.close()  # before the recv or after: closed and drained either way
        receiver.join(DUE)
        assert isinstance(received[0], ClosedError)

    def test_the_link_ending_closes_the_proxy(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(1)
        h.home.close()
        with pytest.raises(ClosedError):
            h.proxy.recv(timeout=DUE)
        h.proxy.close()  # idempotent, as a Chan's: nothing to raise


class TestLoop:
    def test_asend_and_arecv(self, homed: Callable[[int | None], Homed]) -> None:
        h = homed(1)

        async def main() -> Any:
            await h.proxy.asend("a", timeout=DUE)
            assert h.chan.recv(timeout=0) == "a"
            h.chan.send("b", timeout=0)  # the home's own Chan, on the loop's thread
            return await h.proxy.arecv(timeout=DUE)

        assert asyncio.run(main()) == "b"

    def test_async_iteration_ends_once_closed_and_drained(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(2)
        h.chan.send(1)
        h.chan.send(2)
        h.chan.close()

        async def main() -> list[Any]:
            return [value async for value in h.proxy]

        assert asyncio.run(main()) == [1, 2]

    def test_a_sync_call_is_refused_on_the_loop_even_without_waiting(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        """timeout=0 too: each waits for the home's answer on the link."""
        h = homed(1)
        h.chan.send(1)

        async def main() -> None:
            with pytest.raises(RuntimeError, match="await arecv"):
                h.proxy.recv(timeout=0)
            with pytest.raises(RuntimeError, match="await asend"):
                h.proxy.send(2, timeout=0)
            with pytest.raises(RuntimeError, match="thread"):
                len(h.proxy)

        asyncio.run(main())
        assert h.chan.recv(timeout=0) == 1
        assert len(h.chan) == 0

    def test_a_close_is_allowed_on_the_loop(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(1)

        async def main() -> None:
            h.proxy.close()
            with pytest.raises(ClosedError):
                await h.proxy.arecv(timeout=DUE)

        asyncio.run(main())


class TestRefused:
    def test_select_cannot_wait_on_a_proxy(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(1)
        with pytest.raises(TypeError, match="select"):
            Recv(h.proxy)
        with pytest.raises(TypeError, match="select"):
            Send(h.proxy, 1)

    def test_a_proxy_is_not_pickled(self, homed: Callable[[int | None], Homed]) -> None:
        h = homed(1)
        with pytest.raises(TypeError, match="over a link"):
            pickle.dumps(h.proxy)

    def test_a_negative_timeout_is_refused_before_the_call(
        self, homed: Callable[[int | None], Homed]
    ) -> None:
        h = homed(1)
        with pytest.raises(ValueError):
            h.proxy.send(1, timeout=-1)
        with pytest.raises(ValueError):
            h.proxy.recv(timeout=-1)
        with pytest.raises(ValueError):
            asyncio.run(h.proxy.arecv(timeout=-1))
        assert len(h.chan) == 0
