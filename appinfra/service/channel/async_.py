"""Asynchronous channel implementations.

This module provides:
- AsyncChannel: Abstract base for async bidirectional channels
- AsyncThreadChannel: Async channel using asyncio.Queue for coroutine communication
- AsyncProcessChannel: Async channel wrapping mp.Queue for cross-process IPC
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import queue
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Generic, TypeVar, cast

from ..errors import ChannelClosedError, ChannelError, ChannelTimeoutError

TRequest = TypeVar("TRequest")
TResponse = TypeVar("TResponse")


class AsyncChannel(ABC, Generic[TRequest, TResponse]):
    """
    Async bidirectional channel for service communication.

    Provides three communication patterns:
    1. Fire-and-forget: send() without waiting for response
    2. Receive: recv() to get next incoming message
    3. Request/response: submit() sends and waits for matching response

    Safe for concurrent use from multiple coroutines.
    """

    @abstractmethod
    async def send(self, message: TRequest) -> None:
        """Send message without waiting for response."""

    @abstractmethod
    async def recv(self, timeout: float | None = None) -> TResponse:
        """Receive next incoming message."""

    @abstractmethod
    async def submit(
        self, request: TRequest, timeout: float | None = None
    ) -> TResponse:
        """Send request and wait for matching response."""

    @abstractmethod
    def submit_stream(
        self, request: TRequest, timeout: float | None = None
    ) -> AsyncIterator[TResponse]:
        """
        Send request and yield streaming response chunks.

        Yields response chunks with matching id until one with is_final=True.
        Each chunk must have an `id` attribute matching the request.
        The final chunk must have `is_final=True`.

        Args:
            request: Request message (must have .id attribute)
            timeout: Timeout for each chunk (None = use default)

        Yields:
            Response chunks until is_final=True

        Raises:
            ChannelTimeoutError: If a chunk is not received within timeout
            ChannelClosedError: If channel is closed
            ValueError: If request has no id attribute
        """

    @abstractmethod
    async def close(self) -> None:
        """Close the channel."""

    @property
    @abstractmethod
    def is_closed(self) -> bool:
        """True if channel has been closed."""


class _BaseAsyncChannel(AsyncChannel[TRequest, TResponse]):
    """Base implementation with common async logic."""

    def __init__(self, response_timeout: float = 30.0) -> None:
        self._response_timeout = response_timeout
        self._closed = False
        self._lock = asyncio.Lock()
        self._redelivery: asyncio.Queue[Any] = asyncio.Queue()

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def _get_from_queue(self, timeout: float | None) -> Any:
        """Get message from inbound queue. Implemented by subclasses."""
        raise NotImplementedError

    async def submit(
        self, request: TRequest, timeout: float | None = None
    ) -> TResponse:
        """Send request and wait for matching response."""
        if self._closed:
            raise ChannelClosedError("Channel is closed")
        if not hasattr(request, "id"):
            raise ValueError("Request must have an 'id' attribute")

        request_id = request.id  # type: ignore[union-attr]
        effective_timeout = timeout if timeout is not None else self._response_timeout

        await self.send(request)
        return await self._poll_for_response(request_id, effective_timeout)

    async def submit_stream(
        self, request: TRequest, timeout: float | None = None
    ) -> AsyncIterator[TResponse]:
        """Send request and yield streaming response chunks."""
        if self._closed:
            raise ChannelClosedError("Channel is closed")
        if not hasattr(request, "id"):
            raise ValueError("Request must have an 'id' attribute")

        request_id = request.id  # type: ignore[union-attr]
        effective_timeout = timeout if timeout is not None else self._response_timeout

        await self.send(request)
        async for chunk in self._poll_for_stream(request_id, effective_timeout):
            yield chunk

    async def _poll_for_stream(
        self, request_id: str, timeout: float
    ) -> AsyncIterator[TResponse]:
        """Poll for streaming response chunks until is_final=True."""
        while True:
            chunk = await self._get_next_chunk(request_id, timeout)
            yield chunk
            if getattr(chunk, "is_final", True):
                return

    async def _get_next_chunk(self, request_id: str, timeout: float) -> TResponse:
        """Wait for next chunk with matching request_id."""
        deadline = time.monotonic() + timeout
        poll_interval = 0.05

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChannelTimeoutError(
                    f"Stream {request_id} timed out waiting for chunk"
                )

            # Check redelivery queue first
            message = await self._check_redelivery(request_id)
            if message is not None:
                return self._validate_response(message)

            message = await self._try_get_message(min(poll_interval, remaining))
            if message is None:
                continue

            if hasattr(message, "id") and message.id == request_id:
                return self._validate_response(message)

            # Not our message - buffer for later
            await self._redelivery.put(message)

    async def _poll_for_response(self, request_id: str, timeout: float) -> TResponse:
        """Poll for a response with the given request_id."""
        deadline = time.monotonic() + timeout
        poll_interval = 0.05

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChannelTimeoutError(
                    f"Request {request_id} timed out after {timeout}s"
                )

            message = await self._check_redelivery(request_id)
            if message is not None:
                return self._validate_response(message)

            message = await self._try_get_message(min(poll_interval, remaining))
            if message is None:
                continue

            if hasattr(message, "id") and message.id == request_id:
                return self._validate_response(message)

            await self._redelivery.put(message)

    async def _try_get_message(self, timeout: float) -> Any | None:
        """Try to get a message, returning None on timeout."""
        try:
            return await self._get_from_queue(timeout)
        except ChannelTimeoutError:
            return None

    def _validate_response(self, message: Any) -> TResponse:
        """Validate response and raise ChannelError if it contains an error."""
        if hasattr(message, "error") and message.error:
            raise ChannelError(f"Request failed: {message.error}")
        return cast(TResponse, message)

    async def _check_redelivery(self, request_id: str) -> Any | None:
        """Check redelivery queue for a matching response."""
        recheck: list[Any] = []
        result = None

        while True:
            try:
                msg = self._redelivery.get_nowait()
                if result is None and hasattr(msg, "id") and msg.id == request_id:
                    result = msg
                else:
                    recheck.append(msg)
            except asyncio.QueueEmpty:
                break

        for msg in recheck:
            await self._redelivery.put(msg)

        return result

    async def close(self) -> None:
        """Close channel."""
        self._closed = True


class AsyncThreadChannel(_BaseAsyncChannel[TRequest, TResponse]):
    """Async channel using asyncio.Queue for coroutine-based communication."""

    def __init__(
        self,
        outbound: asyncio.Queue[TRequest],
        inbound: asyncio.Queue[TResponse],
        response_timeout: float = 30.0,
    ) -> None:
        super().__init__(response_timeout)
        self._outbound = outbound
        self._inbound = inbound

    async def send(self, message: TRequest) -> None:
        if self._closed:
            raise ChannelClosedError("Channel is closed")
        await self._outbound.put(message)

    async def _get_from_queue(self, timeout: float | None) -> Any:
        try:
            return await asyncio.wait_for(self._inbound.get(), timeout=timeout)
        except TimeoutError:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    async def recv(self, timeout: float | None = None) -> TResponse:
        try:
            return cast(TResponse, self._redelivery.get_nowait())
        except asyncio.QueueEmpty:
            pass

        if self._closed:
            try:
                return cast(TResponse, self._inbound.get_nowait())
            except asyncio.QueueEmpty:
                raise ChannelClosedError("Channel is closed")

        return cast(TResponse, await self._get_from_queue(timeout))


class AsyncProcessChannel(_BaseAsyncChannel[TRequest, TResponse]):
    """Async channel wrapping multiprocessing.Queue for cross-process communication."""

    def __init__(
        self,
        outbound: mp.Queue[TRequest],
        inbound: mp.Queue[TResponse],
        response_timeout: float = 30.0,
    ) -> None:
        super().__init__(response_timeout)
        self._outbound = outbound
        self._inbound = inbound

    async def send(self, message: TRequest) -> None:
        if self._closed:
            raise ChannelClosedError("Channel is closed")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._outbound.put, message)

    async def _get_from_queue(self, timeout: float | None) -> Any:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: self._inbound.get(timeout=timeout)
            )
        except queue.Empty:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    async def recv(self, timeout: float | None = None) -> TResponse:
        try:
            return cast(TResponse, self._redelivery.get_nowait())
        except asyncio.QueueEmpty:
            pass

        if self._closed:
            try:
                loop = asyncio.get_running_loop()
                return cast(
                    TResponse,
                    await loop.run_in_executor(None, self._inbound.get_nowait),
                )
            except queue.Empty:
                raise ChannelClosedError("Channel is closed")

        return cast(TResponse, await self._get_from_queue(timeout))

    async def close(self) -> None:
        await super().close()
        try:
            self._outbound.close()
            self._inbound.close()
        except Exception:
            pass
