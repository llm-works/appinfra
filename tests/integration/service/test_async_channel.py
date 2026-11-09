# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for async service channels over a process queue, which runs a feeder thread."""

import asyncio
import threading
from dataclasses import dataclass

import pytest

from appinfra.service import (
    AsyncProcessQueueChannelFactory,
    Channel,
    ChannelClosedError,
    ChannelTimeoutError,
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
