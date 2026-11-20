# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""An async channel over asyncio queues waits without polling, and close() wakes it."""

import asyncio
from typing import Any

import pytest

from appinfra.service import (
    AsyncBufferedChannel,
    AsyncQueueChannelFactory,
    AsyncQueueTransport,
    ChannelClosedError,
    ChannelConfig,
    Message,
)


class RecordingTransport(AsyncQueueTransport[Any, Any]):
    """Records the timeout of every recv()."""

    def __init__(
        self, outbound: asyncio.Queue[Any], inbound: asyncio.Queue[Any]
    ) -> None:
        super().__init__(outbound, inbound)
        self.timeouts: list[float | None] = []

    async def recv(self, timeout: float | None = None) -> Any:
        self.timeouts.append(timeout)
        return await super().recv(timeout)


async def _parked(task: asyncio.Task[Any]) -> None:
    """Let *task* run until it waits on something."""
    for _ in range(3):
        await asyncio.sleep(0)
    assert not task.done()


class TestAsyncQueueChannelWait:
    @pytest.mark.asyncio
    async def test_recv_waits_in_one_call_without_slices(self) -> None:
        """An idle recv() hands the transport its own timeout (None) once,
        instead of polling it in slices."""
        transport = RecordingTransport(asyncio.Queue(), asyncio.Queue())
        channel: AsyncBufferedChannel[Any, Any] = AsyncBufferedChannel(transport)
        recv = asyncio.create_task(channel.recv())
        await _parked(recv)

        await channel.close()

        with pytest.raises(ChannelClosedError):
            await asyncio.wait_for(recv, timeout=5.0)
        assert transport.timeouts == [None]

    @pytest.mark.asyncio
    async def test_close_wakes_every_parked_recv(self) -> None:
        pair = AsyncQueueChannelFactory().create_pair()
        first = asyncio.create_task(pair.child.recv())
        second = asyncio.create_task(pair.child.recv())
        await _parked(first)
        await _parked(second)

        await pair.child.close()

        for recv in (first, second):
            with pytest.raises(ChannelClosedError):
                await asyncio.wait_for(recv, timeout=5.0)

    @pytest.mark.asyncio
    async def test_recv_after_close_drains_then_raises(self) -> None:
        """Messages queued before close() are still received; then recv() raises."""
        pair = AsyncQueueChannelFactory().create_pair()
        await pair.parent.send(Message(payload=1))
        await pair.parent.send(Message(payload=2))
        await pair.child.close()

        assert (await pair.child.recv()).payload == 1
        assert (await pair.child.recv()).payload == 2
        with pytest.raises(ChannelClosedError):
            await asyncio.wait_for(pair.child.recv(), timeout=5.0)

    @pytest.mark.asyncio
    async def test_close_with_a_full_inbox_still_ends_recv(self) -> None:
        """A full inbox has no room to signal the close; recv() drains it and
        then raises instead of waiting."""
        pair = AsyncQueueChannelFactory(ChannelConfig(max_queue_size=1)).create_pair()
        await pair.parent.send(Message(payload=1))
        await pair.child.close()

        assert (await pair.child.recv()).payload == 1
        with pytest.raises(ChannelClosedError):
            await asyncio.wait_for(pair.child.recv(), timeout=5.0)

    @pytest.mark.asyncio
    async def test_closing_one_side_leaves_the_other_open(self) -> None:
        pair = AsyncQueueChannelFactory().create_pair()
        await pair.child.close()

        await pair.child.transport.send(Message(payload=7))  # still reaches the parent

        assert (await asyncio.wait_for(pair.parent.recv(), timeout=5.0)).payload == 7
