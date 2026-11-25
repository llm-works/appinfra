# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""pipe(): a channel whose two ends live in two processes."""

from __future__ import annotations

import asyncio
import contextlib
import multiprocessing as mp
import pickle
import threading
from collections.abc import Callable
from multiprocessing import connection
from multiprocessing.connection import Connection
from typing import Any, Generic, TypeVar

from ..stop import _report
from .chan import Chan
from .errors import ClosedError

T = TypeVar("T")


def pipe(capacity: int) -> tuple[PipeSendEnd[Any], PipeRecvEnd[Any]]:
    """A channel from one process to another: ``send, recv = pipe(capacity)``.

    Each end goes to the process that uses it, which open()s it there; any
    number of tasks in that process can then send, or receive. A send waits
    while *capacity* values are buffered in the sending process, as Chan's
    buffer; at most *capacity* + 1 more are on their way, on the pipe or with
    its writer. Values are pickled.

    The ends see each other's process end as a close, at EOF of the pipes
    underneath; EOF comes once every copy of an end is closed. A process that
    hands an end to another release()s its own copy once the other has it,
    and a forked child releases the end it inherited and does not use.

    Raises:
        ValueError: If *capacity* is less than 1: a send cannot wait for a
            receiver in another process, so there is no hand-over without a
            buffer.
    """
    if capacity < 1:
        raise ValueError(f"capacity must be 1 or more, not {capacity}")
    data_r, data_w = mp.Pipe(duplex=False)
    acks_r, acks_w = mp.Pipe(duplex=False)
    return PipeSendEnd(capacity, data_w, acks_r), PipeRecvEnd(capacity, data_r, acks_w)


class PipeEnd:
    """One end of a pipe, either one, not opened yet: picklable, to be
    handed to the process that uses it."""

    def __init__(self, capacity: int, data: Connection, acks: Connection) -> None:
        """The end on the *data* and *acks* connections of a pipe."""
        self._capacity = capacity
        # Popped once, by open() or release()
        self._conns: list[tuple[Connection, Connection]] = [(data, acks)]

    def release(self) -> None:
        """Close this process's copy of the end, leaving the channel open for
        the process that uses it.

        Raises:
            RuntimeError: If the end was opened or released here already.
        """
        for conn in self._claim():
            conn.close()

    def _claim(self) -> tuple[Connection, Connection]:
        """The connections, once: an end is opened or released, not both. A
        list's pop() is atomic, so two threads cannot both get them."""
        try:
            return self._conns.pop()
        except IndexError:
            raise RuntimeError("pipe end already opened or released") from None


class PipeSendEnd(PipeEnd, Generic[T]):
    """The sending end of a pipe."""

    def open(self) -> Sender[T]:
        """Start sending from this process.

        Raises:
            RuntimeError: If the end was opened or released here already.
        """
        return Sender(self._capacity, *self._claim())


class PipeRecvEnd(PipeEnd, Generic[T]):
    """The receiving end of a pipe."""

    def open(self) -> Receiver[T]:
        """Start receiving in this process.

        Raises:
            RuntimeError: If the end was opened or released here already.
        """
        return Receiver(*self._claim())


class Sender(Generic[T]):
    """A pipe's sending end, open in its process. send() and asend() wait for
    room and raise as Chan's; a select sends with ``Send(sender, value)``. The
    value is pickled in the call, so one that cannot be raises there.

    The values wait in a buffer here, as in a Chan's; a writer thread puts
    each on the pipe, once the receiving side has room for it, and a second
    one counts the values received there."""

    def __init__(self, capacity: int, data: Connection, acks: Connection) -> None:
        """Start the threads, on the *data* and *acks* connections."""
        self._chan = Chan[bytes](capacity)  # the values sent, for the writer
        self._room = Chan[None](capacity)  # values the receiving side has room for
        self._done = Chan[None](0)  # closed by the writer as it ends
        for _ in range(capacity):
            self._room.send(None, timeout=0)  # fits; and open() may run on a loop
        self._writer = _start(self._write, data)
        try:
            _start(self._count, acks)
        except BaseException:
            self._shut()  # the writer ends, and closes the data pipe
            raise

    def send(self, value: T, timeout: float | None = None) -> None:
        """Send *value*, waiting up to *timeout* seconds for room. Raises as
        Chan.send(), and as pickle.dumps() for a value it cannot pickle."""
        self._chan.send(pickle.dumps(value), timeout)

    async def asend(self, value: T, timeout: float | None = None) -> None:
        """Send *value*, awaiting up to *timeout* seconds for room. Raises as
        send(), except RuntimeError."""
        await self._chan.asend(pickle.dumps(value), timeout)

    def close(self) -> None:
        """Close the channel: the values sent so far are received first, then
        the receiving side sees it closed. Returns once they are all on the
        pipe, which waits for room on the receiving side for those still
        buffered; except on an event loop's thread: waiting there could block
        the loop for good, its tasks the only receivers. A coroutine awaits
        aclose(). A process that exits before its values are on the pipe may
        lose the last ones."""
        self._chan.close()  # the writer drains the buffer, then ends
        # _get_running_loop(): see chan._check_off_loop()
        on_loop = asyncio._get_running_loop() is not None
        if not on_loop and threading.current_thread() is not self._writer:
            self._writer.join()

    async def aclose(self) -> None:
        """Close the channel, awaiting until the values sent so far are on
        the pipe; the loop runs meanwhile. The wait is a Chan's: cancelled, it
        leaves nothing behind, and it ends with StoppedError as the task's
        token stops."""
        self._chan.close()
        with contextlib.suppress(ClosedError):  # the writer ended
            await self._done.arecv()

    def _shut(self) -> None:
        """Close the channel here and stop the writer at once, dropping the
        values it has not put on the pipe: the receiving side is gone."""
        self._chan.close()
        self._room.close()

    def _write(self, data: Connection) -> None:
        """Writer thread: each value onto the pipe, once there is room. The
        value is taken first, so a close with none left ends it at once."""
        try:
            while True:
                value = self._chan.recv()
                self._room.recv()
                data.send_bytes(value)
        except ClosedError:
            pass  # closed and drained, or shut
        except OSError:
            self._shut()  # the receiving side is gone
        finally:
            data.close()
            self._done.close()

    def _count(self, acks: Connection) -> None:
        """Counter thread: room for one more value for each one received; EOF
        once the receiving side closed or is gone."""
        try:
            while True:
                acks.recv_bytes()
                with contextlib.suppress(ClosedError):
                    self._room.send(None)
        except (EOFError, OSError):
            self._shut()
        finally:
            acks.close()


class Receiver(Chan[T]):
    """A pipe's receiving end, open in its process: a Chan, received from as
    any, that a reader thread sends the pipe's values on. close() here drops
    the values still on their way."""

    __slots__ = ("_wake",)

    def __init__(self, data: Connection, acks: Connection) -> None:
        """Start the reader, on the *data* and *acks* connections."""
        super().__init__(0)  # the reader acks a value once a receiver took it
        wake, wake_w = mp.Pipe(duplex=False)
        # Written and closed under the channel's lock: a close() writing to
        # it never races the reader closing it, and its fd being reused
        self._wake: Connection | None = wake_w
        _start(self._read, data, acks, wake)

    def close(self) -> None:
        """Close the channel, here and for the sending side."""
        if self._closed:
            return
        super().close()
        with self._lock:
            if self._wake is not None:  # else the reader is gone already
                self._wake.send_bytes(b"")

    def _read(self, data: Connection, acks: Connection, wake: Connection) -> None:
        """Reader thread: each value from the pipe to a receiver, then an ack;
        until EOF, or a close here. Its connections close as it ends, which
        the sending side sees as a close."""
        try:
            while wake not in connection.wait([data, wake]):
                self._deliver(data.recv_bytes())
                # OSError: the sending side is gone, and EOF follows its values
                with contextlib.suppress(OSError):
                    acks.send_bytes(b"")
        except (ClosedError, EOFError, OSError):
            pass
        finally:
            self.close()
            with self._lock:
                if self._wake is not None:
                    self._wake.close()
                    self._wake = None
            for conn in (data, acks, wake):
                conn.close()

    def _deliver(self, payload: bytes) -> None:
        """Send the value *payload* pickles to a receiver. One that cannot be
        unpickled here (its class missing, its args not fitting its __init__)
        is skipped and its error reported through threading.excepthook, as one
        no caller can catch: one bad value does not end the channel."""
        try:
            value = pickle.loads(payload)
        except Exception as e:
            _report(e)
            return
        self.send(value)


def _start(target: Callable[..., None], *args: Any) -> threading.Thread:
    """Start *target* on a daemon thread: an idle pipe does not hold up the
    interpreter's exit."""
    thread = threading.Thread(
        target=target, args=args, daemon=True, name=f"chan-pipe{target.__name__}"
    )
    thread.start()
    return thread
