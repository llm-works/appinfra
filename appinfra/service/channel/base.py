"""Common types and helpers for channel communication.

This module provides:
- Message: Generic message with id for request/response correlation
- HasId: Protocol for messages with an id attribute
- RedeliveryBuffer: Shared O(1) buffer for out-of-order message redelivery
- validate_response: Shared response validation logic
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar, runtime_checkable

from ..errors import ChannelError

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
    """Raise ``ChannelError`` if a response message carries an error field."""
    if hasattr(message, "error") and message.error:
        raise ChannelError(f"Request failed: {message.error}")
    return message


class RedeliveryBuffer:
    """O(1) buffer for out-of-order messages during request/response correlation.

    Messages with an ``id`` attribute are stored in a dict keyed by id for fast
    lookup.  Messages without an id go into a separate unkeyed list.  When the
    buffer reaches ``max_size``, the oldest entry is evicted.

    Used internally by both ``Channel`` and ``AsyncChannel`` — pure data
    structure, no I/O.
    """

    def __init__(self, max_size: int = 4096) -> None:
        self._keyed: dict[str, list[Any]] = {}
        self._unkeyed: list[Any] = []
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
            msg = msgs.pop(0)
            if not msgs:
                del self._keyed[request_id]
            return msg
        return None

    def pop_any(self) -> Any | None:
        """Pop the next buffered message regardless of id (for ``recv()``)."""
        for key, msgs in self._keyed.items():
            if msgs:
                self._size -= 1
                msg = msgs.pop(0)
                if not msgs:
                    del self._keyed[key]
                return msg
        if self._unkeyed:
            self._size -= 1
            return self._unkeyed.pop(0)
        return None

    def put(self, message: Any) -> None:
        """Buffer a message, evicting the oldest entry if at capacity."""
        if self._size >= self._max_size:
            self._evict_oldest()
        msg_id = getattr(message, "id", None)
        if msg_id is not None:
            self._keyed.setdefault(msg_id, []).append(message)
        else:
            self._unkeyed.append(message)
        self._size += 1

    def _evict_oldest(self) -> None:
        """Evict one entry from the buffer."""
        for key, msgs in self._keyed.items():
            if msgs:
                msgs.pop(0)
                if not msgs:
                    del self._keyed[key]
                self._size -= 1
                self.drops += 1
                return
        if self._unkeyed:
            self._unkeyed.pop(0)
            self._size -= 1
            self.drops += 1
