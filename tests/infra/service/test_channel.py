"""Tests for service channel communication."""

import threading
from dataclasses import dataclass

import pytest

from appinfra.service import (
    Channel,
    ChannelClosedError,
    ChannelConfig,
    ChannelError,
    ChannelTimeoutError,
    Message,
    ProcessQueueChannelFactory,
    QueueChannelFactory,
)
from appinfra.service.channel.base import RedeliveryBuffer, validate_response


@dataclass
class Request:
    """Test request message."""

    id: str
    data: str


@dataclass
class Response:
    """Test response message."""

    id: str
    result: str
    error: str | None = None


class TestMessage:
    """Tests for Message dataclass."""

    def test_default_id_generated(self) -> None:
        """Message generates unique id by default."""
        m1 = Message()
        m2 = Message()
        assert m1.id != m2.id
        assert len(m1.id) > 0

    def test_custom_id(self) -> None:
        """Message accepts custom id."""
        m = Message(id="custom-123")
        assert m.id == "custom-123"

    def test_payload(self) -> None:
        """Message holds arbitrary payload."""
        m = Message(payload={"key": "value"})
        assert m.payload == {"key": "value"}

    def test_error_field(self) -> None:
        """Message has error field for failures."""
        m = Message(error="something went wrong")
        assert m.error == "something went wrong"

    def test_is_final_default(self) -> None:
        """Message is_final defaults to True."""
        m = Message()
        assert m.is_final is True


class TestRedeliveryBuffer:
    """Tests for RedeliveryBuffer shared helper."""

    def test_put_and_check(self) -> None:
        """Messages can be stored and retrieved by id."""
        buf = RedeliveryBuffer()
        buf.put(Message(id="a", payload="hello"))
        buf.put(Message(id="b", payload="world"))

        assert buf.check("b").payload == "world"
        assert buf.check("a").payload == "hello"
        assert buf.check("a") is None

    def test_pop_any(self) -> None:
        """pop_any returns next available message."""
        buf = RedeliveryBuffer()
        buf.put(Message(id="x", payload="first"))
        assert buf.pop_any().payload == "first"
        assert buf.pop_any() is None

    def test_unkeyed_messages(self) -> None:
        """Messages without id go to unkeyed list."""
        buf = RedeliveryBuffer()
        buf.put("plain string")
        assert buf.check("anything") is None
        assert buf.pop_any() == "plain string"

    def test_eviction_at_capacity(self) -> None:
        """Oldest message is evicted when buffer is full."""
        buf = RedeliveryBuffer(max_size=3)
        buf.put(Message(id="1", payload="a"))
        buf.put(Message(id="2", payload="b"))
        buf.put(Message(id="3", payload="c"))
        buf.put(Message(id="4", payload="d"))

        assert buf.drops == 1
        assert buf.size == 3
        assert buf.check("1") is None  # evicted
        assert buf.check("4").payload == "d"

    def test_eviction_unkeyed(self) -> None:
        """Unkeyed messages are evicted after keyed ones."""
        buf = RedeliveryBuffer(max_size=2)
        buf.put("no-id-1")
        buf.put("no-id-2")
        buf.put("no-id-3")

        assert buf.drops == 1
        assert buf.pop_any() == "no-id-2"

    def test_size_tracking(self) -> None:
        """Size is accurate after put/check/pop_any."""
        buf = RedeliveryBuffer()
        assert buf.size == 0
        buf.put(Message(id="a"))
        assert buf.size == 1
        buf.check("a")
        assert buf.size == 0
        buf.put(Message(id="b"))
        buf.pop_any()
        assert buf.size == 0


class TestValidateResponse:
    """Tests for validate_response helper."""

    def test_passes_normal_message(self) -> None:
        """Normal message passes through."""
        msg = Message(payload="ok")
        assert validate_response(msg) is msg

    def test_raises_on_error(self) -> None:
        """Message with error raises ChannelError."""
        msg = Message(error="fail")
        with pytest.raises(ChannelError, match="fail"):
            validate_response(msg)


class TestQueueChannel:
    """Tests for Channel with QueueTransport."""

    def test_send_recv(self) -> None:
        """Basic send/recv works."""
        pair = QueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        parent.send(Request(id="1", data="hello"))
        msg = child.recv(timeout=1.0)

        assert isinstance(msg, Request)
        assert msg.id == "1"
        assert msg.data == "hello"

    def test_bidirectional(self) -> None:
        """Messages flow in both directions."""
        pair = QueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        # Parent to child
        parent.send(Request(id="1", data="ping"))
        assert child.recv(timeout=1.0).data == "ping"

        # Child to parent
        child.send(Response(id="1", result="pong"))
        assert parent.recv(timeout=1.0).result == "pong"

    def test_recv_timeout(self) -> None:
        """recv raises ChannelTimeoutError on timeout."""
        pair = QueueChannelFactory().create_pair()
        parent = pair.parent

        with pytest.raises(ChannelTimeoutError):
            parent.recv(timeout=0.1)

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

    def test_submit_timeout(self) -> None:
        """submit() raises ChannelTimeoutError if no response."""
        pair = QueueChannelFactory().create_pair()
        parent = pair.parent

        with pytest.raises(ChannelTimeoutError):
            parent.submit(Request(id="1", data="test"), timeout=0.1)

    def test_submit_requires_id(self) -> None:
        """submit() raises ValueError if request has no id."""
        pair = QueueChannelFactory().create_pair()
        parent = pair.parent

        with pytest.raises(ValueError, match="id"):
            parent.submit({"data": "no id"}, timeout=0.1)  # type: ignore

    def test_close_channel(self) -> None:
        """Closed channel raises ChannelClosedError on send."""
        pair = QueueChannelFactory().create_pair()
        parent = pair.parent

        parent.close()
        assert parent.is_closed

        with pytest.raises(ChannelClosedError):
            parent.send(Request(id="1", data="test"))

    def test_close_recv_drains(self) -> None:
        """Closed channel drains buffered messages before raising."""
        pair = QueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        parent.send(Request(id="1", data="msg1"))
        parent.send(Request(id="2", data="msg2"))

        # Close the CHILD channel (the one we'll recv on)
        child.close()

        # Should still get buffered messages from closed channel
        msg1 = child.recv(timeout=0.1)
        msg2 = child.recv(timeout=0.1)
        assert msg1.data == "msg1"
        assert msg2.data == "msg2"

        # Then raises ChannelClosedError (no more buffered messages)
        with pytest.raises(ChannelClosedError):
            child.recv(timeout=0.1)

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

        with pytest.raises(ChannelError, match="something failed"):
            parent.submit(Request(id="1", data="test"), timeout=1.0)

        t.join()


class TestQueueChannelFactory:
    """Tests for QueueChannelFactory."""

    def test_creates_connected_pair(self) -> None:
        """Creates two connected channels."""
        pair = QueueChannelFactory().create_pair()

        assert isinstance(pair.parent, Channel)
        assert isinstance(pair.child, Channel)

        pair.parent.send(Message(payload="test"))
        msg = pair.child.recv(timeout=0.1)
        assert msg.payload == "test"

    def test_custom_timeout(self) -> None:
        """Respects custom response timeout from config."""
        factory = QueueChannelFactory(ChannelConfig(response_timeout=0.05))
        pair = factory.create_pair()

        # submit uses the configured timeout
        with pytest.raises(ChannelTimeoutError):
            pair.parent.submit(Request(id="1", data="x"))  # No explicit timeout


class TestSubmitOnClosedChannel:
    """Tests for submit on closed channel."""

    def test_submit_on_closed_raises(self) -> None:
        """submit() raises ChannelClosedError on closed channel."""
        pair = QueueChannelFactory().create_pair()
        pair.parent.close()

        with pytest.raises(ChannelClosedError):
            pair.parent.submit(Request(id="1", data="test"), timeout=0.1)


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

    def test_recv_timeout(self) -> None:
        """recv raises ChannelTimeoutError on timeout."""
        pair = ProcessQueueChannelFactory().create_pair()

        with pytest.raises(ChannelTimeoutError):
            pair.parent.recv(timeout=0.1)

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

    def test_send_on_closed_raises(self) -> None:
        """send() raises ChannelClosedError on closed channel."""
        pair = ProcessQueueChannelFactory().create_pair()
        pair.parent.close()

        with pytest.raises(ChannelClosedError):
            pair.parent.send(Request(id="1", data="test"))

        pair.child.close()

    def test_recv_on_closed_raises(self) -> None:
        """recv() on closed channel raises ChannelClosedError."""
        pair = ProcessQueueChannelFactory().create_pair()

        try:
            # Channel.close() closes underlying mp.Queue, so recv raises
            pair.child.close()
            with pytest.raises(ChannelClosedError):
                pair.child.recv(timeout=0.1)
        finally:
            pair.parent.close()
