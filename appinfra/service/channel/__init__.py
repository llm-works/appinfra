"""Bidirectional channel abstraction for service communication.

Provides both sync and async APIs for request/response patterns between
services and their runners, or between parent and child processes.

Architecture:
- Channel / AsyncChannel: Protocol — implement directly for smart transports
- Transport / AsyncTransport: Protocol — implement for dumb wire transports
- BufferedChannel / AsyncBufferedChannel: Concrete — wraps Transport with
  request/response correlation and redelivery buffering
- Factory classes: Create connected channel pairs

Smart transport (ZMQ, gRPC — handles own correlation):
    class ZMQChannel:
        def send(self, message): ...
        def recv(self, timeout=None): ...
        def submit(self, request, timeout=None): ...
        def close(self): ...
        @property
        def is_closed(self) -> bool: ...

Dumb transport (wrap in BufferedChannel):
    from appinfra.service import BufferedChannel, QueueChannelFactory

    factory = QueueChannelFactory()
    pair = factory.create_pair()
    pair.parent.send(Message(payload="hello"))
"""

from .async_ import (
    AsyncBufferedChannel,
    AsyncChannel,
    AsyncProcessQueueTransport,
    AsyncQueueTransport,
    AsyncTransport,
)
from .base import HasId, Message
from .sync import (
    BufferedChannel,
    Channel,
    ProcessQueueTransport,
    QueueTransport,
    Transport,
)

__all__ = [
    # Base types
    "Message",
    "HasId",
    # Sync protocol + concrete
    "Channel",
    "Transport",
    "BufferedChannel",
    "QueueTransport",
    "ProcessQueueTransport",
    # Async protocol + concrete
    "AsyncChannel",
    "AsyncTransport",
    "AsyncBufferedChannel",
    "AsyncQueueTransport",
    "AsyncProcessQueueTransport",
]
