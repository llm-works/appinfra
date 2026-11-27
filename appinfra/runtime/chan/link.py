# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A link: the duplex channel of frames between two processes that the
runtime makes for each run of a process task. Objects a process hands across
it (a Chan made with process=True) stay in that process, their home; the
other side holds proxies, whose operations reach the home as calls and come
back as results. The home pushes to proxies that keep a copy.

Frames:
    Call     proxy -> home   an operation on an object, with its timeout
    Result   home -> proxy   how a call ended: a value, an error, or cancelled
    Cancel   proxy -> home   the caller gave up: the home answers with the
                             result already decided, or cancelled, never both
    Return   proxy -> home   a value received for a caller that left, given
                             back to be received again in its send order
    Push     home -> proxy   the latest version of an object a proxy copies
    Release  proxy -> home   a proxy is gone, with the times its object was
                             handed to it: dropped there once every handing
                             over is released

A frame's payload (Call.args, Result.value and Result.error, Return.value,
Push.value) crosses as bytes, encoded by the Codec of the side that sends
it, and decoded by the side that uses it. Only the payload: a payload that
cannot be decoded fails its own call, while the frame itself, with the call
it answers, still arrives. Every other field is a plain int, str, float or
bool, which any side can rebuild: a frame's own pickling never fails at the
receiver, where the link would have to drop it, leaving its caller waiting.

Internal: callers use the objects, never the link."""

from __future__ import annotations

import pickle
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any, Self

from .pipe import PipeRecvEnd, PipeSendEnd, Receiver, Sender, pipe

# Frames in transit in either direction, per side: past this, a writer thread
# waits for the other side to read. A transport size, not a semantic one: the
# readers on both sides never wait (a call parks at its home, a result goes to
# its waiter), so this bounds no Chan's values; its own capacity does, as a
# send that has to wait parks at the home. 64 lets a burst of calls from one
# process be in flight without their writer waiting on room
CAPACITY = 64


@dataclass(frozen=True, slots=True)
class Call:
    """An operation *op* on the object *object_id*, homed on the other side,
    with *args*, the encoded tuple of its arguments. *timeout*, relative,
    becomes a deadline as the home receives the call: the wait is kept
    there, so a call that timed out took nothing."""

    call_id: int
    object_id: int
    op: str
    args: bytes
    timeout: float | None


@dataclass(frozen=True, slots=True)
class Result:
    """How the call *call_id* ended: its *value*, the *error* it raised, or
    *cancelled* after a Cancel came before any outcome; value and error are
    encoded once on the link. A value received carries its *seq*, its number
    in the send order, for a Return."""

    call_id: int
    value: Any = None
    error: Any = None  # an exception at the home; its bytes on the link
    cancelled: bool = False
    seq: int = 0


@dataclass(frozen=True, slots=True)
class Return:
    """*value*, encoded, number *seq* in the send order of the object
    *object_id*, received for a caller that left: received again in its
    place. Encoded anew by the side giving it back, which decoded it, its
    Chans with it, as it does every Result."""

    object_id: int
    value: bytes
    seq: int


@dataclass(frozen=True, slots=True)
class Cancel:
    """The caller of *call_id* gave up waiting."""

    call_id: int


@dataclass(frozen=True, slots=True)
class Push:
    """The latest *value*, encoded, of the object *object_id*, its
    *version*-th."""

    object_id: int
    version: int
    value: bytes


@dataclass(frozen=True, slots=True)
class Release:
    """The proxy of *object_id* on the sending side is gone, the object
    handed to it *count* times."""

    object_id: int
    count: int


Frame = Call | Result | Cancel | Return | Push | Release


class Codec:
    """Encodes the payloads of frames, and decodes them: plain pickle here,
    which refuses any Chan in a payload. An endpoint's link codec turns the
    process Chans in a payload into references to their homes."""

    def encode(self, value: Any) -> bytes:
        """*value* as bytes for a frame.

        Raises:
            Exception: As pickle.dumps(), for a value that cannot be encoded.
        """
        return pickle.dumps(value, pickle.HIGHEST_PROTOCOL)

    def decode(self, data: bytes) -> Any:
        """The value *data* encodes.

        Raises:
            Exception: As pickle.loads(), for bytes that cannot be decoded
                here (a class this process cannot import).
        """
        return pickle.loads(data)


def describe(error: BaseException) -> str:
    """*error* as "Type: message", or its type alone when it has no message
    or str() of it raises: its code may be a payload's, run on a side that
    must not fail for it."""
    name = type(error).__name__
    try:
        message = str(error)
    except Exception:
        return name
    return f"{name}: {message}" if message else name


def link() -> tuple[LinkEnd, LinkEnd]:
    """A link between two processes: ``near, far = link()``. Each end goes to
    the process that uses it, which open()s it there; a process that hands
    an end to another release()s its own copy once the other has it."""
    near_out, far_in = pipe(CAPACITY)
    try:
        far_out, near_in = pipe(CAPACITY)
    except BaseException:
        # Released now, not left to the garbage collector: the second pipe
        # failing is most likely the process running out of descriptors
        near_out.release()
        far_in.release()
        raise
    return LinkEnd._of(near_out, near_in), LinkEnd._of(far_out, far_in)


class LinkEnd:
    """One end of a link, not opened yet: picklable, to be handed to the
    process that uses it. Made by link()."""

    _out: PipeSendEnd[Frame]
    _in: PipeRecvEnd[Frame]

    def __init__(self) -> None:
        """Refused: a link end comes from link().

        Raises:
            TypeError: Always.
        """
        raise TypeError("a link end comes from link()")

    @classmethod
    def _of(cls, out: PipeSendEnd[Frame], in_: PipeRecvEnd[Frame]) -> Self:
        """The end sending on *out* and receiving on *in_*; for link()."""
        end = object.__new__(cls)
        end._out, end._in = out, in_
        return end

    def open(self) -> Link:
        """Start using the link from this process.

        Raises:
            RuntimeError: If the end was opened or released here already.
        """
        sender = self._out.open()
        try:
            receiver = self._in.open()
        except BaseException:
            sender.close()
            raise
        return Link._of(sender, receiver)

    def release(self) -> None:
        """Close this process's copy of the end, leaving the link to the
        process that uses it.

        Raises:
            RuntimeError: If the end was opened or released here already.
        """
        try:
            self._out.release()
        finally:
            self._in.release()


class Link:
    """A link, open in its process: frames sent to the other side and
    received from it, sync or async, as a pipe's. The other process ending,
    or closing its end, closes the receiving side here once its frames are
    taken: an iteration over the link ends then. Made by LinkEnd.open()."""

    _sender: Sender[Frame]
    _receiver: Receiver[Frame]

    def __init__(self) -> None:
        """Refused: a Link comes from LinkEnd.open().

        Raises:
            TypeError: Always.
        """
        raise TypeError("a Link comes from LinkEnd.open()")

    @classmethod
    def _of(cls, sender: Sender[Frame], receiver: Receiver[Frame]) -> Self:
        """The link sending with *sender* and receiving with *receiver*."""
        opened = object.__new__(cls)
        opened._sender, opened._receiver = sender, receiver
        return opened

    def send(self, frame: Frame, timeout: float | None = None) -> None:
        """Send *frame* to the other side; as a pipe's Sender.send()."""
        self._sender.send(frame, timeout)

    async def asend(self, frame: Frame, timeout: float | None = None) -> None:
        """Send *frame* to the other side; as a pipe's Sender.asend()."""
        await self._sender.asend(frame, timeout)

    def recv(self, timeout: float | None = None) -> Frame:
        """The next frame from the other side; as a pipe's Receiver.recv()."""
        return self._receiver.recv(timeout)

    async def arecv(self, timeout: float | None = None) -> Frame:
        """The next frame from the other side; as Receiver.arecv()."""
        return await self._receiver.arecv(timeout)

    def __iter__(self) -> Iterator[Frame]:
        """The frames from the other side until the link closes."""
        return iter(self._receiver)

    def __aiter__(self) -> AsyncIterator[Frame]:
        """The frames from the other side until the link closes, awaited."""
        return aiter(self._receiver)

    def close(self) -> None:
        """Close both directions: the frames sent so far still reach the
        other side while it reads, then it sees the link closed; frames on
        their way here are dropped.

        The receiving side closes first: the wait for the frames sent to be
        on the pipe needs the other side to read, and a side closing its own
        receiving end ends that wait for the other. Both closing at once with
        frames unread, neither waits for the other."""
        try:
            self._receiver.close()
        finally:
            self._sender.close()

    async def aclose(self) -> None:
        """Close both directions, awaiting the frames sent so far onto the
        pipe; as close(), on the loop."""
        try:
            self._receiver.close()
        finally:
            await self._sender.aclose()
