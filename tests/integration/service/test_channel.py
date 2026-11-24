# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for service channels with a peer on another thread."""

import threading
from collections import deque
from typing import Any

import pytest

from appinfra.service import (
    BufferedChannel,
    ChannelClosedError,
    ChannelResponseError,
    ChannelTimeoutError,
    Message,
    ProcessQueueChannelFactory,
    QueueChannelFactory,
)
from tests.helpers.service.channel import Request, Response


class TestQueueChannel:
    """Tests for Channel with QueueTransport."""

    def test_submit_request_response(self) -> None:
        """submit() sends request and waits for matching response."""
        pair = QueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        # Responder thread
        def responder() -> None:
            req = child.recv(timeout=1.0)
            child.send(Response(id=req.id, result=f"got: {req.data}"))

        t = threading.Thread(target=responder)
        t.start()

        response = parent.submit(Request(id="req-1", data="test"), timeout=1.0)

        t.join()
        assert response.id == "req-1"
        assert response.result == "got: test"

    def test_concurrent_submits(self) -> None:
        """Multiple concurrent submits get correct responses."""
        pair = QueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child
        results: dict[str, str] = {}

        def responder() -> None:
            for _ in range(3):
                req = child.recv(timeout=1.0)
                child.send(Response(id=req.id, result=f"resp-{req.id}"))

        def submitter(req_id: str) -> None:
            resp = parent.submit(Request(id=req_id, data="x"), timeout=1.0)
            results[req_id] = resp.result

        t_resp = threading.Thread(target=responder)
        t_resp.start()

        threads = [
            threading.Thread(target=submitter, args=(f"req-{i}",)) for i in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        t_resp.join()

        assert results == {
            "req-0": "resp-req-0",
            "req-1": "resp-req-1",
            "req-2": "resp-req-2",
        }

    def test_response_with_error(self) -> None:
        """submit() raises ChannelError if response has error."""
        pair = QueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        def responder() -> None:
            req = child.recv(timeout=1.0)
            child.send(Response(id=req.id, result="", error="something failed"))

        t = threading.Thread(target=responder)
        t.start()

        with pytest.raises(ChannelResponseError, match="something failed") as exc:
            parent.submit(Request(id="1", data="test"), timeout=1.0)
        assert exc.value.response == Response(
            id="1", result="", error="something failed"
        )

        t.join()


class TestCloseUnblocksRecv:
    """Tests for close() unblocking recv()."""

    def test_close_unblocks_recv_no_timeout(self) -> None:
        """close() unblocks a thread waiting in recv(timeout=None)."""
        import time

        pair = QueueChannelFactory().create_pair()
        parent = pair.parent
        error_raised: list[Exception] = []

        def blocking_recv() -> None:
            try:
                parent.recv(timeout=None)  # Would block forever
            except ChannelClosedError as e:
                error_raised.append(e)

        t = threading.Thread(target=blocking_recv)
        t.start()

        # Give thread time to start blocking
        time.sleep(0.15)

        # Close should unblock the recv
        parent.close()
        t.join(timeout=1.0)

        assert not t.is_alive(), "Thread should have been unblocked"
        assert len(error_raised) == 1
        assert isinstance(error_raised[0], ChannelClosedError)


class TestProcessQueueChannel:
    """Tests for Channel with ProcessQueueTransport."""

    def test_send_recv(self) -> None:
        """Basic send/recv works."""
        pair = ProcessQueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        parent.send(Request(id="1", data="hello"))
        msg = child.recv(timeout=1.0)

        assert isinstance(msg, Request)
        assert msg.id == "1"
        assert msg.data == "hello"

        pair.close()

    def test_close_channel(self) -> None:
        """Closing channel closes underlying queues."""
        pair = ProcessQueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        parent.send(Request(id="1", data="msg1"))

        # Receive message before closing
        msg = child.recv(timeout=0.1)
        assert msg.data == "msg1"

        # Close both channels
        pair.close()

        assert parent.is_closed
        assert child.is_closed


class RaceTransport:
    """Transport scripted to open the window between a stream's buffer check and
    its receive: the streamer's first receive waits until the submitter has
    buffered a message or waits for the receive lock; the submitter's later
    receives wait until the streamer has received. Waits are on a condition;
    their deadline is the failure path."""

    def __init__(self, *messages: Any) -> None:
        self.inbound = deque(messages)
        self.cond = threading.Condition()
        self.events: set[str] = set()
        self.calls: dict[str, int] = {}
        self.is_closed = False

    def signal(self, event: str) -> None:
        with self.cond:
            self.events.add(event)
            self.cond.notify_all()

    def wait(self, event: str) -> None:
        with self.cond:
            assert self.cond.wait_for(lambda: event in self.events, timeout=5)

    def send(self, message: Any, timeout: float | None = None) -> None:
        pass

    def recv(self, timeout: float | None = None) -> Any:
        name = threading.current_thread().name
        n = self.calls[name] = self.calls.get(name, 0) + 1
        if name == "streamer" and n == 1:
            self.signal("streamer-receiving")
            self.wait("submitter-progress")
        if name == "submitter" and n > 1:
            self.signal("submitter-progress")  # its first message is buffered
            self.wait("streamer-received")
        with self.cond:
            if not self.inbound:
                raise ChannelTimeoutError("empty")
            message = self.inbound.popleft()
        if name == "streamer":
            self.signal("streamer-received")
        return message

    def close(self) -> None:
        self.is_closed = True


class SignallingLock:
    """A lock that tells the transport when the submitter has to wait for it."""

    def __init__(self, transport: RaceTransport) -> None:
        self._lock = threading.Lock()
        self._transport = transport

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if self._lock.acquire(blocking=False):
            return True
        if threading.current_thread().name == "submitter":
            self._transport.signal("submitter-progress")
        return self._lock.acquire(blocking, timeout)

    def release(self) -> None:
        self._lock.release()


class TestStreamWithOtherCallers:
    """BufferedChannel.stream() while another thread's submit() reads the channel."""

    def test_a_chunk_another_thread_buffers_keeps_its_place(self) -> None:
        """A chunk another thread's submit() receives and buffers while the
        stream waits on the transport is yielded before the stream's next one;
        the final chunk does not end the stream with an earlier one buffered."""
        transport = RaceTransport(
            Message(id="X", payload="X1", is_final=False),
            Message(id="X", payload="X2"),
            Message(id="Y", payload="Y"),
        )
        channel: BufferedChannel[Any, Any] = BufferedChannel(transport)
        channel._recv_lock = SignallingLock(transport)  # type: ignore[assignment]
        got: dict[str, Any] = {}

        def streamer() -> None:
            stream = channel.stream(Request(id="X", data="go"), 5.0)
            got["chunks"] = [chunk.payload for chunk in stream]

        def submitter() -> None:
            got["reply"] = channel.submit(Request(id="Y", data="go"), 5.0).payload

        threads = [threading.Thread(target=streamer, name="streamer")]
        threads[0].start()
        transport.wait("streamer-receiving")
        threads.append(threading.Thread(target=submitter, name="submitter"))
        threads[1].start()
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive()

        assert got == {"chunks": ["X1", "X2"], "reply": "Y"}
