"""Synchronous channel implementations.

This module provides:
- Transport: Protocol for custom wire transports (implement send/recv/close)
- Channel: Concrete channel with submit/recv correlation on top of a Transport
- QueueTransport: Transport using queue.Queue (in-process threads)
- ProcessQueueTransport: Transport using multiprocessing.Queue (cross-process)

Custom transport example::

    class ZMQTransport:
        def __init__(self, socket: zmq.Socket) -> None:
            self._socket = socket
            self._closed = False

        def send(self, message: Any) -> None:
            self._socket.send_pyobj(message)

        def recv(self, timeout: float | None = None) -> Any:
            ms = int((timeout or 0) * 1000)
            if self._socket.poll(timeout=ms):
                return self._socket.recv_pyobj()
            raise ChannelTimeoutError(f"Timeout ({timeout}s)")

        def close(self) -> None:
            self._closed = True
            self._socket.close()

        @property
        def is_closed(self) -> bool:
            return self._closed

    channel = Channel(ZMQTransport(socket), response_timeout=30.0)
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import time
from typing import Any, Generic, Protocol, TypeVar, cast, runtime_checkable

from ..errors import ChannelClosedError, ChannelError, ChannelTimeoutError

TRequest = TypeVar("TRequest")
TResponse = TypeVar("TResponse")


@runtime_checkable
class Transport(Protocol):
    """
    Wire-level transport protocol.

    Implement this protocol to plug in a custom transport (e.g., ZMQ, gRPC,
    shared memory). The ``Channel`` class wraps a Transport and adds
    request/response correlation, redelivery buffering, and close management.

    All four methods must be implemented. No base class required — any object
    satisfying the protocol is accepted.
    """

    def send(self, message: Any) -> None:
        """Send a message over the wire."""
        ...

    def recv(self, timeout: float | None = None) -> Any:
        """
        Receive the next message from the wire.

        Args:
            timeout: Maximum seconds to wait. None means block indefinitely.

        Returns:
            The next message.

        Raises:
            ChannelTimeoutError: If no message arrives within timeout.
        """
        ...

    def close(self) -> None:
        """Release transport resources (sockets, file descriptors, etc.)."""
        ...

    @property
    def is_closed(self) -> bool:
        """True if the transport has been closed."""
        ...


class Channel(Generic[TRequest, TResponse]):
    """
    Bidirectional channel for service communication.

    Wraps a ``Transport`` and adds:
    - **Request/response correlation**: ``submit()`` sends a request and waits
      for a response with a matching ``id`` attribute.
    - **Redelivery buffering**: Messages received out of order during
      ``submit()`` are buffered and returned by subsequent ``recv()`` calls.
    - **Close management**: ``close()`` propagates to the transport and
      unblocks any waiting ``recv()``/``submit()`` calls.

    Three communication patterns:

    1. Fire-and-forget: ``send()`` without waiting for response
    2. Receive: ``recv()`` to get next incoming message
    3. Request/response: ``submit()`` sends and waits for matching response

    Note:
        ``submit()`` and ``recv()`` share the same inbound stream. If using
        both patterns concurrently, messages may be buffered in the redelivery
        queue. For pure request/response, use ``submit()`` exclusively. For
        pure streaming, use ``recv()`` exclusively.

    Args:
        transport: The underlying wire transport.
        response_timeout: Default timeout for ``submit()`` calls (seconds).
    """

    _MAX_REDELIVERY = 4096

    def __init__(
        self,
        transport: Transport,
        response_timeout: float = 30.0,
    ) -> None:
        self._transport = transport
        self._response_timeout = response_timeout
        self._closed = False
        self._redelivery: queue.Queue[Any] = queue.Queue()
        self.redelivery_drops: int = 0

    @property
    def transport(self) -> Transport:
        """The underlying wire transport."""
        return self._transport

    @property
    def is_closed(self) -> bool:
        """True if the channel or its transport has been closed."""
        return self._closed or self._transport.is_closed

    def send(self, message: TRequest) -> None:
        """Send message without waiting for response."""
        if self.is_closed:
            raise ChannelClosedError("Channel is closed")
        self._transport.send(message)

    def recv(self, timeout: float | None = None) -> TResponse:
        """
        Receive next incoming message.

        Checks the redelivery buffer first, then polls the transport
        with periodic close checks. When closed, attempts to drain one
        remaining buffered message before raising ``ChannelClosedError``.
        """
        try:
            return cast(TResponse, self._redelivery.get_nowait())
        except queue.Empty:
            pass

        if self.is_closed:
            return self._drain_or_raise()

        return self._recv_poll(timeout)

    def submit(self, request: TRequest, timeout: float | None = None) -> TResponse:
        """Send request and wait for matching response."""
        if self.is_closed:
            raise ChannelClosedError("Channel is closed")
        if not hasattr(request, "id"):
            raise ValueError("Request must have an 'id' attribute")

        request_id = request.id  # type: ignore[union-attr]
        effective_timeout = timeout if timeout is not None else self._response_timeout

        self.send(request)
        return self._poll_for_response(request_id, effective_timeout)

    def close(self) -> None:
        """Close the channel and its transport."""
        self._closed = True
        self._transport.close()

    # -- internal helpers --------------------------------------------------

    def _drain_or_raise(self) -> TResponse:
        """Try to drain one buffered message from the transport before raising."""
        try:
            return cast(TResponse, self._transport.recv(0))
        except Exception:
            raise ChannelClosedError("Channel is closed")

    def _recv_poll(self, timeout: float | None) -> TResponse:
        """Poll transport with periodic close checks."""
        poll_interval = 0.1
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            if self.is_closed:
                raise ChannelClosedError("Channel is closed")

            wait_time = self._calc_wait_time(poll_interval, deadline, timeout)
            try:
                return cast(TResponse, self._transport.recv(wait_time))
            except ChannelTimeoutError:
                if deadline is not None and time.monotonic() >= deadline:
                    raise

    def _poll_for_response(self, request_id: str, timeout: float) -> TResponse:
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

            message = self._check_redelivery(request_id)
            if message is not None:
                return self._validate_response(message)

            message = self._try_recv(min(poll_interval, remaining))
            if message is None:
                continue

            if hasattr(message, "id") and message.id == request_id:
                return self._validate_response(message)

            self._buffer_for_redelivery(message)

    def _buffer_for_redelivery(self, message: Any) -> None:
        """Buffer a message for redelivery, discarding oldest if at capacity."""
        if self._redelivery.qsize() >= self._MAX_REDELIVERY:
            try:
                self._redelivery.get_nowait()
                self.redelivery_drops += 1
            except queue.Empty:
                pass
        self._redelivery.put(message)

    def _try_recv(self, timeout: float) -> Any | None:
        """Try to receive, returning None on timeout."""
        try:
            return self._transport.recv(timeout)
        except ChannelTimeoutError:
            return None

    def _validate_response(self, message: Any) -> TResponse:
        """Validate response and raise ChannelError if it contains an error."""
        if hasattr(message, "error") and message.error:
            raise ChannelError(f"Request failed: {message.error}")
        return cast(TResponse, message)

    def _check_redelivery(self, request_id: str) -> Any | None:
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
            except queue.Empty:
                break

        for msg in recheck:
            self._redelivery.put(msg)

        return result

    def _calc_wait_time(
        self, poll_interval: float, deadline: float | None, timeout: float | None
    ) -> float:
        """Calculate wait time for next poll iteration."""
        if deadline is None:
            return poll_interval
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")
        return min(poll_interval, remaining)


# ---------------------------------------------------------------------------
# Built-in transports
# ---------------------------------------------------------------------------


class QueueTransport(Generic[TRequest, TResponse]):
    """Transport using ``queue.Queue`` for in-process thread communication."""

    def __init__(
        self,
        outbound: queue.Queue[TRequest],
        inbound: queue.Queue[TResponse],
    ) -> None:
        self._outbound = outbound
        self._inbound = inbound
        self._closed = False

    def send(self, message: TRequest) -> None:
        """Put message on the outbound queue."""
        self._outbound.put(message)

    def recv(self, timeout: float | None = None) -> TResponse:
        """Get next message from the inbound queue."""
        try:
            return cast(TResponse, self._inbound.get(timeout=timeout))
        except queue.Empty:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    def close(self) -> None:
        """Mark as closed (queue.Queue has no close method)."""
        self._closed = True

    @property
    def is_closed(self) -> bool:
        """Return True if closed."""
        return self._closed


class ProcessQueueTransport(Generic[TRequest, TResponse]):
    """Transport using ``multiprocessing.Queue`` for cross-process IPC."""

    def __init__(
        self,
        outbound: mp.Queue[TRequest],
        inbound: mp.Queue[TResponse],
    ) -> None:
        self._outbound = outbound
        self._inbound = inbound
        self._closed = False

    def send(self, message: TRequest) -> None:
        """Put message on the outbound mp.Queue."""
        self._outbound.put(message)

    def recv(self, timeout: float | None = None) -> TResponse:
        """Get next message from the inbound mp.Queue."""
        try:
            return cast(TResponse, self._inbound.get(timeout=timeout))
        except queue.Empty:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    def close(self) -> None:
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
