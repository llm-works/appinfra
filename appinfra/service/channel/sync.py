# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Synchronous channel implementations.

This module provides:
- Channel: Protocol for sync bidirectional communication (implement directly
  for smart transports like ZMQ that handle their own correlation)
- Transport: Protocol for dumb wire transports (send/recv/close)
- BufferedChannel: Concrete Channel wrapping a Transport with correlation and
  redelivery buffering
- QueueTransport: Transport using queue.Queue (in-process threads)
- ProcessQueueTransport: Transport using multiprocessing.Queue (cross-process)

Smart transport (implements Channel directly)::

    class ZMQChannel:
        def send(self, message): ...
        def recv(self, timeout=None): ...
        def submit(self, request, timeout=None): ...
        def stream(self, request, timeout=None): ...
        def close(self): ...
        @property
        def is_closed(self) -> bool: ...

Dumb transport (wrap in BufferedChannel)::

    channel = BufferedChannel(QueueTransport(outbound, inbound))
"""

from __future__ import annotations

import contextlib
import multiprocessing as mp
import queue
import threading
import time
from collections.abc import Iterator
from typing import Any, Generic, Protocol, TypeVar, cast, runtime_checkable

from ..errors import ChannelClosedError, ChannelFullError, ChannelTimeoutError
from .base import RedeliveryBuffer, recv_slice, route, send_slice, validate_response

TRequest = TypeVar("TRequest")
TResponse = TypeVar("TResponse")


@runtime_checkable
class Channel(Protocol):
    """
    Sync bidirectional channel protocol.

    Implement this directly for smart transports (e.g., ZMQ, gRPC) that
    handle their own request/response correlation.  For dumb transports
    that only provide raw send/recv, use ``BufferedChannel`` which wraps a
    ``Transport`` and adds correlation, redelivery buffering, and close
    management.
    """

    def send(self, message: Any, timeout: float | None = None) -> None:
        """Send message without waiting for response.

        Raises ``ChannelFullError`` if there is no room within *timeout*
        seconds (None waits until there is, 0 does not wait).
        """
        ...

    def recv(self, timeout: float | None = None) -> Any:
        """Receive next incoming message."""
        ...

    def submit(self, request: Any, timeout: float | None = None) -> Any:
        """Send request and wait for matching response."""
        ...

    def stream(self, request: Any, timeout: float | None = None) -> Iterator[Any]:
        """Send request and yield streaming response chunks."""
        ...

    def close(self) -> None:
        """Close the channel."""
        ...

    @property
    def is_closed(self) -> bool:
        """True if channel has been closed."""
        ...


@runtime_checkable
class Transport(Protocol):
    """
    Wire-level transport protocol.

    Implement this protocol to plug in a custom transport (e.g., ZMQ, gRPC,
    shared memory). The ``BufferedChannel`` class wraps a Transport and adds
    request/response correlation, redelivery buffering, and close management.

    All four methods must be implemented. No base class required — any object
    satisfying the protocol is accepted.
    """

    def send(self, message: Any, timeout: float | None = None) -> None:
        """
        Send a message over the wire.

        Important:
            Implementations **must** honor the *timeout* parameter like
            ``recv()``: ``BufferedChannel`` sends in short slices to check for
            close while the wire is full.

        Args:
            message: Message to send.
            timeout: Maximum seconds to wait for room. None means block
                indefinitely; 0 means do not wait.

        Raises:
            ChannelFullError: If there is no room within timeout.
        """
        ...

    def recv(self, timeout: float | None = None) -> Any:
        """
        Receive the next message from the wire.

        Important:
            Implementations **must** honor the *timeout* parameter and return
            or raise within that window.  ``Channel`` relies on short-interval
            polling to check for close; a transport that blocks indefinitely
            will prevent close from taking effect promptly.

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


class BufferedChannel(Generic[TRequest, TResponse]):
    """
    Sync channel wrapping a Transport with correlation and redelivery.

    Wraps a ``Transport`` and adds:
    - **Request/response correlation**: ``submit()`` sends a request and waits
      for a response with a matching ``id`` attribute.
    - **Redelivery buffering**: Messages received out of order during
      ``submit()`` are buffered and returned by subsequent ``recv()`` calls.
    - **Close management**: ``close()`` propagates to the transport and
      unblocks any waiting ``recv()``/``submit()`` calls.

    Four communication patterns:

    1. Fire-and-forget: ``send()`` without waiting for response
    2. Receive: ``recv()`` to get next incoming message
    3. Request/response: ``submit()`` sends and waits for matching response
    4. Streaming: ``stream()`` yields response chunks until ``is_final``

    Note:
        ``submit()`` and ``recv()`` share the same inbound stream. If using
        both patterns concurrently, messages may be buffered in the redelivery
        queue. For pure request/response, use ``submit()`` exclusively. For
        pure streaming, use ``recv()`` exclusively.

    Args:
        transport: The underlying wire transport.
        response_timeout: Default timeout for ``submit()`` calls (seconds).
    """

    def __init__(
        self,
        transport: Transport,
        response_timeout: float = 30.0,
    ) -> None:
        self._transport = transport
        self._response_timeout = response_timeout
        self._closed = False
        self._redelivery = RedeliveryBuffer()
        self._lock = threading.Lock()
        # Held by submit() and stream() for one round: check the buffer, receive,
        # route. A message another caller received is then buffered before this
        # caller looks, so a stream's chunks stay in order. close() takes _lock
        # only, never waiting on a receive.
        self._recv_lock = threading.Lock()

    def __getstate__(self) -> dict[str, Any]:
        """State pickled when the channel is passed to a spawn or forkserver child.

        The lock and the redelivery buffer stay in this process: the child gets a
        fresh lock and an empty buffer, so a buffered message is never delivered
        by both processes.
        """
        state = self.__dict__.copy()
        del state["_lock"]
        del state["_recv_lock"]
        del state["_redelivery"]
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        self._redelivery = RedeliveryBuffer()
        self._lock = threading.Lock()
        self._recv_lock = threading.Lock()

    @property
    def transport(self) -> Transport:
        """The underlying wire transport."""
        return self._transport

    @property
    def redelivery_drops(self) -> int:
        """Number of messages dropped due to redelivery buffer overflow."""
        return self._redelivery.drops

    @property
    def is_closed(self) -> bool:
        """True if the channel or its transport has been closed."""
        return self._closed or self._transport.is_closed

    def send(self, message: TRequest, timeout: float | None = None) -> None:
        """
        Send message without waiting for response.

        While the transport is full, retries in short slices so that
        ``close()`` interrupts the wait.

        Args:
            message: Message to send.
            timeout: Maximum seconds to wait for room. None waits until there
                is room or the channel closes; 0 tries once.

        Raises:
            ChannelClosedError: If the channel is closed, or closes while waiting.
            ChannelFullError: If the transport stays full for *timeout* seconds.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self.is_closed:
                raise ChannelClosedError("Channel is closed")
            try:
                self._transport.send(message, send_slice(deadline))
                return
            except ChannelFullError:
                if deadline is not None and time.monotonic() >= deadline:
                    raise ChannelFullError(f"Channel full for {timeout}s") from None

    def recv(self, timeout: float | None = None) -> TResponse:
        """
        Receive next incoming message.

        Checks the redelivery buffer first, then polls the transport
        with periodic close checks. When closed, attempts to drain one
        remaining buffered message before raising ``ChannelClosedError``.

        Thread-safe: concurrent ``recv()`` / ``submit()`` / ``close()`` calls
        are guarded by an internal lock around redelivery and state access.
        """
        with self._lock:
            msg = self._redelivery.pop_any()
            if msg is not None:
                return cast(TResponse, msg)
            if self.is_closed:
                return self._drain_or_raise()

        return self._recv_poll(timeout)

    def submit(self, request: TRequest, timeout: float | None = None) -> TResponse:
        """Send request and wait for matching response.

        *timeout* covers both waiting for room to send and waiting for the
        response.
        """
        request_id, effective_timeout = self._request_id(request, timeout)
        deadline = time.monotonic() + effective_timeout

        self.send(request, effective_timeout)
        return self._poll_for_response(request_id, deadline, effective_timeout)

    def stream(
        self, request: TRequest, timeout: float | None = None
    ) -> Iterator[TResponse]:
        """Send request and yield the response chunks carrying its id, until
        one with ``is_final=True``; a chunk without ``is_final`` is final.

        Like ``AsyncBufferedChannel.stream()``, the request is sent when
        iteration begins, and *timeout* applies to the send and to the wait for
        each chunk on its own. Other messages go to the redelivery buffer.
        """
        request_id, effective_timeout = self._request_id(request, timeout)
        self.send(request, effective_timeout)
        while True:
            deadline = time.monotonic() + effective_timeout
            chunk = self._poll_for_response(request_id, deadline, effective_timeout)
            yield chunk
            if getattr(chunk, "is_final", True):
                return

    def close(self) -> None:
        """Close the channel and its transport."""
        with self._lock:
            self._closed = True
        self._transport.close()

    # -- internal helpers --------------------------------------------------

    def _request_id(
        self, request: TRequest, timeout: float | None
    ) -> tuple[str, float]:
        """The id of *request* and the timeout to use for it.

        Raises:
            ChannelClosedError: If the channel is closed.
            ValueError: If *request* has no ``id``.
        """
        if self.is_closed:
            raise ChannelClosedError("Channel is closed")
        if not hasattr(request, "id"):
            raise ValueError("Request must have an 'id' attribute")
        return request.id, timeout if timeout is not None else self._response_timeout

    def _drain_or_raise(self) -> TResponse:
        """Try to drain one buffered message from the transport before raising."""
        try:
            return cast(TResponse, self._transport.recv(0))
        except ChannelTimeoutError:
            raise ChannelClosedError("Channel is closed")
        except Exception as exc:
            raise ChannelClosedError("Channel is closed") from exc

    def _drain_or_timeout(self, timeout: float | None) -> TResponse:
        """Try one non-blocking recv before raising ChannelTimeoutError."""
        try:
            return cast(TResponse, self._transport.recv(0))
        except Exception:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    def _recv_poll(self, timeout: float | None) -> TResponse:
        """Poll transport with periodic close checks."""
        poll_interval = 0.1
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            if self.is_closed:
                return self._drain_or_raise()

            wait_time = self._calc_wait_time(poll_interval, deadline, timeout)
            try:
                return cast(TResponse, self._transport.recv(wait_time))
            except ChannelTimeoutError:
                if deadline is not None and time.monotonic() >= deadline:
                    return self._drain_or_timeout(timeout)

    def _poll_for_response(
        self, request_id: str, deadline: float, timeout: float
    ) -> TResponse:
        """Poll for a response with the given request_id until *deadline*."""
        while True:
            with self._recv_lock:
                message = self._poll_once(request_id, deadline, timeout)
            if message is not None:
                return cast(TResponse, validate_response(message))

    def _poll_once(self, request_id: str, deadline: float, timeout: float) -> Any:
        """One round under _recv_lock: the buffered message for *request_id*, or
        one received from the transport; a received message for another id is
        buffered. None if nothing for *request_id* arrived this round."""
        with self._lock:
            if self.is_closed:
                raise ChannelClosedError("Channel closed while waiting for response")
            message = self._redelivery.check(request_id)
        if message is not None:
            return message
        message = self._try_recv(recv_slice(request_id, deadline, timeout))
        with self._lock:
            return route(message, request_id, self._redelivery)

    def _try_recv(self, timeout: float) -> Any | None:
        """Try to receive, returning None on timeout."""
        try:
            return self._transport.recv(timeout)
        except ChannelTimeoutError:
            return None

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

    def send(self, message: TRequest, timeout: float | None = None) -> None:
        """Put message on the outbound queue, waiting up to *timeout* for room."""
        try:
            self._outbound.put(message, timeout=timeout)
        except queue.Full:
            raise ChannelFullError(f"Queue full ({timeout}s)") from None

    def recv(self, timeout: float | None = None) -> TResponse:
        """Get next message from the inbound queue."""
        try:
            return self._inbound.get(timeout=timeout)
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

    def send(self, message: TRequest, timeout: float | None = None) -> None:
        """Put message on the outbound mp.Queue, waiting up to *timeout* for room."""
        try:
            self._outbound.put(message, timeout=timeout)
        except queue.Full:
            raise ChannelFullError(f"Queue full ({timeout}s)") from None
        except ValueError as e:
            # mp.Queue.put() raises ValueError once close() has run.
            if self._closed:
                raise ChannelClosedError("Channel is closed") from e
            raise

    def recv(self, timeout: float | None = None) -> TResponse:
        """Get next message from the inbound mp.Queue."""
        try:
            return self._inbound.get(timeout=timeout)
        except queue.Empty:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    def close(self) -> None:
        """Close both multiprocessing queues."""
        self._closed = True
        with contextlib.suppress(Exception):
            self._outbound.close()
        with contextlib.suppress(Exception):
            self._inbound.close()

    def allow_exit_without_flush(self) -> None:
        """Let this process exit without waiting for unsent messages to reach the pipe.

        For an outbound queue whose only reader cannot outlive this process, such as
        a daemon child: multiprocessing terminates daemon children at exit before it
        waits for queue feeders, so that wait could only block. Messages still unsent
        at exit are dropped. See ``multiprocessing.Queue.cancel_join_thread()``.
        """
        self._outbound.cancel_join_thread()

    @property
    def is_closed(self) -> bool:
        """Return True if closed."""
        return self._closed
