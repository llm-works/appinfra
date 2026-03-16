"""Factory for creating channel pairs with consistent configuration."""

from __future__ import annotations

import multiprocessing as mp
import queue
from dataclasses import dataclass
from typing import Any

from ..channel import ProcessChannel, ThreadChannel


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
    """A pair of connected channels.

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
