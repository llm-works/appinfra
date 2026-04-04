"""Asynchronous channel implementations.

This module provides:
- AsyncChannel: Protocol for async bidirectional communication (implement
  directly for smart transports like ZMQ that handle their own correlation)
- AsyncTransport: Protocol for dumb async wire transports (send/recv/close)
- AsyncBufferedChannel: Concrete AsyncChannel wrapping an AsyncTransport with
  correlation, streaming, and redelivery buffering
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

from ..errors import ChannelClosedError, ChannelTimeoutError
from .base import RedeliveryBuffer, validate_response

TRequest = TypeVar("TRequest")
TResponse = TypeVar("TResponse")


@runtime_checkable
class AsyncChannel(Protocol):
    """
    Async bidirectional channel protocol.

    Implement this directly for smart transports (e.g., ZMQ, gRPC) that
    handle their own request/response correlation.  For dumb transports
    that only provide raw send/recv, use ``AsyncBufferedChannel`` which
    wraps an ``AsyncTransport`` and adds correlation, streaming, redelivery
    buffering, and close management.
    """

    async def send(self, message: Any) -> None:
        """Send message without waiting for response."""
        ...

    async def recv(self, timeout: float | None = None) -> Any:
        """Receive next incoming message."""
        ...

    async def submit(self, request: Any, timeout: float | None = None) -> Any:
        """Send request and wait for matching response."""
        ...

    def submit_stream(
        self, request: Any, timeout: float | None = None
    ) -> AsyncIterator[Any]:
        """Send request and yield streaming response chunks."""
        ...

    async def close(self) -> None:
        """Close the channel."""
        ...

    @property
    def is_closed(self) -> bool:
        """True if channel has been closed."""
        ...


@runtime_checkable
class AsyncTransport(Protocol):
    """
    Async wire-level transport protocol.

    Implement this protocol to plug in a custom async transport. The
    ``AsyncBufferedChannel`` class wraps an AsyncTransport and adds
    request/response correlation, streaming, redelivery buffering, and close
    management.
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


class AsyncBufferedChannel(Generic[TRequest, TResponse]):
    """
    Async channel wrapping an AsyncTransport with correlation and redelivery.

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

    def __init__(
        self,
        transport: AsyncTransport,
        response_timeout: float = 30.0,
    ) -> None:
        self._transport = transport
        self._response_timeout = response_timeout
        self._closed = False
        self._redelivery = RedeliveryBuffer()

    @property
    def transport(self) -> AsyncTransport:
        """The underlying async wire transport."""
        return self._transport

    @property
    def redelivery_drops(self) -> int:
        """Number of messages dropped due to redelivery buffer overflow."""
        return self._redelivery.drops

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
        msg = self._redelivery.pop_any()
        if msg is not None:
            return cast(TResponse, msg)

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
                    return await self._drain_or_timeout(timeout)
                wait = min(poll_interval, remaining)

            try:
                return cast(TResponse, await self._transport.recv(wait))
            except ChannelTimeoutError:
                if deadline is not None and time.monotonic() >= deadline:
                    return await self._drain_or_timeout(timeout)

    async def _drain_or_timeout(self, timeout: float | None) -> TResponse:
        """Try one non-blocking recv before raising ChannelTimeoutError."""
        try:
            return cast(TResponse, await self._transport.recv(0.01))
        except Exception:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    async def _drain_or_raise(self) -> TResponse:
        """Try to drain one buffered message from the transport before raising."""
        try:
            # Small epsilon — recv(0) with asyncio.wait_for cancels immediately
            # even when data is available, so use a brief window instead.
            return cast(TResponse, await self._transport.recv(0.01))
        except ChannelTimeoutError:
            raise ChannelClosedError("Channel is closed")
        except Exception as exc:
            raise ChannelClosedError("Channel is closed") from exc

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

            message = self._redelivery.check(request_id)
            if message is not None:
                return cast(TResponse, validate_response(message))

            message = await self._try_recv(min(poll_interval, remaining))
            if message is None:
                continue

            if hasattr(message, "id") and message.id == request_id:
                return cast(TResponse, validate_response(message))

            self._redelivery.put(message)

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

            message = self._redelivery.check(request_id)
            if message is not None:
                return cast(TResponse, validate_response(message))

            message = await self._try_recv(min(poll_interval, remaining))
            if message is None:
                continue

            if hasattr(message, "id") and message.id == request_id:
                return cast(TResponse, validate_response(message))

            self._redelivery.put(message)

    async def _try_recv(self, timeout: float) -> Any | None:
        """Try to receive, returning None on timeout."""
        try:
            return await self._transport.recv(timeout)
        except ChannelTimeoutError:
            return None


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

    _RECV_CAP = 60.0

    async def recv(self, timeout: float | None = None) -> TResponse:
        """Get next message from the inbound mp.Queue via executor.

        When timeout is None, caps at ``_RECV_CAP`` (60s) to avoid blocking
        the executor thread indefinitely — mp.Queue.get(timeout=None) cannot
        be interrupted by close().  The channel's poll loop retries
        automatically, so the cap is transparent to callers.
        """
        effective = timeout if timeout is not None else self._RECV_CAP
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: self._inbound.get(timeout=effective)
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
