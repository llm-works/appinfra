# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""One process's end of a link, open: the objects it homes for the other
side, and the calls it makes on objects homed there.

One reader thread takes every frame from the other side: a Result goes to
the caller waiting for it, the rest to the home. This side's frames (calls,
and the cancels, returns and releases of its proxies) go through one outbox
that never blocks, in the order posted, and one pump thread puts them on the
link: a caller is never held by the link, on a thread or on the loop, and a
frame posted after another by one thread never overtakes it. Each caller
encodes its own payload, so a value that cannot cross fails there.

A caller that leaves before its Result (a stop, a cancel) posts a Cancel;
a Result that still comes, with a value received, goes back to the home as
a Return, to be received again in its send order: no value is lost."""

from __future__ import annotations

import contextlib
import itertools
import threading
from typing import Any

from ...log import Logger
from .chan import Chan
from .errors import ClosedError
from .home import Home
from .link import Call, Cancel, Codec, Frame, LinkEnd, Push, Result, Return, describe


class _Pending:
    """A call waiting for its Result: where it goes, and what to do with a
    value if its caller left."""

    __slots__ = ("object_id", "op", "reply", "abandoned")

    def __init__(self, object_id: int, op: str) -> None:
        """A call of *op* on *object_id*, its Result to be delivered on its
        own reply Chan."""
        self.object_id = object_id
        self.op = op
        self.reply: Chan[Result] = Chan(1)  # one Result: its send never waits
        self.abandoned = False


class Endpoint:
    """This process's end of one link: the Home of the objects it hands
    across, and the calls on objects homed on the other side. Made per link
    and process, from the end of the link this process uses."""

    def __init__(self, lg: Logger, end: LinkEnd) -> None:
        """Open *end* and start the reader and the pump."""
        self._link = end.open()
        self._codec = Codec()
        self.home = Home(lg, self._link, self._codec)
        # Guards _pending and _closed; held only for table changes
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending: dict[int, _Pending] = {}
        self._closed = False
        self._outbox: Chan[Frame] = Chan(None)  # never blocks a caller
        for target, name in ((self._read, "link-read"), (self._pump, "link-pump")):
            threading.Thread(target=target, name=name, daemon=True).start()

    def call(
        self, object_id: int, op: str, args: tuple[Any, ...], timeout: float | None
    ) -> Any:
        """Run *op* with *args* on the object *object_id* homed on the other
        side, and return its value, waiting for its Result; the *timeout* is
        kept at the home. A call left with an exception (a stop) is
        abandoned, its value given back.

        Raises:
            ClosedError: If the link is closed, or the call raised it there.
            Exception: As *op* raised it at the home, and as the codec does
                for arguments that cannot be encoded or a value that cannot
                be decoded here.
        """
        call_id, pending = self._start(object_id, op, args, timeout)
        try:
            result = pending.reply.recv()
        except BaseException:
            self._abandon(call_id, pending)
            raise
        return self._outcome(result)

    async def acall(
        self, object_id: int, op: str, args: tuple[Any, ...], timeout: float | None
    ) -> Any:
        """call(), awaited on the loop; a cancelled call is abandoned."""
        call_id, pending = self._start(object_id, op, args, timeout)
        try:
            result = await pending.reply.arecv()
        except BaseException:
            self._abandon(call_id, pending)
            raise
        return self._outcome(result)

    def close(self) -> None:
        """End this side of the link: the waiting calls raise ClosedError,
        the home drops its objects; idempotent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pending = list(self._pending.values())
            self._pending.clear()
        for call in pending:
            call.reply.close()
        self.home.close()
        self._outbox.close()
        self._link.close()

    def _start(
        self, object_id: int, op: str, args: tuple[Any, ...], timeout: float | None
    ) -> tuple[int, _Pending]:
        """Post the Call; its id, and the pending call its Result goes to.

        Raises:
            ClosedError: If the link is closed.
        """
        data = self._codec.encode(args)  # here: what cannot cross fails here
        pending = _Pending(object_id, op)
        with self._lock:
            if self._closed:
                raise ClosedError("link closed")
            call_id = next(self._ids)
            self._pending[call_id] = pending
        self._post(Call(call_id, object_id, op, data, timeout))
        return call_id, pending

    def _abandon(self, call_id: int, pending: _Pending) -> None:
        """The caller of *call_id* left: cancel the call if its Result has
        not come, else give back the value the Result holds."""
        with self._lock:
            waiting = self._pending.get(call_id) is pending
            if waiting:
                pending.abandoned = True
        if waiting:
            self._post(Cancel(call_id))
            return
        # Delivered before the caller left, or given back by recv() as it left
        with contextlib.suppress(ClosedError, TimeoutError):
            self._give_back(pending, pending.reply.recv(timeout=0))

    def _outcome(self, result: Result) -> Any:
        """The value of *result*, decoded here.

        Raises:
            Exception: The error the call raised at the home, or as the codec
                does for a value that cannot be decoded.
            RuntimeError: If the error raised at the home cannot be decoded
                here (its class missing, its args not fitting its __init__).
        """
        if result.error is not None:
            try:
                error = self._codec.decode(result.error)
            except Exception as e:
                raise RuntimeError(
                    f"error at the home cannot be decoded here: {describe(e)}"
                ) from e
            raise error
        return self._codec.decode(result.value)

    def _settle(self, result: Result) -> None:
        """Reader: hand *result* to its caller; give back its value if the
        caller left. Under the lock, so an abandon sees it delivered or not."""
        with self._lock:
            pending = self._pending.pop(result.call_id, None)
            if pending is None:
                return
            if not pending.abandoned:
                pending.reply.send(result, timeout=0)
                return
        self._give_back(pending, result)

    def _give_back(self, pending: _Pending, result: Result) -> None:
        """Return the value *result* received for a caller that left, to be
        received again at the home in its send order."""
        if pending.op == "recv" and result.error is None and not result.cancelled:
            self._post(Return(pending.object_id, result.value, result.seq))

    def _post(self, frame: Frame) -> None:
        """Queue *frame* for the pump; never waits. Closed, the link has
        ended, and the waiting calls with it."""
        with contextlib.suppress(ClosedError):
            self._outbox.send(frame)

    def _read(self) -> None:
        """Reader thread: each frame from the other side to its caller or the
        home, until the link closes; then this side closes."""
        try:
            for frame in self._link:
                if isinstance(frame, Result):
                    self._settle(frame)
                elif not isinstance(frame, Push):
                    self.home.handle(frame)
                del frame  # not kept, with its payload, until the next one
        finally:
            self.close()

    def _pump(self) -> None:
        """Pump thread: each frame from the outbox onto the link, until the
        outbox closes or the link does."""
        with contextlib.suppress(ClosedError):
            for frame in self._outbox:
                self._link.send(frame)
