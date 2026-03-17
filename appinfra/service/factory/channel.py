"""Factory for creating channel pairs with consistent configuration."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import queue
from dataclasses import dataclass
from typing import Any

from ..channel import (
    AsyncProcessChannel,
    AsyncThreadChannel,
    ProcessChannel,
    ThreadChannel,
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

    parent: ThreadChannel[Any, Any] | ProcessChannel[Any, Any]
    child: ThreadChannel[Any, Any] | ProcessChannel[Any, Any]

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

    parent: AsyncThreadChannel[Any, Any] | AsyncProcessChannel[Any, Any]
    child: AsyncThreadChannel[Any, Any] | AsyncProcessChannel[Any, Any]

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

    parent: AsyncProcessChannel[Any, Any]
    child: ProcessChannel[Any, Any]

    async def close(self) -> None:
        """Close both channels."""
        await self.parent.close()
        self.child.close()


class ChannelFactory:
    """
    Factory for creating channel pairs with consistent configuration.

    Centralizes channel creation so configuration (timeouts, queue sizes)
    is consistent across the application.

    Example:
        factory = ChannelFactory(ChannelConfig(response_timeout=60.0))

        # For thread-based communication
        pair = factory.create_thread_pair()
        # pair.parent for caller, pair.child for service

        # For process-based communication
        pair = factory.create_process_pair()
    """

    def __init__(self, config: ChannelConfig | None = None) -> None:
        """
        Initialize factory.

        Args:
            config: Channel configuration (uses defaults if not provided)
        """
        self._config = config or ChannelConfig()

    @property
    def config(self) -> ChannelConfig:
        """Current configuration."""
        return self._config

    def create_thread_pair(self) -> ChannelPair:
        """
        Create a pair of connected ThreadChannels.

        Returns:
            ChannelPair with parent and child ThreadChannels
        """
        if self._config.max_queue_size > 0:
            q1: queue.Queue[Any] = queue.Queue(maxsize=self._config.max_queue_size)
            q2: queue.Queue[Any] = queue.Queue(maxsize=self._config.max_queue_size)
        else:
            q1 = queue.Queue()
            q2 = queue.Queue()

        parent = ThreadChannel(
            outbound=q1,
            inbound=q2,
            response_timeout=self._config.response_timeout,
        )
        child = ThreadChannel(
            outbound=q2,
            inbound=q1,
            response_timeout=self._config.response_timeout,
        )

        return ChannelPair(parent=parent, child=child)

    def create_process_pair(self) -> ChannelPair:
        """
        Create a pair of connected ProcessChannels.

        IMPORTANT: Create this BEFORE spawning the child process.

        Returns:
            ChannelPair with parent and child ProcessChannels
        """
        if self._config.max_queue_size > 0:
            q1: mp.Queue[Any] = mp.Queue(maxsize=self._config.max_queue_size)
            q2: mp.Queue[Any] = mp.Queue(maxsize=self._config.max_queue_size)
        else:
            q1 = mp.Queue()
            q2 = mp.Queue()

        parent = ProcessChannel(
            outbound=q1,
            inbound=q2,
            response_timeout=self._config.response_timeout,
        )
        child = ProcessChannel(
            outbound=q2,
            inbound=q1,
            response_timeout=self._config.response_timeout,
        )

        return ChannelPair(parent=parent, child=child)

    def create_async_thread_pair(self) -> AsyncChannelPair:
        """
        Create a pair of connected AsyncThreadChannels.

        For async communication between coroutines in the same event loop.

        Returns:
            AsyncChannelPair with parent and child AsyncThreadChannels
        """
        if self._config.max_queue_size > 0:
            q1: asyncio.Queue[Any] = asyncio.Queue(maxsize=self._config.max_queue_size)
            q2: asyncio.Queue[Any] = asyncio.Queue(maxsize=self._config.max_queue_size)
        else:
            q1 = asyncio.Queue()
            q2 = asyncio.Queue()

        parent = AsyncThreadChannel(
            outbound=q1,
            inbound=q2,
            response_timeout=self._config.response_timeout,
        )
        child = AsyncThreadChannel(
            outbound=q2,
            inbound=q1,
            response_timeout=self._config.response_timeout,
        )

        return AsyncChannelPair(parent=parent, child=child)

    def create_async_process_pair(self) -> AsyncProcessChannelPair:
        """
        Create channels for async parent <-> sync subprocess communication.

        The parent channel uses async/await, suitable for asyncio code.
        The child channel uses blocking sync calls, suitable for subprocess code.

        IMPORTANT: Create this BEFORE spawning the child process.

        Returns:
            AsyncProcessChannelPair with async parent and sync child channels
        """
        if self._config.max_queue_size > 0:
            q1: mp.Queue[Any] = mp.Queue(maxsize=self._config.max_queue_size)
            q2: mp.Queue[Any] = mp.Queue(maxsize=self._config.max_queue_size)
        else:
            q1 = mp.Queue()
            q2 = mp.Queue()

        parent = AsyncProcessChannel(
            outbound=q1,
            inbound=q2,
            response_timeout=self._config.response_timeout,
        )
        child = ProcessChannel(
            outbound=q2,
            inbound=q1,
            response_timeout=self._config.response_timeout,
        )

        return AsyncProcessChannelPair(parent=parent, child=child)
