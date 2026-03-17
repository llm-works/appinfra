"""Bidirectional channel abstraction for service communication.

Provides both sync and async APIs for request/response patterns between
services and their runners, or between parent and child processes.

Sync channels (Channel, ThreadChannel, ProcessChannel):
    Use blocking calls, suitable for threaded code.

Async channels (AsyncChannel, AsyncThreadChannel, AsyncProcessChannel):
    Use async/await, suitable for asyncio code.

Use ChannelFactory to create channel pairs:
    from appinfra.service import ChannelFactory

    factory = ChannelFactory()
    pair = factory.create_thread_pair()
    pair.parent.send(Message(payload="hello"))
"""

from .async_ import AsyncChannel, AsyncProcessChannel, AsyncThreadChannel
from .base import HasId, Message
from .sync import Channel, ProcessChannel, ThreadChannel

__all__ = [
    # Base types
    "Message",
    "HasId",
    # Sync channels
    "Channel",
    "ThreadChannel",
    "ProcessChannel",
    # Async channels
    "AsyncChannel",
    "AsyncThreadChannel",
    "AsyncProcessChannel",
]
