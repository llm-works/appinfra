# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for ChannelResponseError: the error response is kept on the exception."""

from __future__ import annotations

import asyncio
import inspect
import threading
from dataclasses import dataclass
from typing import Any

import pytest

from appinfra.service import (
    AsyncProcessQueueChannelFactory,
    AsyncQueueChannelFactory,
    ChannelError,
    ChannelResponseError,
    Message,
    ProcessQueueChannelFactory,
    QueueChannelFactory,
)
from appinfra.service.channel.base import validate_response


@dataclass
class Request:
    """Request message."""

    id: str


@dataclass
class Response:
    """Response message with a field beyond the error text."""

    id: str
    status: str = "ok"
    error: str | None = None
    is_final: bool = True


SYNC_FACTORIES = [QueueChannelFactory, ProcessQueueChannelFactory]
ASYNC_FACTORIES = [AsyncQueueChannelFactory, AsyncProcessQueueChannelFactory]


@pytest.mark.unit
class TestValidateResponse:
    """validate_response() raises ChannelResponseError carrying the message."""

    def test_raises_with_response(self) -> None:
        msg = Message(error="fail")

        with pytest.raises(ChannelResponseError, match="Request failed: fail") as exc:
            validate_response(msg)

        assert exc.value.response is msg

    def test_is_channel_error(self) -> None:
        with pytest.raises(ChannelError):
            validate_response(Message(error="fail"))


@pytest.mark.unit
@pytest.mark.parametrize("factory", SYNC_FACTORIES)
class TestSyncSubmit:
    """BufferedChannel.submit() over queue.Queue / mp.Queue."""

    def test_error_response_is_attached(self, factory: Any) -> None:
        pair = factory().create_pair()

        def responder() -> None:
            req = pair.child.recv(timeout=1.0)
            pair.child.send(Response(id=req.id, status="rejected", error="busy"))

        thread = threading.Thread(target=responder)
        thread.start()

        with pytest.raises(ChannelResponseError, match="busy") as exc:
            pair.parent.submit(Request("1"), timeout=2.0)

        thread.join()
        assert exc.value.response == Response(id="1", status="rejected", error="busy")
        pair.close()


async def _recv(channel: Any) -> Any:
    """recv() on either child; the process pair's child is sync."""
    result = channel.recv(timeout=1.0)
    return await result if inspect.isawaitable(result) else result


async def _send(channel: Any, message: Any) -> None:
    result = channel.send(message)
    if inspect.isawaitable(result):
        await result


@pytest.mark.unit
@pytest.mark.parametrize("factory", ASYNC_FACTORIES)
class TestAsyncSubmit:
    """AsyncBufferedChannel.submit() and submit_stream()."""

    @pytest.mark.asyncio
    async def test_error_response_is_attached(self, factory: Any) -> None:
        pair = factory().create_pair()
        pending = asyncio.create_task(pair.parent.submit(Request("1"), timeout=2.0))
        await asyncio.sleep(0.1)  # let submit() send the request

        req = await _recv(pair.child)
        await _send(pair.child, Response(id=req.id, status="rejected", error="busy"))

        with pytest.raises(ChannelResponseError, match="busy") as exc:
            await pending
        assert exc.value.response == Response(id="1", status="rejected", error="busy")
        await pair.close()

    @pytest.mark.asyncio
    async def test_error_chunk_mid_stream_is_attached(self, factory: Any) -> None:
        pair = factory().create_pair()
        chunks: list[Response] = []

        async def consume() -> None:
            async for chunk in pair.parent.submit_stream(Request("1"), timeout=2.0):
                chunks.append(chunk)

        pending = asyncio.create_task(consume())
        await asyncio.sleep(0.1)  # let submit_stream() send the request

        req = await _recv(pair.child)
        await _send(pair.child, Response(id=req.id, is_final=False))
        failed = Response(id=req.id, status="failed", error="lost", is_final=False)
        await _send(pair.child, failed)

        with pytest.raises(ChannelResponseError, match="lost") as exc:
            await pending
        assert chunks == [Response(id="1", is_final=False)]
        assert exc.value.response == failed
        await pair.close()
