"""Common types for channel communication.

This module provides:
- Message: Generic message with id for request/response correlation
- HasId: Protocol for messages with an id attribute
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar, runtime_checkable

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
