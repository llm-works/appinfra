"""Bidirectional channel abstraction for service communication.

Provides sync API for request/response patterns between services and their
runners, or between parent and child processes.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar, cast, runtime_checkable

from .errors import ChannelClosedError, ChannelError, ChannelTimeoutError

# Message types
TRequest = TypeVar("TRequest")
TResponse = TypeVar("TResponse")


@runtime_checkable
class HasId(Protocol):
    """Protocol for messages with an id attribute."""

    id: str


@dataclass
class Message:
    """Generic message with id for request/response correlation.

    Use this as a base for your own message types, or use any object
    with an `id` attribute.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    payload: Any = None
    error: str | None = None
    is_final: bool = True  # For streaming: False until last chunk


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
        """
        Send message without waiting for response.

        Args:
            message: Message to send

        Raises:
            ChannelClosedError: If channel is closed
        """

    @abstractmethod
    def recv(self, timeout: float | None = None) -> TResponse:
        """
        Receive next incoming message.

        Args:
            timeout: Seconds to wait (None = block forever)

        Returns:
            Received message

        Raises:
            ChannelTimeoutError: If timeout expires
            ChannelClosedError: If channel is closed
        """

    @abstractmethod
    def submit(
        self,
        request: TRequest,
        timeout: float | None = None,
    ) -> TResponse:
        """
        Send request and wait for matching response.

        The request must have an `id` attribute. The response is matched
        by its `id` attribute.

        Args:
            request: Request message (must have .id attribute)
            timeout: Seconds to wait for response (None = block forever)

        Returns:
            Response with matching id

        Raises:
            ChannelTimeoutError: If timeout expires
            ChannelClosedError: If channel is closed
            ValueError: If request has no id attribute
        """

    @abstractmethod
    def close(self) -> None:
        """
        Close the channel.

        After closing:
        - send() raises ChannelClosedError
        - recv() returns buffered messages then raises ChannelClosedError
        - submit() raises ChannelClosedError
        """

    @property
    @abstractmethod
    def is_closed(self) -> bool:
        """True if channel has been closed."""


class _BaseChannel(Channel[TRequest, TResponse]):
    """Base implementation with common logic for submit()."""

    def __init__(self, response_timeout: float = 30.0) -> None:
        """
        Initialize channel.

        Args:
            response_timeout: Default timeout for submit() calls
        """
        self._response_timeout = response_timeout
        self._closed = False
        self._lock = threading.Lock()

        # Messages received during submit() that weren't the expected response
        # These get returned by subsequent recv() calls
        self._redelivery: queue.Queue[Any] = queue.Queue()

    @property
    def is_closed(self) -> bool:
        return self._closed

    def _get_from_queue(self, timeout: float | None) -> Any:
        """Get message from inbound queue. Implemented by subclasses."""
        raise NotImplementedError

    def submit(
        self,
        request: TRequest,
        timeout: float | None = None,
    ) -> TResponse:
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
        import time

        deadline = time.monotonic() + timeout
        poll_interval = 0.05

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChannelTimeoutError(
                    f"Request {request_id} timed out after {timeout}s"
                )

            # Check redelivery queue first (another submit may have buffered our response)
            message = self._check_redelivery(request_id)
            if message is not None:
                return self._validate_response(message)

            message = self._try_get_message(min(poll_interval, remaining))
            if message is None:
                continue

            if hasattr(message, "id") and message.id == request_id:
                return self._validate_response(message)

            # Not our response - buffer for later
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
        # Drain redelivery queue, looking for our response
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

        # Put back non-matching messages
        for msg in recheck:
            self._redelivery.put(msg)

        return result

    def close(self) -> None:
        """Close channel."""
        self._closed = True


class ThreadChannel(_BaseChannel[TRequest, TResponse]):
    """
    Channel using queue.Queue for thread-based communication.

    Use this for communication between threads within the same process,
    such as with ThreadRunner.

    Example:
        # Create paired channels
        to_service: queue.Queue = queue.Queue()
        from_service: queue.Queue = queue.Queue()

        # Parent side
        parent_ch = ThreadChannel(outbound=to_service, inbound=from_service)

        # Service side (swap queues)
        service_ch = ThreadChannel(outbound=from_service, inbound=to_service)

        # Request/response
        response = parent_ch.submit(Request(id="1", data="hello"))
    """

    def __init__(
        self,
        outbound: queue.Queue[TRequest],
        inbound: queue.Queue[TResponse],
        response_timeout: float = 30.0,
    ) -> None:
        """
        Initialize thread channel.

        Args:
            outbound: Queue for sending messages
            inbound: Queue for receiving messages
            response_timeout: Default timeout for submit()
        """
        super().__init__(response_timeout)
        self._outbound = outbound
        self._inbound = inbound

    def send(self, message: TRequest) -> None:
        if self._closed:
            raise ChannelClosedError("Channel is closed")
        self._outbound.put(message)

    def _get_from_queue(self, timeout: float | None) -> Any:
        """Get message from inbound queue."""
        try:
            return self._inbound.get(timeout=timeout)
        except queue.Empty:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    def recv(self, timeout: float | None = None) -> TResponse:
        # First check redelivery queue (messages buffered during submit())
        try:
            return cast(TResponse, self._redelivery.get_nowait())
        except queue.Empty:
            pass

        if self._closed:
            # Drain any remaining messages first
            try:
                return cast(TResponse, self._inbound.get_nowait())
            except queue.Empty:
                raise ChannelClosedError("Channel is closed")

        return cast(TResponse, self._get_from_queue(timeout))

    def close(self) -> None:
        super().close()
        # No need to close queue.Queue - they don't have close()


class ProcessChannel(_BaseChannel[TRequest, TResponse]):
    """
    Channel using multiprocessing.Queue for cross-process communication.

    Use this for communication between parent and child processes,
    such as with ProcessRunner.

    Example:
        # Create queues (in parent, before fork)
        to_child: mp.Queue = mp.Queue()
        from_child: mp.Queue = mp.Queue()

        # Parent side
        parent_ch = ProcessChannel(outbound=to_child, inbound=from_child)

        # Child side (swap queues, passed via Process args)
        child_ch = ProcessChannel(outbound=from_child, inbound=to_child)

        # Request/response
        response = parent_ch.submit(Request(id="1", data="hello"))
    """

    def __init__(
        self,
        outbound: mp.Queue[TRequest],
        inbound: mp.Queue[TResponse],
        response_timeout: float = 30.0,
    ) -> None:
        """
        Initialize process channel.

        Args:
            outbound: Queue for sending messages
            inbound: Queue for receiving messages
            response_timeout: Default timeout for submit()
        """
        super().__init__(response_timeout)
        self._outbound = outbound
        self._inbound = inbound

    def send(self, message: TRequest) -> None:
        if self._closed:
            raise ChannelClosedError("Channel is closed")
        self._outbound.put(message)

    def _get_from_queue(self, timeout: float | None) -> Any:
        """Get message from inbound queue."""
        try:
            return self._inbound.get(timeout=timeout)
        except queue.Empty:
            raise ChannelTimeoutError(f"Timeout waiting for message ({timeout}s)")

    def recv(self, timeout: float | None = None) -> TResponse:
        # First check redelivery queue (messages buffered during submit())
        try:
            return cast(TResponse, self._redelivery.get_nowait())
        except queue.Empty:
            pass

        if self._closed:
            # Drain any remaining messages first
            try:
                return cast(TResponse, self._inbound.get_nowait())
            except queue.Empty:
                raise ChannelClosedError("Channel is closed")

        return cast(TResponse, self._get_from_queue(timeout))

    def close(self) -> None:
        super().close()
        # Close mp.Queue to release resources
        try:
            self._outbound.close()
            self._inbound.close()
        except Exception:
            pass  # Ignore errors on close


def create_thread_channel_pair(
    response_timeout: float = 30.0,
) -> tuple[ThreadChannel[Any, Any], ThreadChannel[Any, Any]]:
    """
    Create a pair of connected ThreadChannels.

    Returns (parent_channel, service_channel) where messages sent on one
    are received on the other.

    Example:
        parent_ch, service_ch = create_thread_channel_pair()

        # In service thread
        msg = service_ch.recv()
        service_ch.send(Response(id=msg.id, result="done"))

        # In parent thread
        resp = parent_ch.submit(Request(id="1", data="work"))
    """
    q1: queue.Queue[Any] = queue.Queue()
    q2: queue.Queue[Any] = queue.Queue()

    parent = ThreadChannel(outbound=q1, inbound=q2, response_timeout=response_timeout)
    service = ThreadChannel(outbound=q2, inbound=q1, response_timeout=response_timeout)

    return parent, service


def create_process_channel_pair(
    response_timeout: float = 30.0,
) -> tuple[ProcessChannel[Any, Any], ProcessChannel[Any, Any]]:
    """
    Create a pair of connected ProcessChannels.

    Returns (parent_channel, child_channel) where messages sent on one
    are received on the other.

    IMPORTANT: Create this BEFORE spawning the child process. Pass the
    child_channel's queues to the child process via Process args.

    Example:
        parent_ch, child_ch = create_process_channel_pair()

        def child_main(outbound_q, inbound_q):
            ch = ProcessChannel(outbound=outbound_q, inbound=inbound_q)
            msg = ch.recv()
            ch.send(Response(id=msg.id, result="done"))

        proc = mp.Process(
            target=child_main,
            args=(child_ch._outbound, child_ch._inbound),
        )
        proc.start()

        resp = parent_ch.submit(Request(id="1", data="work"))
    """
    q1: mp.Queue[Any] = mp.Queue()
    q2: mp.Queue[Any] = mp.Queue()

    parent = ProcessChannel(outbound=q1, inbound=q2, response_timeout=response_timeout)
    child = ProcessChannel(outbound=q2, inbound=q1, response_timeout=response_timeout)

    return parent, child
