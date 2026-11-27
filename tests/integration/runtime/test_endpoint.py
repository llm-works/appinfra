# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Two endpoints of one link, in one process: calls from one on a Chan homed
at the other, as a proxy makes them."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Chan
from appinfra.runtime.chan import ClosedError
from appinfra.runtime.chan.endpoint import Endpoint
from appinfra.runtime.chan.link import link

# Seconds a call expected to end now may take: the failure path, not a wait
DUE = 5.0


@dataclass
class Pair:
    """The home's endpoint, with a Chan registered there, and the caller's."""

    home: Endpoint
    caller: Endpoint
    chan: Chan[Any]
    object_id: int
    lg: MagicMock  # the home's


@pytest.fixture
def pair() -> Iterator[Pair]:
    near, far = link()
    lg = MagicMock()
    home, caller = Endpoint(lg, near), Endpoint(MagicMock(), far)
    chan: Chan[Any] = Chan(1)
    yield Pair(home, caller, chan, home.home.register(chan), lg)
    caller.close()
    home.close()


class TestCall:
    def test_a_send_and_a_recv_reach_the_home_chan(self, pair: Pair) -> None:
        pair.caller.call(pair.object_id, "send", ({"x": [1]},), DUE)
        assert pair.chan.recv(timeout=0) == {"x": [1]}
        pair.chan.send(8)
        assert pair.caller.call(pair.object_id, "recv", (), DUE) == 8

    def test_an_error_at_the_home_is_raised_by_the_caller(self, pair: Pair) -> None:
        with pytest.raises(TimeoutError):
            pair.caller.call(pair.object_id, "recv", (), 0)

    def test_arguments_that_cannot_be_encoded_fail_at_the_caller(
        self, pair: Pair
    ) -> None:
        with pytest.raises(TypeError):
            pair.caller.call(pair.object_id, "send", (threading.Lock(),), DUE)
        assert pair.caller.call(pair.object_id, "len", (), DUE) == 0

    def test_a_call_awaited_on_the_loop(self, pair: Pair) -> None:
        async def main() -> Any:
            await pair.caller.acall(pair.object_id, "send", (7,), DUE)
            return await pair.caller.acall(pair.object_id, "recv", (), DUE)

        assert asyncio.run(main()) == 7

    def test_a_cancelled_call_loses_no_value(self, pair: Pair) -> None:
        """Cancelled while parked, with a value handed to it or not: the
        value ends in the Chan, given back if its Result came."""

        async def main() -> None:
            waiting = asyncio.create_task(
                pair.caller.acall(pair.object_id, "recv", (), None)
            )
            await asyncio.sleep(0)  # the task posts its call
            await pair.caller.acall(pair.object_id, "len", (), DUE)  # parked now
            # Handed to the parked call at once (timeout=0: on the loop's
            # thread); its Result on its way
            pair.chan.send(7, timeout=0)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting

        asyncio.run(main())
        assert pair.chan.recv(timeout=DUE) == 7

    def test_a_given_back_value_that_cannot_be_decoded_fails_alone(
        self, pair: Pair
    ) -> None:
        """Encoded at the home, the value cannot be rebuilt there: dropped,
        while the link and the calls after it go on."""

        async def main() -> None:
            waiting = asyncio.create_task(
                pair.caller.acall(pair.object_id, "recv", (), None)
            )
            await asyncio.sleep(0)  # the task posts its call
            await pair.caller.acall(pair.object_id, "len", (), DUE)  # parked now
            pair.chan.send(_Undecodable(), timeout=0)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting

        _rebuilding.clear()
        asyncio.run(main())
        # The Return is posted by whichever thread saw the Result last: wait
        # for its decoding; a call posted after it is read after it
        assert _rebuilding.wait(DUE)
        assert pair.caller.call(pair.object_id, "len", (), DUE) == 0
        extra = pair.lg.warning.call_args.kwargs["extra"]
        assert extra["object_id"] == pair.object_id
        assert isinstance(extra["exception"], ValueError)


_rebuilding = threading.Event()


def _rebuild() -> Any:
    """Decoding an _Undecodable: signals, then fails."""
    _rebuilding.set()
    raise ValueError("cannot be rebuilt")


class _Undecodable:
    """Encodes, but its decoding raises."""

    def __reduce__(self) -> tuple[Any, ...]:
        return (_rebuild, ())


class TestClose:
    def test_a_call_waiting_when_the_link_ends_raises_closed(self, pair: Pair) -> None:
        raised: list[BaseException] = []

        def wait() -> None:
            try:
                pair.caller.call(pair.object_id, "recv", (), None)
            except BaseException as e:
                raised.append(e)

        waiter = threading.Thread(target=wait)
        waiter.start()
        pair.home.close()  # the other side's end: the caller's reader sees EOF
        waiter.join(DUE)
        assert not waiter.is_alive()
        assert isinstance(raised[0], ClosedError)

    def test_a_call_after_the_close_raises_closed(self, pair: Pair) -> None:
        pair.caller.close()
        with pytest.raises(ClosedError):
            pair.caller.call(pair.object_id, "len", (), DUE)
