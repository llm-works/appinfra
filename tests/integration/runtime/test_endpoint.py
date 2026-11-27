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
    caller_lg: MagicMock


@pytest.fixture
def pair() -> Iterator[Pair]:
    near, far = link()
    caller_lg = MagicMock()
    home, caller = Endpoint(MagicMock(), near), Endpoint(caller_lg, far)
    chan: Chan[Any] = Chan(1)
    yield Pair(home, caller, chan, home.home.register(chan), caller_lg)
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

    def test_an_error_that_cannot_be_rebuilt_here_still_ends_the_call(
        self, pair: Pair
    ) -> None:
        """Raised at the home by the decoding of the arguments, the error
        cannot be rebuilt at the caller: the call still ends, with an error
        naming it, and is not left waiting for a Result that never comes."""

        async def main() -> Any:
            call = pair.caller.acall(pair.object_id, "send", (_RaisesBad(),), DUE)
            return await asyncio.wait_for(call, DUE)

        with pytest.raises(RuntimeError, match="cannot be decoded") as raised:
            asyncio.run(main())
        assert isinstance(raised.value.__cause__, TypeError)  # _BadError's rebuild

    def test_an_error_whose_decoding_fails_unprintably_still_ends_the_call(
        self, pair: Pair
    ) -> None:
        """The failure to rebuild the error cannot be printed: the call ends
        with the RuntimeError, naming that failure by its type."""
        with pytest.raises(
            RuntimeError, match="cannot be decoded here: _UnprintableError$"
        ):
            pair.caller.call(pair.object_id, "send", (_RaisesRebuildsBadly(),), DUE)

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

    def test_a_received_value_that_cannot_be_decoded_fails_alone(
        self, pair: Pair
    ) -> None:
        """Received for a caller that left, the value cannot be rebuilt on
        the reader: dropped and logged, while the link and the calls after it
        go on."""

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
        # Decoded on the caller's reader: a Result read after it, settled after
        assert _rebuilding.wait(DUE)
        assert pair.caller.call(pair.object_id, "len", (), DUE) == 0
        extra = pair.caller_lg.warning.call_args.kwargs["extra"]
        assert extra["object_id"] == pair.object_id
        assert isinstance(extra["exception"], ValueError)


class _BadError(Exception):
    """An error pickle can write but not rebuild: its args lack *code*."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def _raise_bad() -> Any:
    """Decoding a _RaisesBad: raises a _BadError."""
    raise _BadError("bad payload", 7)


class _RaisesBad:
    """Encodes, but its decoding raises a _BadError."""

    def __reduce__(self) -> tuple[Any, ...]:
        return (_raise_bad, ())


class _UnprintableError(Exception):
    """An error whose str() raises."""

    def __str__(self) -> str:
        raise ValueError("cannot be printed")


def _raise_unprintable() -> Any:
    """Decoding a _RebuildsBadlyError: raises an _UnprintableError."""
    raise _UnprintableError()


class _RebuildsBadlyError(Exception):
    """An error that crosses, but whose decoding raises an _UnprintableError."""

    def __reduce__(self) -> tuple[Any, ...]:
        return (_raise_unprintable, ())


def _raise_rebuilds_badly() -> Any:
    """Decoding a _RaisesRebuildsBadly: raises a _RebuildsBadlyError."""
    raise _RebuildsBadlyError()


class _RaisesRebuildsBadly:
    """Encodes, but its decoding raises a _RebuildsBadlyError."""

    def __reduce__(self) -> tuple[Any, ...]:
        return (_raise_rebuilds_badly, ())


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
