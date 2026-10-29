# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Common types and helpers for channel communication.

This module provides:
- Message: Generic message with id for request/response correlation
- HasId: Protocol for messages with an id attribute
- RedeliveryBuffer: Shared O(1) buffer for out-of-order message redelivery
- validate_response: Shared response validation logic
- send_slice: Wait slice for close-aware sends
- close_queue / close_queue_async: Close an mp.Queue without hanging interpreter exit
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar, runtime_checkable

from ..errors import ChannelResponseError

# Message types used by channel implementations
TRequest = TypeVar("TRequest")
TResponse = TypeVar("TResponse")


@runtime_checkable
class HasId(Protocol):
    """Protocol for messages with an id attribute."""

    id: str


@dataclass
class Message:
    """Generic message with id for request/response correlation.

    Use this as a base for your own message types, or use any object
    with an `id` attribute.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    payload: Any = None
    error: str | None = None
    is_final: bool = True  # For streaming: False until last chunk


def validate_response(message: Any) -> Any:
    """Raise ``ChannelResponseError`` if a response message carries an error field."""
    if hasattr(message, "error") and message.error:
        raise ChannelResponseError(message)
    return message


#: Longest a channel's send() waits on the transport before rechecking close.
SEND_POLL_INTERVAL = 0.1


def send_slice(deadline: float | None) -> float:
    """Seconds for the next transport send attempt, given an optional deadline."""
    if deadline is None:
        return SEND_POLL_INTERVAL
    return max(0.0, min(SEND_POLL_INTERVAL, deadline - time.monotonic()))


#: Longest close() lets an mp.Queue's feeder thread write sent messages to the pipe.
QUEUE_FLUSH_TIMEOUT = 1.0


def _feeder(q: Any) -> threading.Thread | None:
    """The thread that writes put() messages to q's pipe; None before the first put().

    Private CPython attribute: mp.Queue has no public join with a timeout.
    """
    return getattr(q, "_thread", None)


def close_queue(q: Any) -> None:
    """Close an mp.Queue, letting its feeder write sent messages for QUEUE_FLUSH_TIMEOUT.

    The feeder keeps writing after close(), and interpreter exit joins it. With a full
    pipe and no reader it never finishes, so a feeder still running at the deadline
    has its exit join cancelled: the process exits, and what it had not written is lost.
    """
    q.close()
    feeder = _feeder(q)
    if feeder is not None:
        feeder.join(QUEUE_FLUSH_TIMEOUT)
    if feeder is None or feeder.is_alive():
        q.cancel_join_thread()


async def close_queue_async(q: Any) -> None:
    """close_queue() without blocking the event loop while the feeder writes."""
    q.close()
    feeder = _feeder(q)
    deadline = time.monotonic() + QUEUE_FLUSH_TIMEOUT
    while feeder is not None and feeder.is_alive() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    if feeder is None or feeder.is_alive():
        q.cancel_join_thread()


class RedeliveryBuffer:
    """O(1) buffer for out-of-order messages during request/response correlation.

    Messages with an ``id`` attribute are stored in a dict keyed by id for fast
    lookup.  Messages without an id go into a separate unkeyed list.  When the
    buffer reaches ``max_size``, the oldest entry is evicted.

    Used internally by both ``Channel`` and ``AsyncChannel`` — pure data
    structure, no I/O.
    """

    def __init__(self, max_size: int = 4096) -> None:
        self._keyed: dict[str, deque[Any]] = {}
        self._unkeyed: deque[Any] = deque()
        self._size: int = 0
        self._max_size = max_size
        self.drops: int = 0

    @property
    def size(self) -> int:
        """Current number of buffered messages."""
        return self._size

    def check(self, request_id: str) -> Any | None:
        """O(1) lookup for a buffered message matching *request_id*."""
        msgs = self._keyed.get(request_id)
        if msgs:
            self._size -= 1
            msg = msgs.popleft()
            if not msgs:
                del self._keyed[request_id]
            return msg
        return None

    def pop_any(self) -> Any | None:
        """Pop the next buffered message regardless of id (for ``recv()``)."""
        if self._keyed:
            key = next(iter(self._keyed))
            msgs = self._keyed[key]
            self._size -= 1
            msg = msgs.popleft()
            if not msgs:
                del self._keyed[key]
            return msg
        if self._unkeyed:
            self._size -= 1
            return self._unkeyed.popleft()
        return None

    def put(self, message: Any) -> None:
        """Buffer a message, evicting the oldest entry if at capacity."""
        if self._size >= self._max_size:
            self._evict_oldest()
        msg_id = getattr(message, "id", None)
        if msg_id is not None:
            self._keyed.setdefault(msg_id, deque()).append(message)
        else:
            self._unkeyed.append(message)
        self._size += 1

    def _evict_oldest(self) -> None:
        """Evict one entry from the buffer."""
        if self._keyed:
            key = next(iter(self._keyed))
            msgs = self._keyed[key]
            msgs.popleft()
            if not msgs:
                del self._keyed[key]
            self._size -= 1
            self.drops += 1
            return
        if self._unkeyed:
            self._unkeyed.popleft()
            self._size -= 1
            self.drops += 1
