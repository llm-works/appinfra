"""Synchronous channel implementations.

This module provides:
- Channel: Abstract base for sync bidirectional channels
- ThreadChannel: Channel using queue.Queue for thread-based communication
- ProcessChannel: Channel using multiprocessing.Queue for cross-process IPC
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar, cast

from ..errors import ChannelClosedError, ChannelError, ChannelTimeoutError

TRequest = TypeVar("TRequest")
TResponse = TypeVar("TResponse")


class Channel(ABC, Generic[TRequest, TResponse]):
    """
    Bidirectional channel for service communication.

    Provides three communication patterns:
    1. Fire-and-forget: send() without waiting for response
    2. Receive: recv() to get next incoming message
    3. Request/response: submit() sends and waits for matching response

    Thread-safe for concurrent send/recv from multiple threads.
    """

    @abstractmethod
    def send(self, message: TRequest) -> None:
        """Send message without waiting for response."""

    @abstractmethod
    def recv(self, timeout: float | None = None) -> TResponse:
        """Receive next incoming message."""

    @abstractmethod
    def submit(self, request: TRequest, timeout: float | None = None) -> TResponse:
        """Send request and wait for matching response."""

    @abstractmethod
    def close(self) -> None:
        """Close the channel."""

    @property
    @abstractmethod
    def is_closed(self) -> bool:
        """True if channel has been closed."""


class _BaseChannel(Channel[TRequest, TResponse]):
    """Base implementation with common logic for submit()."""

    def __init__(self, response_timeout: float = 30.0) -> None:
        self._response_timeout = response_timeout
        self._closed = False
        self._lock = threading.Lock()
        self._redelivery: queue.Queue[Any] = queue.Queue()

    @property
    def is_closed(self) -> bool:
        return self._closed

    def _get_from_queue(self, timeout: float | None) -> Any:
        """Get message from inbound queue. Implemented by subclasses."""
        raise NotImplementedError

    def submit(self, request: TRequest, timeout: float | None = None) -> TResponse:
        """Send request and wait for matching response."""
        if self._closed:
            raise ChannelClosedError("Channel is closed")
        if not hasattr(request, "id"):
            raise ValueError("Request must have an 'id' attribute")

        request_id = request.id  # type: ignore[union-attr]
        effective_timeout = timeout if timeout is not None else self._response_timeout

        self.send(request)
        return self._poll_for_response(request_id, effective_timeout)

    def _poll_for_response(self, request_id: str, timeout: float) -> TResponse:
        """Poll for a response with the given request_id."""
        deadline = time.monotonic() + timeout
        poll_interval = 0.05

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChannelTimeoutError(
                    f"Request {request_id} timed out after {timeout}s"
                )

            message = self._check_redelivery(request_id)
            if message is not None:
                return self._validate_response(message)

            message = self._try_get_message(min(poll_interval, remaining))
            if message is None:
                continue

            if hasattr(message, "id") and message.id == request_id:
                return self._validate_response(message)

            self._redelivery.put(message)

    def _try_get_message(self, timeout: float) -> Any | None:
        """Try to get a message from the queue, returning None on timeout."""
        try:
            return self._get_from_queue(timeout)
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

    def close(self) -> None:
        """Close channel."""
        self._closed = True


class ThreadChannel(_BaseChannel[TRequest, TResponse]):
    """Channel using queue.Queue for thread-based communication."""

    def __init__(
        self,
        outbound: queue.Queue[TRequest],
        inbound: queue.Queue[TResponse],
        response_timeout: float = 30.0,
    ) -> None:
        super().__init__(response_timeout)
        self._outbound = outbound
        self._inbound = inbound

    def send(self, message: TRequest) -> None:
        if self._closed:
            raise ChannelClosedError("Channel is closed")
        self._outbound.put(message)

    def _get_from_queue(self, timeout: float | None) -> Any:
        try:
            return self._inbound.get(timeout=timeout)
        except queue.Empty:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    def recv(self, timeout: float | None = None) -> TResponse:
        try:
            return cast(TResponse, self._redelivery.get_nowait())
        except queue.Empty:
            pass

        if self._closed:
            try:
                return cast(TResponse, self._inbound.get_nowait())
            except queue.Empty:
                raise ChannelClosedError("Channel is closed")

        return cast(TResponse, self._get_from_queue(timeout))


class ProcessChannel(_BaseChannel[TRequest, TResponse]):
    """Channel using multiprocessing.Queue for cross-process communication."""

    def __init__(
        self,
        outbound: mp.Queue[TRequest],
        inbound: mp.Queue[TResponse],
        response_timeout: float = 30.0,
    ) -> None:
        super().__init__(response_timeout)
        self._outbound = outbound
        self._inbound = inbound

    def send(self, message: TRequest) -> None:
        if self._closed:
            raise ChannelClosedError("Channel is closed")
        self._outbound.put(message)

    def _get_from_queue(self, timeout: float | None) -> Any:
        try:
            return self._inbound.get(timeout=timeout)
        except queue.Empty:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    def recv(self, timeout: float | None = None) -> TResponse:
        try:
            return cast(TResponse, self._redelivery.get_nowait())
        except queue.Empty:
            pass

        # ProcessChannel.close() closes underlying mp.Queue, so we can't drain
        if self._closed:
            raise ChannelClosedError("Channel is closed")

        return cast(TResponse, self._get_from_queue(timeout))

    def close(self) -> None:
        super().close()
        try:
            self._outbound.close()
            self._inbound.close()
        except Exception:
            pass
