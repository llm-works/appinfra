"""Factory for creating channel pairs with consistent configuration."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import queue
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..channel.async_ import (
    AsyncBufferedChannel,
    AsyncChannel,
    AsyncProcessQueueTransport,
    AsyncQueueTransport,
)
from ..channel.sync import (
    BufferedChannel,
    Channel,
    ProcessQueueTransport,
    QueueTransport,
)


@dataclass
class ChannelConfig:
    """Configuration for channel creation.

    Attributes:
        response_timeout: Default timeout for submit() calls (seconds)
        max_queue_size: Maximum queue size (0 = unlimited)
    """

    response_timeout: float = 30.0
    max_queue_size: int = 0


@dataclass
class ChannelPair:
    """A pair of connected sync channels.

    Attributes:
        parent: Channel for the parent/caller side
        child: Channel for the child/service side
    """

    parent: Channel
    child: Channel

    def close(self) -> None:
        """Close both channels."""
        self.parent.close()
        self.child.close()


@dataclass
class AsyncChannelPair:
    """A pair of connected async channels.

    Attributes:
        parent: Async channel for the parent/caller side
        child: Async channel for the child/service side
    """

    parent: AsyncChannel
    child: AsyncChannel

    async def close(self) -> None:
        """Close both channels."""
        await self.parent.close()
        await self.child.close()


@dataclass
class AsyncProcessChannelPair:
    """Channel pair for async parent <-> sync subprocess communication.

    Attributes:
        parent: Async channel for the parent (async/await)
        child: Sync channel for the subprocess (blocking)
    """

    parent: AsyncChannel
    child: Channel

    async def close(self) -> None:
        """Close both channels."""
        await self.parent.close()
        self.child.close()


@runtime_checkable
class ChannelPairFactory(Protocol):
    """Protocol for pluggable transport factories.

    Implement this to provide custom channel pairs (e.g., ZMQ, gRPC)
    instead of the built-in queue-based channels.

    Example::

        class ZMQChannelFactory:
            def create_pair(self) -> ChannelPair:
                parent = Channel(ZMQTransport(ctx, endpoint))
                child = Channel(ZMQTransport(ctx, endpoint))
                return ChannelPair(parent=parent, child=child)

        factory = RunnerFactory(lg, channel_factory=ZMQChannelFactory())
    """

    def create_pair(self) -> ChannelPair:
        """Create a connected channel pair."""
        ...


def _make_queues(queue_cls: type, max_size: int) -> tuple[Any, Any]:
    """Create a pair of queues."""
    if max_size > 0:
        return queue_cls(maxsize=max_size), queue_cls(maxsize=max_size)
    return queue_cls(), queue_cls()


class QueueChannelFactory:
    """
    Factory for creating channel pairs using ``queue.Queue`` transport.

    Suitable for thread-based (in-process) communication.

    Example:
        factory = QueueChannelFactory(ChannelConfig(response_timeout=60.0))
        pair = factory.create_pair()
    """

    def __init__(self, config: ChannelConfig | None = None) -> None:
        self._config = config or ChannelConfig()

    @property
    def config(self) -> ChannelConfig:
        """Current configuration."""
        return self._config

    def create_pair(self) -> ChannelPair:
        """Create a connected channel pair using queue.Queue transport."""
        q1, q2 = _make_queues(queue.Queue, self._config.max_queue_size)
        timeout = self._config.response_timeout

        parent: BufferedChannel[Any, Any] = BufferedChannel(
            QueueTransport(outbound=q1, inbound=q2), timeout
        )
        child: BufferedChannel[Any, Any] = BufferedChannel(
            QueueTransport(outbound=q2, inbound=q1), timeout
        )

        return ChannelPair(parent=parent, child=child)


class ProcessQueueChannelFactory:
    """
    Factory for creating channel pairs using ``multiprocessing.Queue`` transport.

    Suitable for cross-process communication.

    IMPORTANT: Create pairs BEFORE spawning the child process.

    Example:
        factory = ProcessQueueChannelFactory(ChannelConfig(response_timeout=60.0))
        pair = factory.create_pair()
    """

    def __init__(self, config: ChannelConfig | None = None) -> None:
        self._config = config or ChannelConfig()

    @property
    def config(self) -> ChannelConfig:
        """Current configuration."""
        return self._config

    def create_pair(self) -> ChannelPair:
        """Create a connected channel pair using multiprocessing.Queue transport."""
        q1, q2 = _make_queues(mp.Queue, self._config.max_queue_size)
        timeout = self._config.response_timeout

        parent: BufferedChannel[Any, Any] = BufferedChannel(
            ProcessQueueTransport(outbound=q1, inbound=q2), timeout
        )
        child: BufferedChannel[Any, Any] = BufferedChannel(
            ProcessQueueTransport(outbound=q2, inbound=q1), timeout
        )

        return ChannelPair(parent=parent, child=child)


class AsyncQueueChannelFactory:
    """Factory for creating async channel pairs using ``asyncio.Queue`` transport."""

    def __init__(self, config: ChannelConfig | None = None) -> None:
        self._config = config or ChannelConfig()

    def create_pair(self) -> AsyncChannelPair:
        """Create a connected async channel pair."""
        q1, q2 = _make_queues(asyncio.Queue, self._config.max_queue_size)
        timeout = self._config.response_timeout

        parent: AsyncBufferedChannel[Any, Any] = AsyncBufferedChannel(
            AsyncQueueTransport(outbound=q1, inbound=q2), timeout
        )
        child: AsyncBufferedChannel[Any, Any] = AsyncBufferedChannel(
            AsyncQueueTransport(outbound=q2, inbound=q1), timeout
        )

        return AsyncChannelPair(parent=parent, child=child)


class AsyncProcessQueueChannelFactory:
    """Factory for async parent <-> sync subprocess channel pairs."""

    def __init__(self, config: ChannelConfig | None = None) -> None:
        self._config = config or ChannelConfig()

    def create_pair(self) -> AsyncProcessChannelPair:
        """Create an async parent + sync child channel pair."""
        q1, q2 = _make_queues(mp.Queue, self._config.max_queue_size)
        timeout = self._config.response_timeout

        parent: AsyncBufferedChannel[Any, Any] = AsyncBufferedChannel(
            AsyncProcessQueueTransport(outbound=q1, inbound=q2), timeout
        )
        child: BufferedChannel[Any, Any] = BufferedChannel(
            ProcessQueueTransport(outbound=q2, inbound=q1), timeout
        )

        return AsyncProcessChannelPair(parent=parent, child=child)
