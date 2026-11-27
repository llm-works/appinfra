# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A process Chan as a process other than its home holds it: a proxy whose
every operation is a call to the home, over the link between the two."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, TypeVar, cast

from .chan import Chan, _check_valid

T = TypeVar("T")


class Caller(Protocol):
    """What a proxy needs of this process's end of the link: an Endpoint."""

    def call(
        self, object_id: int, op: str, args: tuple[Any, ...], timeout: float | None
    ) -> Any:
        """Run *op* on the object homed across the link, and wait for it."""

    async def acall(
        self, object_id: int, op: str, args: tuple[Any, ...], timeout: float | None
    ) -> Any:
        """call(), awaited."""

    def post(self, object_id: int, op: str, args: tuple[Any, ...]) -> None:
        """Run *op* on the object homed across the link, without waiting."""


class _ChanProxy(Chan[T]):
    """A process Chan homed in another process: its operations are calls to
    the home, made through *endpoint*, this process's end of the link there.
    The values and the waiters exist once, at the home, so a proxy keeps the
    Chan's semantics: capacity 0, many senders and receivers, close.

    A send's value is encoded here, so a value that cannot cross fails here,
    and the home stores a copy. A timeout is kept at the home: a call that
    timed out took nothing. A stop of the task ends only a wait, as on a
    local Chan, so a stopped task can still drain: a call the home completes
    at once does, one that waits there raises StoppedError. A call left
    before its answer (a cancel, an interrupt) is cancelled at the home, and
    a value it had received is given back, to be received again in its send
    order. A loop task cancelled thus leaves every call through a proxy at
    once: unlike a local Chan's, a proxy's arecv() always awaits the home.
    A link that ends closes every proxy on it: their calls raise ClosedError.

    On an event loop's thread, ``send()``, ``recv()`` and ``len()`` are
    refused, timeout=0 too: each waits for the home's answer on the link.
    Coroutines await ``asend()``/``arecv()``. ``close()`` waits for nothing:
    it is posted to the home, before the calls this process makes after it.
    A select cannot wait on a proxy (TypeError there): its cases are decided
    at the home, and a select completes exactly one of its own."""

    # __weakref__: the link codec keeps one proxy per object while it lives
    __slots__ = ("_endpoint", "_object_id", "__weakref__")

    def __init__(self, endpoint: Caller, object_id: int) -> None:
        """The proxy of the object *object_id* homed across *endpoint*'s
        link. Chan's own state is not made: it lives at the home, and any
        use of it here would fail at once, as a bug."""
        self._process = True
        self._endpoint = endpoint
        self._object_id = object_id

    def send(self, value: T, timeout: float | None = None) -> None:
        """Send *value*, the home waiting up to *timeout* seconds for room.

        Raises:
            ClosedError: If the channel or the link is closed.
            StoppedError: If the task's token is stopped while waiting.
            TimeoutError: If there is no room after *timeout*.
            ValueError: If *timeout* is negative.
            RuntimeError: If called on an event loop's thread.
            TypeError: As pickle.dumps() for a value it cannot pickle.
        """
        _check_off_loop(timeout, "send", "await asend()")
        self._endpoint.call(self._object_id, "send", (value,), timeout)

    def recv(self, timeout: float | None = None) -> T:
        """Receive the next value, the home waiting up to *timeout* seconds
        for one. Raises as send(), except TypeError."""
        _check_off_loop(timeout, "recv", "await arecv()")
        return cast(T, self._endpoint.call(self._object_id, "recv", (), timeout))

    async def asend(self, value: T, timeout: float | None = None) -> None:
        """Send *value*, awaiting up to *timeout* seconds for room. Raises as
        send(), except RuntimeError."""
        _check_valid(timeout)
        await self._endpoint.acall(self._object_id, "send", (value,), timeout)

    async def arecv(self, timeout: float | None = None) -> T:
        """Receive the next value, awaiting up to *timeout* seconds for one.
        Raises as recv(), except RuntimeError."""
        _check_valid(timeout)
        value = await self._endpoint.acall(self._object_id, "recv", (), timeout)
        return cast(T, value)

    def close(self) -> None:
        """Close the channel at its home; idempotent, and waits for nothing.
        A call this process makes after it runs after it."""
        self._endpoint.post(self._object_id, "close", ())

    def __len__(self) -> int:
        """The values waiting at the home, as Chan's len().

        Raises:
            ClosedError: If the link is closed.
            RuntimeError: If called on an event loop's thread.
        """
        _check_off_loop(None, "len", "call it from a thread")
        return int(self._endpoint.call(self._object_id, "len", (), None))

    # Iteration and __reduce__ are Chan's own: they use only recv(), arecv()
    # and _process, which the proxy has

    def __repr__(self) -> str:
        """The object it stands for, at its home."""
        return f"<Chan proxy of object {self._object_id}>"


def _check_off_loop(timeout: float | None, call: str, instead: str) -> None:
    """Refuse a negative *timeout*, and a blocking *call* on an event loop's
    thread, whatever the timeout: through a proxy even timeout=0 waits, for
    the home's answer on the link. _get_running_loop() as in chan.py."""
    _check_valid(timeout)
    if asyncio._get_running_loop() is not None:
        raise RuntimeError(
            f"{call}() on a proxy waits for the Chan's home and would block "
            f"the event loop; {instead}"
        )
