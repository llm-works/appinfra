# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for send() on a full bounded channel: timeout, close and submit."""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from dataclasses import dataclass
from typing import Any

import pytest

from appinfra.service import (
    AsyncProcessQueueChannelFactory,
    AsyncQueueChannelFactory,
    ChannelClosedError,
    ChannelConfig,
    ChannelFullError,
    ProcessQueueChannelFactory,
    QueueChannelFactory,
)

FULL = ChannelConfig(max_queue_size=1)


@dataclass
class Request:
    """Request message."""

    id: str


SYNC_FACTORIES = [QueueChannelFactory, ProcessQueueChannelFactory]
ASYNC_FACTORIES = [AsyncQueueChannelFactory, AsyncProcessQueueChannelFactory]


@pytest.mark.parametrize("factory", SYNC_FACTORIES)
class TestSyncSendOnFullChannel:
    """BufferedChannel.send() over a full queue.Queue / mp.Queue."""

    def test_timeout_zero_raises_full(self, factory: Any) -> None:
        pair = factory(FULL).create_pair()
        pair.parent.send(Request("1"))

        with pytest.raises(ChannelFullError):
            pair.parent.send(Request("2"), timeout=0)
        pair.close()

    def test_timeout_raises_full_after_timeout(self, factory: Any) -> None:
        pair = factory(FULL).create_pair()
        pair.parent.send(Request("1"))

        started = time.monotonic()
        with pytest.raises(ChannelFullError):
            pair.parent.send(Request("2"), timeout=0.3)
        assert 0.3 <= time.monotonic() - started < 1.0
        pair.close()

    def test_close_interrupts_blocked_send(self, factory: Any) -> None:
        pair = factory(FULL).create_pair()
        pair.parent.send(Request("1"))
        threading.Timer(0.2, pair.parent.close).start()

        started = time.monotonic()
        with pytest.raises(ChannelClosedError):
            pair.parent.send(Request("2"))
        assert time.monotonic() - started < 1.0
        pair.child.close()

    def test_send_completes_when_room_frees(self, factory: Any) -> None:
        pair = factory(FULL).create_pair()
        pair.parent.send(Request("1"))
        threading.Timer(0.2, lambda: pair.child.recv(timeout=1.0)).start()

        pair.parent.send(Request("2"), timeout=2.0)

        assert pair.child.recv(timeout=1.0).id == "2"
        pair.close()

    def test_submit_counts_send_wait_against_timeout(self, factory: Any) -> None:
        pair = factory(FULL).create_pair()
        pair.parent.send(Request("1"))

        started = time.monotonic()
        with pytest.raises(ChannelFullError):
            pair.parent.submit(Request("2"), timeout=0.3)
        assert time.monotonic() - started < 1.0
        pair.close()


async def _recv(channel: Any, timeout: float) -> Any:
    """recv() on either side of a pair; the process pair's child is sync."""
    result = channel.recv(timeout=timeout)
    return await result if inspect.isawaitable(result) else result


async def _close(channel: Any) -> None:
    result = channel.close()
    if inspect.isawaitable(result):
        await result


@pytest.mark.parametrize("factory", ASYNC_FACTORIES)
class TestAsyncSendOnFullChannel:
    """AsyncBufferedChannel.send() over a full asyncio.Queue / mp.Queue."""

    @pytest.mark.asyncio
    async def test_timeout_zero_raises_full(self, factory: Any) -> None:
        pair = factory(FULL).create_pair()
        await pair.parent.send(Request("1"))

        with pytest.raises(ChannelFullError):
            await pair.parent.send(Request("2"), timeout=0)
        await pair.close()

    @pytest.mark.asyncio
    async def test_timeout_raises_full_after_timeout(self, factory: Any) -> None:
        pair = factory(FULL).create_pair()
        await pair.parent.send(Request("1"))

        started = time.monotonic()
        with pytest.raises(ChannelFullError):
            await pair.parent.send(Request("2"), timeout=0.3)
        assert 0.3 <= time.monotonic() - started < 1.0
        await pair.close()

    @pytest.mark.asyncio
    async def test_close_interrupts_blocked_send(self, factory: Any) -> None:
        pair = factory(FULL).create_pair()
        await pair.parent.send(Request("1"))
        blocked = asyncio.create_task(pair.parent.send(Request("2")))
        await asyncio.sleep(0.2)

        started = time.monotonic()
        await pair.parent.close()
        with pytest.raises(ChannelClosedError):
            await blocked
        assert time.monotonic() - started < 1.0
        await _close(pair.child)

    @pytest.mark.asyncio
    async def test_send_completes_when_room_frees(self, factory: Any) -> None:
        pair = factory(FULL).create_pair()
        await pair.parent.send(Request("1"))
        pending = asyncio.create_task(pair.parent.send(Request("2"), timeout=2.0))
        await asyncio.sleep(0.2)

        assert (await _recv(pair.child, 1.0)).id == "1"
        await pending
        assert (await _recv(pair.child, 1.0)).id == "2"
        await pair.close()

    @pytest.mark.asyncio
    async def test_submit_counts_send_wait_against_timeout(self, factory: Any) -> None:
        pair = factory(FULL).create_pair()
        await pair.parent.send(Request("1"))

        started = time.monotonic()
        with pytest.raises(ChannelFullError):
            await pair.parent.submit(Request("2"), timeout=0.3)
        assert time.monotonic() - started < 1.0
        await pair.close()
