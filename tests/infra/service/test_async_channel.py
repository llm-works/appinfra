"""Tests for async service channel communication."""

import asyncio
from dataclasses import dataclass

import pytest

from appinfra.service import (
    AsyncThreadChannel,
    ChannelClosedError,
    ChannelConfig,
    ChannelError,
    ChannelFactory,
    ChannelTimeoutError,
    Message,
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


class TestAsyncThreadChannel:
    """Tests for AsyncThreadChannel."""

    @pytest.mark.asyncio
    async def test_send_recv(self) -> None:
        """Basic async send/recv works."""
        pair = ChannelFactory().create_async_thread_pair()
        parent, child = pair.parent, pair.child

        await parent.send(Request(id="1", data="hello"))
        msg = await child.recv(timeout=1.0)

        assert isinstance(msg, Request)
        assert msg.id == "1"
        assert msg.data == "hello"

    @pytest.mark.asyncio
    async def test_bidirectional(self) -> None:
        """Messages flow in both directions."""
        pair = ChannelFactory().create_async_thread_pair()
        parent, child = pair.parent, pair.child

        # Parent to child
        await parent.send(Request(id="1", data="ping"))
        msg = await child.recv(timeout=1.0)
        assert msg.data == "ping"

        # Child to parent
        await child.send(Response(id="1", result="pong"))
        resp = await parent.recv(timeout=1.0)
        assert resp.result == "pong"

    @pytest.mark.asyncio
    async def test_recv_timeout(self) -> None:
        """recv raises ChannelTimeoutError on timeout."""
        pair = ChannelFactory().create_async_thread_pair()

        with pytest.raises(ChannelTimeoutError):
            await pair.parent.recv(timeout=0.1)

    @pytest.mark.asyncio
    async def test_submit_request_response(self) -> None:
        """submit() sends request and waits for matching response."""
        pair = ChannelFactory().create_async_thread_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            await child.send(Response(id=req.id, result=f"got: {req.data}"))

        task = asyncio.create_task(responder())

        response = await parent.submit(Request(id="req-1", data="test"), timeout=1.0)

        await task
        assert response.id == "req-1"
        assert response.result == "got: test"

    @pytest.mark.asyncio
    async def test_submit_timeout(self) -> None:
        """submit() raises ChannelTimeoutError if no response."""
        pair = ChannelFactory().create_async_thread_pair()

        with pytest.raises(ChannelTimeoutError):
            await pair.parent.submit(Request(id="1", data="test"), timeout=0.1)

    @pytest.mark.asyncio
    async def test_submit_requires_id(self) -> None:
        """submit() raises ValueError if request has no id."""
        pair = ChannelFactory().create_async_thread_pair()

        with pytest.raises(ValueError, match="id"):
            await pair.parent.submit({"data": "no id"}, timeout=0.1)  # type: ignore

    @pytest.mark.asyncio
    async def test_close_channel(self) -> None:
        """Closed channel raises ChannelClosedError on send."""
        pair = ChannelFactory().create_async_thread_pair()

        await pair.parent.close()
        assert pair.parent.is_closed

        with pytest.raises(ChannelClosedError):
            await pair.parent.send(Request(id="1", data="test"))

    @pytest.mark.asyncio
    async def test_submit_on_closed_raises(self) -> None:
        """submit() raises ChannelClosedError on closed channel."""
        pair = ChannelFactory().create_async_thread_pair()
        await pair.parent.close()

        with pytest.raises(ChannelClosedError):
            await pair.parent.submit(Request(id="1", data="test"), timeout=0.1)

    @pytest.mark.asyncio
    async def test_concurrent_submits(self) -> None:
        """Multiple concurrent submits get correct responses."""
        pair = ChannelFactory().create_async_thread_pair()
        parent, child = pair.parent, pair.child
        results: dict[str, str] = {}

        async def responder() -> None:
            for _ in range(3):
                req = await child.recv(timeout=1.0)
                await child.send(Response(id=req.id, result=f"resp-{req.id}"))

        async def submitter(req_id: str) -> None:
            resp = await parent.submit(Request(id=req_id, data="x"), timeout=1.0)
            results[req_id] = resp.result

        resp_task = asyncio.create_task(responder())

        await asyncio.gather(
            submitter("req-0"),
            submitter("req-1"),
            submitter("req-2"),
        )
        await resp_task

        assert results == {
            "req-0": "resp-req-0",
            "req-1": "resp-req-1",
            "req-2": "resp-req-2",
        }

    @pytest.mark.asyncio
    async def test_response_with_error(self) -> None:
        """submit() raises ChannelError if response has error."""
        pair = ChannelFactory().create_async_thread_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            await child.send(Response(id=req.id, result="", error="something failed"))

        task = asyncio.create_task(responder())

        with pytest.raises(ChannelError, match="something failed"):
            await parent.submit(Request(id="1", data="test"), timeout=1.0)

        await task


class TestAsyncChannelFactory:
    """Tests for ChannelFactory async methods."""

    @pytest.mark.asyncio
    async def test_creates_connected_pair(self) -> None:
        """Creates two connected async channels."""
        pair = ChannelFactory().create_async_thread_pair()

        assert isinstance(pair.parent, AsyncThreadChannel)
        assert isinstance(pair.child, AsyncThreadChannel)

        await pair.parent.send(Message(payload="test"))
        msg = await pair.child.recv(timeout=0.1)
        assert msg.payload == "test"

    @pytest.mark.asyncio
    async def test_custom_timeout(self) -> None:
        """Respects custom response timeout."""
        factory = ChannelFactory(ChannelConfig(response_timeout=0.05))
        pair = factory.create_async_thread_pair()

        with pytest.raises(ChannelTimeoutError):
            await pair.parent.submit(Request(id="1", data="x"))

    @pytest.mark.asyncio
    async def test_async_channel_pair_close(self) -> None:
        """AsyncChannelPair.close() closes both channels."""
        pair = ChannelFactory().create_async_thread_pair()

        await pair.close()

        assert pair.parent.is_closed
        assert pair.child.is_closed

    @pytest.mark.asyncio
    async def test_async_thread_pair_with_max_queue_size(self) -> None:
        """Async thread pair respects max queue size."""
        config = ChannelConfig(max_queue_size=10)
        factory = ChannelFactory(config)
        pair = factory.create_async_thread_pair()

        assert pair.parent is not None
        assert pair.child is not None

    @pytest.mark.asyncio
    async def test_async_process_pair_with_max_queue_size(self) -> None:
        """Async process pair respects max queue size."""
        config = ChannelConfig(max_queue_size=10)
        factory = ChannelFactory(config)
        pair = factory.create_async_process_pair()

        assert pair.parent is not None
        assert pair.child is not None
        await pair.close()


class TestAsyncProcessChannel:
    """Tests for AsyncProcessChannel."""

    @pytest.mark.asyncio
    async def test_send_recv(self) -> None:
        """Basic async send/recv works with process channel."""
        pair = ChannelFactory().create_async_process_pair()
        parent, child = pair.parent, pair.child

        await parent.send(Request(id="1", data="hello"))
        # Child is sync ProcessChannel
        msg = child.recv(timeout=1.0)

        assert isinstance(msg, Request)
        assert msg.id == "1"
        assert msg.data == "hello"

        await pair.close()

    @pytest.mark.asyncio
    async def test_bidirectional(self) -> None:
        """Messages flow in both directions."""
        pair = ChannelFactory().create_async_process_pair()
        parent, child = pair.parent, pair.child

        # Parent (async) to child (sync)
        await parent.send(Request(id="1", data="ping"))
        msg = child.recv(timeout=1.0)
        assert msg.data == "ping"

        # Child (sync) to parent (async)
        child.send(Response(id="1", result="pong"))
        resp = await parent.recv(timeout=1.0)
        assert resp.result == "pong"

        await pair.close()

    @pytest.mark.asyncio
    async def test_recv_timeout(self) -> None:
        """recv raises ChannelTimeoutError on timeout."""
        pair = ChannelFactory().create_async_process_pair()

        with pytest.raises(ChannelTimeoutError):
            await pair.parent.recv(timeout=0.1)

        await pair.close()

    @pytest.mark.asyncio
    async def test_send_on_closed_raises(self) -> None:
        """send() raises ChannelClosedError on closed channel."""
        pair = ChannelFactory().create_async_process_pair()
        await pair.parent.close()

        with pytest.raises(ChannelClosedError):
            await pair.parent.send(Request(id="1", data="test"))

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        """close() closes the channel and underlying queues."""
        pair = ChannelFactory().create_async_process_pair()
        parent, child = pair.parent, pair.child

        # Use the channel
        await parent.send(Request(id="1", data="test"))
        msg = child.recv(timeout=1.0)
        assert msg.data == "test"

        # Close both
        await pair.close()

        assert parent.is_closed
        assert child.is_closed


class TestAsyncThreadChannelClosedDrain:
    """Tests for draining closed async channels."""

    @pytest.mark.asyncio
    async def test_recv_on_closed_drains(self) -> None:
        """recv() on closed AsyncThreadChannel drains buffered messages."""
        pair = ChannelFactory().create_async_thread_pair()
        parent, child = pair.parent, pair.child

        # Send a message then close child
        await parent.send(Request(id="1", data="buffered"))
        await child.close()

        # Should get the buffered message
        msg = await child.recv(timeout=0.1)
        assert msg.data == "buffered"

        # Then raises ChannelClosedError
        with pytest.raises(ChannelClosedError):
            await child.recv(timeout=0.1)


@dataclass
class StreamChunk:
    """Test streaming chunk message."""

    id: str
    data: str
    is_final: bool = False


class TestAsyncChannelStreaming:
    """Tests for streaming support in async channels."""

    @pytest.mark.asyncio
    async def test_submit_stream_basic(self) -> None:
        """submit_stream() yields chunks until is_final=True."""
        pair = ChannelFactory().create_async_thread_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            # Send 3 chunks, last one is final
            await child.send(StreamChunk(id=req.id, data="chunk1", is_final=False))
            await child.send(StreamChunk(id=req.id, data="chunk2", is_final=False))
            await child.send(StreamChunk(id=req.id, data="chunk3", is_final=True))

        task = asyncio.create_task(responder())

        chunks = []
        async for chunk in parent.submit_stream(
            Request(id="req-1", data="test"), timeout=1.0
        ):
            chunks.append(chunk.data)

        await task

        assert chunks == ["chunk1", "chunk2", "chunk3"]

    @pytest.mark.asyncio
    async def test_submit_stream_single_chunk(self) -> None:
        """submit_stream() works with single final chunk."""
        pair = ChannelFactory().create_async_thread_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            await child.send(StreamChunk(id=req.id, data="only", is_final=True))

        task = asyncio.create_task(responder())

        chunks = []
        async for chunk in parent.submit_stream(
            Request(id="req-1", data="test"), timeout=1.0
        ):
            chunks.append(chunk.data)

        await task

        assert chunks == ["only"]

    @pytest.mark.asyncio
    async def test_submit_stream_timeout(self) -> None:
        """submit_stream() raises ChannelTimeoutError if chunk not received."""
        pair = ChannelFactory().create_async_thread_pair()

        with pytest.raises(ChannelTimeoutError):
            async for _ in pair.parent.submit_stream(
                Request(id="1", data="test"), timeout=0.1
            ):
                pass

    @pytest.mark.asyncio
    async def test_submit_stream_requires_id(self) -> None:
        """submit_stream() raises ValueError if request has no id."""
        pair = ChannelFactory().create_async_thread_pair()

        with pytest.raises(ValueError, match="id"):
            async for _ in pair.parent.submit_stream({"data": "no id"}, timeout=0.1):  # type: ignore
                pass

    @pytest.mark.asyncio
    async def test_submit_stream_on_closed_raises(self) -> None:
        """submit_stream() raises ChannelClosedError on closed channel."""
        pair = ChannelFactory().create_async_thread_pair()
        await pair.parent.close()

        with pytest.raises(ChannelClosedError):
            async for _ in pair.parent.submit_stream(
                Request(id="1", data="test"), timeout=0.1
            ):
                pass

    @pytest.mark.asyncio
    async def test_submit_stream_with_error(self) -> None:
        """submit_stream() raises ChannelError if chunk has error."""
        pair = ChannelFactory().create_async_thread_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            await child.send(Response(id=req.id, result="", error="stream failed"))

        task = asyncio.create_task(responder())

        with pytest.raises(ChannelError, match="stream failed"):
            async for _ in parent.submit_stream(
                Request(id="1", data="test"), timeout=1.0
            ):
                pass

        await task

    @pytest.mark.asyncio
    async def test_submit_stream_default_is_final(self) -> None:
        """Response without is_final attribute defaults to True (single response)."""
        pair = ChannelFactory().create_async_thread_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            # Response has no is_final, should default to True
            await child.send(Response(id=req.id, result="done"))

        task = asyncio.create_task(responder())

        chunks = []
        async for chunk in parent.submit_stream(
            Request(id="req-1", data="test"), timeout=1.0
        ):
            chunks.append(chunk)

        await task

        assert len(chunks) == 1
        assert chunks[0].result == "done"
