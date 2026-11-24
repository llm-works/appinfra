# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for async service channel communication."""

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any

import pytest

from appinfra.service import (
    AsyncBufferedChannel,
    AsyncChannel,
    AsyncProcessQueueChannelFactory,
    AsyncQueueChannelFactory,
    ChannelClosedError,
    ChannelConfig,
    ChannelResponseError,
    ChannelTimeoutError,
    Message,
)
from tests.helpers.service.channel import Request, Response


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


class TestAsyncProcessChannel:
    """Tests for AsyncChannel (process transport)."""

    @pytest.mark.asyncio
    async def test_send_on_closed_raises(self) -> None:
        """send() raises ChannelClosedError on closed channel."""
        pair = AsyncProcessQueueChannelFactory().create_pair()
        await pair.parent.close()

        with pytest.raises(ChannelClosedError):
            await pair.parent.send(Request(id="1", data="test"))


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
    async def test_stream_basic(self) -> None:
        """stream() yields chunks until is_final=True."""
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
            async for chunk in parent.stream(
                Request(id="req-1", data="test"), timeout=1.0
            )
        ]

        await task

        assert chunks == ["chunk1", "chunk2", "chunk3"]

    @pytest.mark.asyncio
    async def test_stream_single_chunk(self) -> None:
        """stream() works with single final chunk."""
        pair = AsyncQueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            await child.send(StreamChunk(id=req.id, data="only", is_final=True))

        task = asyncio.create_task(responder())

        chunks = [
            chunk.data
            async for chunk in parent.stream(
                Request(id="req-1", data="test"), timeout=1.0
            )
        ]

        await task

        assert chunks == ["only"]

    @pytest.mark.asyncio
    async def test_stream_timeout(self) -> None:
        """stream() raises ChannelTimeoutError if chunk not received."""
        pair = AsyncQueueChannelFactory().create_pair()

        with pytest.raises(ChannelTimeoutError):
            async for _ in pair.parent.stream(
                Request(id="1", data="test"), timeout=0.1
            ):
                pass

    @pytest.mark.asyncio
    async def test_stream_requires_id(self) -> None:
        """stream() raises ValueError if request has no id."""
        pair = AsyncQueueChannelFactory().create_pair()

        with pytest.raises(ValueError, match="id"):
            async for _ in pair.parent.stream({"data": "no id"}, timeout=0.1):  # type: ignore
                pass

    @pytest.mark.asyncio
    async def test_stream_on_closed_raises(self) -> None:
        """stream() raises ChannelClosedError on closed channel."""
        pair = AsyncQueueChannelFactory().create_pair()
        await pair.parent.close()

        with pytest.raises(ChannelClosedError):
            async for _ in pair.parent.stream(
                Request(id="1", data="test"), timeout=0.1
            ):
                pass

    @pytest.mark.asyncio
    async def test_stream_with_error(self) -> None:
        """stream() raises ChannelError if chunk has error."""
        pair = AsyncQueueChannelFactory().create_pair()
        parent, child = pair.parent, pair.child

        async def responder() -> None:
            req = await child.recv(timeout=1.0)
            await child.send(Response(id=req.id, result="", error="stream failed"))

        task = asyncio.create_task(responder())

        with pytest.raises(ChannelResponseError, match="stream failed") as exc:
            async for _ in parent.stream(Request(id="1", data="test"), timeout=1.0):
                pass
        assert exc.value.response == Response(id="1", result="", error="stream failed")

        await task

    @pytest.mark.asyncio
    async def test_stream_default_is_final(self) -> None:
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
            async for chunk in parent.stream(
                Request(id="req-1", data="test"), timeout=1.0
            )
        ]

        await task

        assert len(chunks) == 1
        assert chunks[0].result == "done"

    @pytest.mark.asyncio
    async def test_a_chunk_another_task_buffers_keeps_its_place(self) -> None:
        """A chunk another task's submit() receives and buffers while the stream
        waits on the transport is yielded before the stream's next one."""
        transport = AsyncRaceTransport(
            Message(id="X", payload="X1", is_final=False),
            Message(id="X", payload="X2"),
            Message(id="Y", payload="Y"),
        )
        channel: AsyncBufferedChannel[Any, Any] = AsyncBufferedChannel(transport)
        channel._recv_lock = AsyncSignallingLock(transport)  # type: ignore[assignment]

        async def streamer() -> list[Any]:
            stream = channel.stream(Request(id="X", data="go"), 5.0)
            return [chunk.payload async for chunk in stream]

        chunks = asyncio.create_task(streamer(), name="streamer")
        await transport.wait("streamer-receiving")
        reply = asyncio.create_task(
            channel.submit(Request(id="Y", data="go"), 5.0), name="submitter"
        )

        assert await asyncio.wait_for(chunks, 5) == ["X1", "X2"]
        assert (await asyncio.wait_for(reply, 5)).payload == "Y"

    @pytest.mark.asyncio
    async def test_the_wait_for_the_lock_is_bounded_by_the_deadline(self) -> None:
        """submit() waits for the receive lock only until its deadline, then
        raises ChannelTimeoutError."""
        channel = AsyncQueueChannelFactory().create_pair().parent
        lock = AsyncBusyLock()
        channel._recv_lock = lock  # type: ignore[assignment]

        with pytest.raises(ChannelTimeoutError):
            await channel.submit(Request(id="1", data="go"), 5.0)

        assert lock.acquires == 1


class AsyncBusyLock:
    """An asyncio lock another task holds: acquire() raises the TimeoutError a
    deadline-bounded wait for it raises once the deadline passes."""

    def __init__(self) -> None:
        self.acquires = 0

    async def acquire(self) -> bool:
        self.acquires += 1
        raise TimeoutError

    def release(self) -> None:
        raise AssertionError("released a lock it did not hold")

    async def __aenter__(self) -> None:
        raise AssertionError("waited for the lock without a deadline")

    async def __aexit__(self, *exc: object) -> None:
        pass


class AsyncRaceTransport:
    """Async counterpart of the sync test's RaceTransport: the streamer's first
    receive waits until the submitter has buffered a message or waits for the
    receive lock; the submitter's later receives wait until the streamer has
    received. Waits are on events; their deadline is the failure path."""

    def __init__(self, *messages: Any) -> None:
        self.inbound = deque(messages)
        self.events: dict[str, asyncio.Event] = {}
        self.calls: dict[str, int] = {}
        self.is_closed = False

    def _event(self, name: str) -> asyncio.Event:
        return self.events.setdefault(name, asyncio.Event())

    def signal(self, name: str) -> None:
        self._event(name).set()

    async def wait(self, name: str) -> None:
        await asyncio.wait_for(self._event(name).wait(), 5)

    async def send(self, message: Any, timeout: float | None = None) -> None:
        pass

    async def recv(self, timeout: float | None = None) -> Any:
        task = asyncio.current_task()
        name = task.get_name() if task else ""
        n = self.calls[name] = self.calls.get(name, 0) + 1
        if name == "streamer" and n == 1:
            self.signal("streamer-receiving")
            await self.wait("submitter-progress")
        if name == "submitter" and n > 1:
            self.signal("submitter-progress")  # its first message is buffered
            await self.wait("streamer-received")
        if not self.inbound:
            raise ChannelTimeoutError("empty")
        message = self.inbound.popleft()
        if name == "streamer":
            self.signal("streamer-received")
        return message

    async def close(self) -> None:
        self.is_closed = True


class AsyncSignallingLock:
    """An asyncio lock that tells the transport when the submitter waits for it."""

    def __init__(self, transport: AsyncRaceTransport) -> None:
        self._lock = asyncio.Lock()
        self._transport = transport

    async def acquire(self) -> bool:
        # The streamer takes the lock first, uncontended, so a caller finding
        # it held is the submitter; no task name check, since wait_for() runs
        # this in a task of its own on Python 3.11
        if self._lock.locked():
            self._transport.signal("submitter-progress")
        return await self._lock.acquire()

    def release(self) -> None:
        self._lock.release()
