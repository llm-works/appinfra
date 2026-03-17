"""Tests for service channel communication."""

import threading
from dataclasses import dataclass

import pytest

from appinfra.service import (
    ChannelClosedError,
    ChannelConfig,
    ChannelFactory,
    ChannelTimeoutError,
    Message,
    ThreadChannel,
)


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


class TestThreadChannel:
    """Tests for ThreadChannel."""

    def test_send_recv(self) -> None:
        """Basic send/recv works."""
        pair = ChannelFactory().create_thread_pair()
        parent, child = pair.parent, pair.child

        parent.send(Request(id="1", data="hello"))
        msg = child.recv(timeout=1.0)

        assert isinstance(msg, Request)
        assert msg.id == "1"
        assert msg.data == "hello"

    def test_bidirectional(self) -> None:
        """Messages flow in both directions."""
        pair = ChannelFactory().create_thread_pair()
        parent, child = pair.parent, pair.child

        # Parent to child
        parent.send(Request(id="1", data="ping"))
        assert child.recv(timeout=1.0).data == "ping"

        # Child to parent
        child.send(Response(id="1", result="pong"))
        assert parent.recv(timeout=1.0).result == "pong"

    def test_recv_timeout(self) -> None:
        """recv raises ChannelTimeoutError on timeout."""
        pair = ChannelFactory().create_thread_pair()
        parent = pair.parent

        with pytest.raises(ChannelTimeoutError):
            parent.recv(timeout=0.1)

    def test_submit_request_response(self) -> None:
        """submit() sends request and waits for matching response."""
        pair = ChannelFactory().create_thread_pair()
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
        pair = ChannelFactory().create_thread_pair()
        parent = pair.parent

        with pytest.raises(ChannelTimeoutError):
            parent.submit(Request(id="1", data="test"), timeout=0.1)

    def test_submit_requires_id(self) -> None:
        """submit() raises ValueError if request has no id."""
        pair = ChannelFactory().create_thread_pair()
        parent = pair.parent

        with pytest.raises(ValueError, match="id"):
            parent.submit({"data": "no id"}, timeout=0.1)  # type: ignore

    def test_close_channel(self) -> None:
        """Closed channel raises ChannelClosedError on send."""
        pair = ChannelFactory().create_thread_pair()
        parent = pair.parent

        parent.close()
        assert parent.is_closed

        with pytest.raises(ChannelClosedError):
            parent.send(Request(id="1", data="test"))

    def test_close_recv_drains(self) -> None:
        """Closed channel drains buffered messages before raising."""
        pair = ChannelFactory().create_thread_pair()
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
        pair = ChannelFactory().create_thread_pair()
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
        from appinfra.service import ChannelError

        pair = ChannelFactory().create_thread_pair()
        parent, child = pair.parent, pair.child

        def responder() -> None:
            req = child.recv(timeout=1.0)
            child.send(Response(id=req.id, result="", error="something failed"))

        t = threading.Thread(target=responder)
        t.start()

        with pytest.raises(ChannelError, match="something failed"):
            parent.submit(Request(id="1", data="test"), timeout=1.0)

        t.join()


class TestChannelFactory:
    """Tests for ChannelFactory."""

    def test_creates_connected_pair(self) -> None:
        """Creates two connected channels."""
        pair = ChannelFactory().create_thread_pair()

        assert isinstance(pair.parent, ThreadChannel)
        assert isinstance(pair.child, ThreadChannel)

        pair.parent.send(Message(payload="test"))
        msg = pair.child.recv(timeout=0.1)
        assert msg.payload == "test"

    def test_custom_timeout(self) -> None:
        """Respects custom response timeout from config."""
        factory = ChannelFactory(ChannelConfig(response_timeout=0.05))
        pair = factory.create_thread_pair()

        # submit uses the configured timeout
        with pytest.raises(ChannelTimeoutError):
            pair.parent.submit(Request(id="1", data="x"))  # No explicit timeout


class TestSubmitOnClosedChannel:
    """Tests for submit on closed channel."""

    def test_submit_on_closed_raises(self) -> None:
        """submit() raises ChannelClosedError on closed channel."""
        pair = ChannelFactory().create_thread_pair()
        pair.parent.close()

        with pytest.raises(ChannelClosedError):
            pair.parent.submit(Request(id="1", data="test"), timeout=0.1)


class TestProcessChannel:
    """Tests for ProcessChannel."""

    def test_send_recv(self) -> None:
        """Basic send/recv works."""
        pair = ChannelFactory().create_process_pair()
        parent, child = pair.parent, pair.child

        parent.send(Request(id="1", data="hello"))
        msg = child.recv(timeout=1.0)

        assert isinstance(msg, Request)
        assert msg.id == "1"
        assert msg.data == "hello"

        pair.close()

    def test_recv_timeout(self) -> None:
        """recv raises ChannelTimeoutError on timeout."""
        pair = ChannelFactory().create_process_pair()

        with pytest.raises(ChannelTimeoutError):
            pair.parent.recv(timeout=0.1)

        pair.close()

    def test_close_channel(self) -> None:
        """Closing ProcessChannel closes underlying queues."""
        pair = ChannelFactory().create_process_pair()
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
        pair = ChannelFactory().create_process_pair()
        pair.parent.close()

        with pytest.raises(ChannelClosedError):
            pair.parent.send(Request(id="1", data="test"))

    def test_recv_on_closed_raises(self) -> None:
        """recv() on closed ProcessChannel raises ChannelClosedError."""
        pair = ChannelFactory().create_process_pair()
        pair.child.close()

        # ProcessChannel.close() closes underlying mp.Queue, so recv raises
        with pytest.raises(ChannelClosedError):
            pair.child.recv(timeout=0.1)
