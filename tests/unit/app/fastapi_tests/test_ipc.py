# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""IPCChannel over a requests Chan in this process: a task on the same loop
plays the parent."""

import asyncio

import pytest

from appinfra.app.fastapi.config.ipc import IPCConfig
from appinfra.app.fastapi.runtime.ipc import IPCChannel
from appinfra.runtime import Chan
from appinfra.runtime.chan import ClosedError


def _channel(capacity: int = 1, **config: object) -> tuple[IPCChannel, Chan]:
    requests: Chan = Chan(capacity, process=True)
    return IPCChannel(requests, IPCConfig(**config)), requests  # type: ignore[arg-type]


class TestHealth:
    def test_an_idle_channel_reports_healthy(self) -> None:
        channel, _ = _channel(max_pending=50)
        assert channel.pending_count == 0
        assert channel.health_status == {
            "pending_requests": 0,
            "max_pending": 50,
            "is_healthy": True,
        }


class TestSubmit:
    @pytest.mark.asyncio
    async def test_the_reply_is_returned(self) -> None:
        channel, requests = _channel()

        async def parent() -> None:
            data, reply = await requests.arecv()
            await reply.asend(data * 2)

        answering = asyncio.create_task(parent())
        assert await channel.submit("ab", timeout=5.0) == "abab"
        await answering

    @pytest.mark.asyncio
    async def test_a_request_in_flight_is_counted(self) -> None:
        channel, requests = _channel()
        submitting = asyncio.create_task(channel.submit("x", timeout=5.0))
        _, reply = await requests.arecv()  # the request is out: it waits
        assert channel.pending_count == 1
        await reply.asend("done")
        assert await submitting == "done"
        assert channel.pending_count == 0

    @pytest.mark.asyncio
    async def test_a_request_over_max_pending_is_refused(self) -> None:
        channel, requests = _channel(max_pending=0)
        with pytest.raises(RuntimeError, match="Max pending requests exceeded"):
            await channel.submit("x")
        assert len(requests) == 0

    @pytest.mark.asyncio
    async def test_the_timeout_covers_sending_the_request(self) -> None:
        """Nobody receives and the Chan has no room: the send times out."""
        channel, _ = _channel(capacity=0)
        with pytest.raises(TimeoutError):
            await channel.submit("x", timeout=0)
        assert channel.pending_count == 0

    @pytest.mark.asyncio
    async def test_a_reply_after_a_timeout_is_refused(self) -> None:
        channel, requests = _channel()
        with pytest.raises(TimeoutError):
            await channel.submit("x", timeout=0)
        _, reply = await requests.arecv()
        with pytest.raises(ClosedError):
            await reply.asend("late")


class TestStream:
    @pytest.mark.asyncio
    async def test_values_until_the_reply_is_closed(self) -> None:
        channel, requests = _channel()

        async def parent() -> None:
            data, reply = await requests.arecv()
            for letter in data:
                await reply.asend(letter)
            reply.close()

        answering = asyncio.create_task(parent())
        assert [v async for v in channel.stream("abc", timeout=5.0)] == list("abc")
        await answering
        assert channel.pending_count == 0

    @pytest.mark.asyncio
    async def test_a_stream_over_max_pending_is_refused(self) -> None:
        channel, _ = _channel(max_pending=0)
        with pytest.raises(RuntimeError, match="Max pending requests exceeded"):
            async for _ in channel.stream("x"):
                pass

    @pytest.mark.asyncio
    async def test_a_stream_left_early_closes_its_reply(self) -> None:
        """The route stops reading: the parent's next value is refused."""
        channel, requests = _channel()
        stream = channel.stream("x", timeout=5.0)
        reading = asyncio.create_task(anext(stream))
        _, reply = await requests.arecv()
        await reply.asend("first")
        assert await reading == "first"
        await stream.aclose()
        with pytest.raises(ClosedError):
            await reply.asend("second")
        assert channel.pending_count == 0
