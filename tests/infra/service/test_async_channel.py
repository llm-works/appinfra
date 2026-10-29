# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for async service channel communication."""

import asyncio
import threading
from dataclasses import dataclass

import pytest

from appinfra.service import (
    AsyncChannel,
    AsyncProcessQueueChannelFactory,
    AsyncQueueChannelFactory,
    Channel,
    ChannelClosedError,
    ChannelConfig,
    ChannelResponseError,
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
    """Tests for AsyncChannel (queue transport)."""

    @pytest.mark.asyncio
    async def test_send_recv(self) -> None:
        """Basic async send/recv works."""
        pair = AsyncQueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        await parent.send(Request(id="1", data="hello"))
        msg = await child.recv(timeout=1.0)

        assert isinstance(msg, Request)
        assert msg.id == "1"
        assert msg.data == "hello"

    @pytest.mark.asyncio
    async def test_bidirectional(self) -> None:
        """Messages flow in both directions."""
        pair = AsyncQueueChannelFactory().create_pair()
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
        pair = AsyncQueueChannelFactory().create_pair()

        with pytest.raises(ChannelTimeoutError):
            await pair.parent.recv(timeout=0.1)

    @pytest.mark.asyncio
    async def test_submit_request_response(self) -> None:
        """submit() sends request and waits for matching response."""
        pair = AsyncQueueChannelFactory().create_pair()
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
        pair = AsyncQueueChannelFactory().create_pair()

        with pytest.raises(ChannelTimeoutError):
            await pair.parent.submit(Request(id="1", data="test"), timeout=0.1)

    @pytest.mark.asyncio
    async def test_submit_requires_id(self) -> None:
        """submit() raises ValueError if request has no id."""
        pair = AsyncQueueChannelFactory().create_pair()

        with pytest.raises(ValueError, match="id"):
            await pair.parent.submit({"data": "no id"}, timeout=0.1)  # type: ignore

    @pytest.mark.asyncio
    async def test_close_channel(self) -> None:
        """Closed channel raises ChannelClosedError on send."""
        pair = AsyncQueueChannelFactory().create_pair()

        await pair.parent.close()
        assert pair.parent.is_closed

        with pytest.raises(ChannelClosedError):
            await pair.parent.send(Request(id="1", data="test"))

    @pytest.mark.asyncio
    async def test_submit_on_closed_raises(self) -> None:
        """submit() raises ChannelClosedError on closed channel."""
        pair = AsyncQueueChannelFactory().create_pair()
        await pair.parent.close()

        with pytest.raises(ChannelClosedError):
            await pair.parent.submit(Request(id="1", data="test"), timeout=0.1)

    @pytest.mark.asyncio
    async def test_concurrent_submits(self) -> None:
        """Multiple concurrent submits get correct responses."""
        pair = AsyncQueueChannelFactory().create_pair()
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
        pair = AsyncQueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            await child.send(Response(id=req.id, result="", error="something failed"))

        task = asyncio.create_task(responder())

        with pytest.raises(ChannelResponseError, match="something failed") as exc:
            await parent.submit(Request(id="1", data="test"), timeout=1.0)
        assert exc.value.response == Response(
            id="1", result="", error="something failed"
        )

        await task


class TestAsyncQueueChannelFactory:
    """Tests for AsyncQueueChannelFactory."""

    @pytest.mark.asyncio
    async def test_creates_connected_pair(self) -> None:
        """Creates two connected async channels."""
        pair = AsyncQueueChannelFactory().create_pair()

        assert isinstance(pair.parent, AsyncChannel)
        assert isinstance(pair.child, AsyncChannel)

        await pair.parent.send(Message(payload="test"))
        msg = await pair.child.recv(timeout=0.1)
        assert msg.payload == "test"

    @pytest.mark.asyncio
    async def test_custom_timeout(self) -> None:
        """Respects custom response timeout."""
        factory = AsyncQueueChannelFactory(ChannelConfig(response_timeout=0.05))
        pair = factory.create_pair()

        with pytest.raises(ChannelTimeoutError):
            await pair.parent.submit(Request(id="1", data="x"))

    @pytest.mark.asyncio
    async def test_async_channel_pair_close(self) -> None:
        """AsyncChannelPair.close() closes both channels."""
        pair = AsyncQueueChannelFactory().create_pair()

        await pair.close()

        assert pair.parent.is_closed
        assert pair.child.is_closed

    @pytest.mark.asyncio
    async def test_async_thread_pair_with_max_queue_size(self) -> None:
        """Async thread pair respects max queue size."""
        config = ChannelConfig(max_queue_size=10)
        factory = AsyncQueueChannelFactory(config)
        pair = factory.create_pair()

        assert pair.parent is not None
        assert pair.child is not None

    @pytest.mark.asyncio
    async def test_async_process_pair_with_max_queue_size(self) -> None:
        """Async process pair respects max queue size."""
        config = ChannelConfig(max_queue_size=10)
        factory = AsyncProcessQueueChannelFactory(config)
        pair = factory.create_pair()

        assert pair.parent is not None
        assert pair.child is not None
        await pair.close()


def _consume_without_reply(channel: Channel, count: int) -> asyncio.Future[None]:
    """Read *count* messages from *channel* on a thread and never answer them.

    A process exits only after its queue's feeder has written everything it put into the
    pipe; with more unread requests than the pipe holds, the test's process never exits.
    """
    loop = asyncio.get_running_loop()
    done: asyncio.Future[None] = loop.create_future()

    def consume() -> None:
        try:
            for _ in range(count):
                channel.recv(timeout=10.0)
        except BaseException as e:
            loop.call_soon_threadsafe(done.set_exception, e)
        else:
            loop.call_soon_threadsafe(done.set_result, None)

    threading.Thread(target=consume, daemon=True).start()
    return done


class TestAsyncProcessChannel:
    """Tests for AsyncChannel (process transport)."""

    @pytest.mark.asyncio
    async def test_send_recv(self) -> None:
        """Basic async send/recv works with process channel."""
        pair = AsyncProcessQueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        await parent.send(Request(id="1", data="hello"))
        # Child is sync Channel
        msg = child.recv(timeout=1.0)

        assert isinstance(msg, Request)
        assert msg.id == "1"
        assert msg.data == "hello"

        await pair.close()

    @pytest.mark.asyncio
    async def test_bidirectional(self) -> None:
        """Messages flow in both directions."""
        pair = AsyncProcessQueueChannelFactory().create_pair()
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
        pair = AsyncProcessQueueChannelFactory().create_pair()

        with pytest.raises(ChannelTimeoutError):
            await pair.parent.recv(timeout=0.1)

        await pair.close()

    @pytest.mark.asyncio
    async def test_send_on_closed_raises(self) -> None:
        """send() raises ChannelClosedError on closed channel."""
        pair = AsyncProcessQueueChannelFactory().create_pair()
        await pair.parent.close()

        with pytest.raises(ChannelClosedError):
            await pair.parent.send(Request(id="1", data="test"))

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        """close() closes the channel and underlying queues."""
        pair = AsyncProcessQueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        # Use the channel
        await parent.send(Request(id="1", data="test"))
        msg = child.recv(timeout=1.0)
        assert msg.data == "test"

        # Close both
        await pair.close()

        assert parent.is_closed
        assert child.is_closed

    @pytest.mark.asyncio
    async def test_close_fails_pending_submits_with_closed_error(self) -> None:
        """Every submit pending at close() raises ChannelClosedError.

        More submits than executor threads leaves recv calls queued in the
        executor, so they reach mp.Queue.get() only after close().
        """
        pair = AsyncProcessQueueChannelFactory().create_pair()
        consumed = _consume_without_reply(pair.child, 100)
        tasks = [
            asyncio.create_task(
                pair.parent.submit(Request(id=str(i), data="x"), timeout=30.0)
            )
            for i in range(100)
        ]
        await asyncio.sleep(0.3)
        await asyncio.wait_for(consumed, timeout=10.0)

        await pair.parent.close()
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert {type(r) for r in results} == {ChannelClosedError}
        pair.child.close()

    @pytest.mark.asyncio
    async def test_close_fails_queued_sends_with_closed_error(self) -> None:
        """A send still queued in the executor at close() raises ChannelClosedError."""
        pair = AsyncProcessQueueChannelFactory().create_pair()
        consumed = _consume_without_reply(pair.child, 100)
        submits = [
            asyncio.create_task(
                pair.parent.submit(Request(id=str(i), data="x"), timeout=30.0)
            )
            for i in range(100)
        ]
        await asyncio.sleep(0.3)  # executor is now busy with recv polls
        await asyncio.wait_for(consumed, timeout=10.0)

        sends = [
            asyncio.create_task(pair.parent.send(Request(id=f"s{i}", data="x")))
            for i in range(10)
        ]
        await asyncio.sleep(0)  # sends reach the executor queue
        await pair.parent.close()
        results = await asyncio.gather(*sends, *submits, return_exceptions=True)

        assert {type(r) for r in results} == {ChannelClosedError}
        pair.child.close()


class TestAsyncThreadChannelClosedDrain:
    """Tests for draining closed async channels."""

    @pytest.mark.asyncio
    async def test_recv_on_closed_drains(self) -> None:
        """recv() on closed AsyncChannel drains buffered messages."""
        pair = AsyncQueueChannelFactory().create_pair()
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
        pair = AsyncQueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            # Send 3 chunks, last one is final
            await child.send(StreamChunk(id=req.id, data="chunk1", is_final=False))
            await child.send(StreamChunk(id=req.id, data="chunk2", is_final=False))
            await child.send(StreamChunk(id=req.id, data="chunk3", is_final=True))

        task = asyncio.create_task(responder())

        chunks = [
            chunk.data
            async for chunk in parent.submit_stream(
                Request(id="req-1", data="test"), timeout=1.0
            )
        ]

        await task

        assert chunks == ["chunk1", "chunk2", "chunk3"]

    @pytest.mark.asyncio
    async def test_submit_stream_single_chunk(self) -> None:
        """submit_stream() works with single final chunk."""
        pair = AsyncQueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            await child.send(StreamChunk(id=req.id, data="only", is_final=True))

        task = asyncio.create_task(responder())

        chunks = [
            chunk.data
            async for chunk in parent.submit_stream(
                Request(id="req-1", data="test"), timeout=1.0
            )
        ]

        await task

        assert chunks == ["only"]

    @pytest.mark.asyncio
    async def test_submit_stream_timeout(self) -> None:
        """submit_stream() raises ChannelTimeoutError if chunk not received."""
        pair = AsyncQueueChannelFactory().create_pair()

        with pytest.raises(ChannelTimeoutError):
            async for _ in pair.parent.submit_stream(
                Request(id="1", data="test"), timeout=0.1
            ):
                pass

    @pytest.mark.asyncio
    async def test_submit_stream_requires_id(self) -> None:
        """submit_stream() raises ValueError if request has no id."""
        pair = AsyncQueueChannelFactory().create_pair()

        with pytest.raises(ValueError, match="id"):
            async for _ in pair.parent.submit_stream({"data": "no id"}, timeout=0.1):  # type: ignore
                pass

    @pytest.mark.asyncio
    async def test_submit_stream_on_closed_raises(self) -> None:
        """submit_stream() raises ChannelClosedError on closed channel."""
        pair = AsyncQueueChannelFactory().create_pair()
        await pair.parent.close()

        with pytest.raises(ChannelClosedError):
            async for _ in pair.parent.submit_stream(
                Request(id="1", data="test"), timeout=0.1
            ):
                pass

    @pytest.mark.asyncio
    async def test_submit_stream_with_error(self) -> None:
        """submit_stream() raises ChannelError if chunk has error."""
        pair = AsyncQueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            await child.send(Response(id=req.id, result="", error="stream failed"))

        task = asyncio.create_task(responder())

        with pytest.raises(ChannelResponseError, match="stream failed") as exc:
            async for _ in parent.submit_stream(
                Request(id="1", data="test"), timeout=1.0
            ):
                pass
        assert exc.value.response == Response(id="1", result="", error="stream failed")

        await task

    @pytest.mark.asyncio
    async def test_submit_stream_default_is_final(self) -> None:
        """Response without is_final attribute defaults to True (single response)."""
        pair = AsyncQueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            # Response has no is_final, should default to True
            await child.send(Response(id=req.id, result="done"))

        task = asyncio.create_task(responder())

        chunks = [
            chunk
            async for chunk in parent.submit_stream(
                Request(id="req-1", data="test"), timeout=1.0
            )
        ]

        await task

        assert len(chunks) == 1
        assert chunks[0].result == "done"
