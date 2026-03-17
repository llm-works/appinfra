"""Queue-based IPC channel using service package infrastructure.

This module provides IPCChannel, a thin wrapper around AsyncProcessChannel
that adds application-specific features:
- max_pending enforcement
- health_status reporting
- Lifecycle methods compatible with FastAPI lifespan
"""

from __future__ import annotations

import multiprocessing as mp
from collections.abc import AsyncIterator
from typing import Any

from ....service.channel import AsyncProcessChannel
from ..config.ipc import IPCConfig


class IPCChannel:
    """
    Bidirectional IPC channel for FastAPI subprocess communication.

    Wraps AsyncProcessChannel to provide:
    - max_pending request limiting
    - Health status reporting for /_health endpoint
    - start_polling/stop_polling lifecycle for FastAPI lifespan compatibility

    Message Protocol:
    - Messages MUST have an `.id` attribute for routing
    - Streaming messages MUST have an `.is_final` attribute
    - Framework is agnostic about message types; users define their own
      Request/Response/StreamChunk dataclasses

    Example usage in FastAPI handler:
        async def inference(request: InferenceRequest, ipc: IPCChannel = Depends(get_ipc)):
            internal = InternalRequest(id=str(uuid4()), data=request.data)
            response = await ipc.submit(internal, timeout=60.0)
            return response.result
    """

    def __init__(
        self,
        request_q: mp.Queue[Any],
        response_q: mp.Queue[Any],
        config: IPCConfig,
    ) -> None:
        """
        Initialize IPC channel.

        Args:
            request_q: Queue for sending requests to main process
            response_q: Queue for receiving responses from main process
            config: IPC configuration
        """
        self._channel: AsyncProcessChannel[Any, Any] = AsyncProcessChannel(
            outbound=request_q,
            inbound=response_q,
            response_timeout=config.response_timeout,
        )
        self._config = config
        self._pending_count = 0
        self._closed = False

    @property
    def pending_count(self) -> int:
        """Number of requests currently awaiting response."""
        return self._pending_count

    @property
    def health_status(self) -> dict[str, Any]:
        """
        Health status for reporting.

        Returns dict with:
        - pending_requests: Current number of pending requests
        - max_pending: Configured maximum
        - is_healthy: True if under capacity
        """
        return {
            "pending_requests": self._pending_count,
            "max_pending": self._config.max_pending,
            "is_healthy": self._pending_count < self._config.max_pending,
        }

    async def submit(
        self,
        request: Any,
        timeout: float | None = None,
    ) -> Any:
        """
        Submit request and wait for response.

        Args:
            request: Request object with `.id` attribute
            timeout: Override default response timeout (seconds)

        Returns:
            Response object from main process

        Raises:
            RuntimeError: If max_pending exceeded
            ChannelTimeoutError: If response not received within timeout
            ValueError: If request has no `.id` attribute
        """
        if self._pending_count >= self._config.max_pending:
            raise RuntimeError(
                f"Max pending requests exceeded ({self._config.max_pending})"
            )

        self._pending_count += 1
        try:
            return await self._channel.submit(request, timeout)
        finally:
            self._pending_count -= 1

    async def submit_stream(
        self,
        request: Any,
        timeout: float | None = None,
    ) -> AsyncIterator[Any]:
        """
        Submit streaming request and yield response chunks.

        Yields chunks until one with is_final=True is received.

        Args:
            request: Request object with `.id` attribute
            timeout: Timeout for each chunk (None = use default)

        Yields:
            Response chunks until is_final=True

        Raises:
            RuntimeError: If max_pending exceeded
            ChannelTimeoutError: If a chunk is not received within timeout
            ValueError: If request has no `.id` attribute
        """
        if self._pending_count >= self._config.max_pending:
            raise RuntimeError(
                f"Max pending requests exceeded ({self._config.max_pending})"
            )

        self._pending_count += 1
        try:
            async for chunk in self._channel.submit_stream(request, timeout):
                yield chunk
        finally:
            self._pending_count -= 1

    async def start_polling(self) -> None:
        """
        Start the channel (FastAPI lifespan compatibility).

        AsyncProcessChannel polls on-demand, so this is a no-op.
        Kept for API compatibility with FastAPI adapter lifespan.
        """
        pass

    async def stop_polling(self) -> None:
        """
        Stop the channel and clean up resources.

        Called during FastAPI shutdown to close underlying queues.
        """
        if not self._closed:
            self._closed = True
            await self._channel.close()
