# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for service channels with a peer on another thread."""

import threading
from dataclasses import dataclass

import pytest

from appinfra.service import (
    ChannelClosedError,
    ChannelResponseError,
    ProcessQueueChannelFactory,
    QueueChannelFactory,
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
