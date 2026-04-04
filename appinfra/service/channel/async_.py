"""Asynchronous channel implementations.

This module provides:
- AsyncTransport: Protocol for custom async wire transports
- AsyncChannel: Concrete async channel with submit/recv correlation
- AsyncQueueTransport: Transport using asyncio.Queue (coroutines)
- AsyncProcessQueueTransport: Transport wrapping mp.Queue (cross-process)
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import queue
import time
from collections.abc import AsyncIterator
from typing import Any, Generic, Protocol, TypeVar, cast, runtime_checkable

from ..errors import ChannelClosedError, ChannelError, ChannelTimeoutError

TRequest = TypeVar("TRequest")
TResponse = TypeVar("TResponse")


@runtime_checkable
class AsyncTransport(Protocol):
    """
    Async wire-level transport protocol.

    Implement this protocol to plug in a custom async transport. The
    ``AsyncChannel`` class wraps an AsyncTransport and adds request/response
    correlation, streaming, redelivery buffering, and close management.
    """

    async def send(self, message: Any) -> None:
        """Send a message over the wire."""
        ...

    async def recv(self, timeout: float | None = None) -> Any:
        """
        Receive the next message from the wire.

        Args:
            timeout: Maximum seconds to wait.

        Raises:
            ChannelTimeoutError: If no message arrives within timeout.
        """
        ...

    async def close(self) -> None:
        """Release transport resources."""
        ...

    @property
    def is_closed(self) -> bool:
        """True if the transport has been closed."""
        ...


class AsyncChannel(Generic[TRequest, TResponse]):
    """
    Async bidirectional channel for service communication.

    Wraps an ``AsyncTransport`` and adds request/response correlation,
    streaming, redelivery buffering, and close management.

    Four communication patterns:

    1. Fire-and-forget: ``send()`` without waiting for response
    2. Receive: ``recv()`` to get next incoming message
    3. Request/response: ``submit()`` sends and waits for matching response
    4. Streaming: ``submit_stream()`` yields response chunks until ``is_final``

    Args:
        transport: The underlying async wire transport.
        response_timeout: Default timeout for ``submit()`` calls (seconds).
    """

    _MAX_REDELIVERY = 4096

    def __init__(
        self,
        transport: AsyncTransport,
        response_timeout: float = 30.0,
    ) -> None:
        self._transport = transport
        self._response_timeout = response_timeout
        self._closed = False
        self._redelivery: asyncio.Queue[Any] = asyncio.Queue()
        self.redelivery_drops: int = 0

    @property
    def transport(self) -> AsyncTransport:
        """The underlying async wire transport."""
        return self._transport

    @property
    def is_closed(self) -> bool:
        """True if the channel or its transport has been closed."""
        return self._closed or self._transport.is_closed

    async def send(self, message: TRequest) -> None:
        """Send message without waiting for response."""
        if self.is_closed:
            raise ChannelClosedError("Channel is closed")
        await self._transport.send(message)

    async def recv(self, timeout: float | None = None) -> TResponse:
        """
        Receive next incoming message.

        Checks the redelivery buffer first, then polls the transport
        with periodic close checks. When closed, attempts to drain one
        remaining buffered message before raising ``ChannelClosedError``.
        """
        try:
            return cast(TResponse, self._redelivery.get_nowait())
        except asyncio.QueueEmpty:
            pass

        if self.is_closed:
            return await self._drain_or_raise()

        return await self._recv_poll(timeout)

    async def submit(
        self, request: TRequest, timeout: float | None = None
    ) -> TResponse:
        """Send request and wait for matching response."""
        if self.is_closed:
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
        """
        Send request and yield streaming response chunks.

        Yields response chunks with matching id until one with
        ``is_final=True``.
        """
        if self.is_closed:
            raise ChannelClosedError("Channel is closed")
        if not hasattr(request, "id"):
            raise ValueError("Request must have an 'id' attribute")

        request_id = request.id  # type: ignore[union-attr]
        effective_timeout = timeout if timeout is not None else self._response_timeout

        await self.send(request)
        async for chunk in self._poll_for_stream(request_id, effective_timeout):
            yield chunk

    async def close(self) -> None:
        """Close the channel and its transport."""
        self._closed = True
        await self._transport.close()

    # -- internal helpers --------------------------------------------------

    async def _recv_poll(self, timeout: float | None) -> TResponse:
        """Poll transport with periodic close checks."""
        poll_interval = 0.1
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            if self.is_closed:
                return await self._drain_or_raise()

            wait = poll_interval
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ChannelTimeoutError(
                        f"Timeout waiting for message ({timeout}s)"
                    )
                wait = min(poll_interval, remaining)

            try:
                return cast(TResponse, await self._transport.recv(wait))
            except ChannelTimeoutError:
                if deadline is not None and time.monotonic() >= deadline:
                    raise

    async def _drain_or_raise(self) -> TResponse:
        """Try to drain one buffered message from the transport before raising."""
        try:
            # Small epsilon — recv(0) with asyncio.wait_for cancels immediately
            # even when data is available, so use a brief window instead.
            return cast(TResponse, await self._transport.recv(0.01))
        except Exception:
            raise ChannelClosedError("Channel is closed")

    async def _poll_for_response(self, request_id: str, timeout: float) -> TResponse:
        """Poll for a response with the given request_id."""
        deadline = time.monotonic() + timeout
        poll_interval = 0.05

        while True:
            if self.is_closed:
                raise ChannelClosedError("Channel closed while waiting for response")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChannelTimeoutError(
                    f"Request {request_id} timed out after {timeout}s"
                )

            message = await self._check_redelivery(request_id)
            if message is not None:
                return self._validate_response(message)

            message = await self._try_recv(min(poll_interval, remaining))
            if message is None:
                continue

            if hasattr(message, "id") and message.id == request_id:
                return self._validate_response(message)

            await self._buffer_for_redelivery(message)

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
            if self.is_closed:
                raise ChannelClosedError("Channel closed while waiting for chunk")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChannelTimeoutError(
                    f"Stream {request_id} timed out waiting for chunk"
                )

            message = await self._check_redelivery(request_id)
            if message is not None:
                return self._validate_response(message)

            message = await self._try_recv(min(poll_interval, remaining))
            if message is None:
                continue

            if hasattr(message, "id") and message.id == request_id:
                return self._validate_response(message)

            await self._buffer_for_redelivery(message)

    async def _buffer_for_redelivery(self, message: Any) -> None:
        """Buffer a message for redelivery, discarding oldest if at capacity."""
        if self._redelivery.qsize() >= self._MAX_REDELIVERY:
            try:
                self._redelivery.get_nowait()
                self.redelivery_drops += 1
            except asyncio.QueueEmpty:
                pass
        await self._redelivery.put(message)

    async def _try_recv(self, timeout: float) -> Any | None:
        """Try to receive, returning None on timeout."""
        try:
            return await self._transport.recv(timeout)
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


# ---------------------------------------------------------------------------
# Built-in async transports
# ---------------------------------------------------------------------------


class AsyncQueueTransport(Generic[TRequest, TResponse]):
    """Async transport using ``asyncio.Queue`` for coroutine communication."""

    def __init__(
        self,
        outbound: asyncio.Queue[TRequest],
        inbound: asyncio.Queue[TResponse],
    ) -> None:
        self._outbound = outbound
        self._inbound = inbound
        self._closed = False

    async def send(self, message: TRequest) -> None:
        """Put message on the outbound asyncio queue."""
        await self._outbound.put(message)

    async def recv(self, timeout: float | None = None) -> TResponse:
        """Get next message from the inbound asyncio queue."""
        try:
            return await asyncio.wait_for(self._inbound.get(), timeout=timeout)
        except TimeoutError:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    async def close(self) -> None:
        """Mark as closed."""
        self._closed = True

    @property
    def is_closed(self) -> bool:
        """Return True if closed."""
        return self._closed


class AsyncProcessQueueTransport(Generic[TRequest, TResponse]):
    """Async transport wrapping ``multiprocessing.Queue`` for cross-process IPC."""

    def __init__(
        self,
        outbound: mp.Queue[TRequest],
        inbound: mp.Queue[TResponse],
    ) -> None:
        self._outbound = outbound
        self._inbound = inbound
        self._closed = False

    async def send(self, message: TRequest) -> None:
        """Put message on the outbound mp.Queue via executor."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._outbound.put, message)

    async def recv(self, timeout: float | None = None) -> TResponse:
        """Get next message from the inbound mp.Queue via executor."""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: self._inbound.get(timeout=timeout)
            )
        except queue.Empty:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    async def close(self) -> None:
        """Close both multiprocessing queues."""
        self._closed = True
        try:
            self._outbound.close()
            self._inbound.close()
        except Exception:
            pass

    @property
    def is_closed(self) -> bool:
        """Return True if closed."""
        return self._closed
