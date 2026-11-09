# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for IPCChannel submitting over multiprocessing queues, read on an executor
thread."""

import asyncio
import multiprocessing as mp

import pytest

from appinfra.app.fastapi.config.ipc import IPCConfig
from appinfra.app.fastapi.runtime.ipc import IPCChannel
from appinfra.service import ChannelTimeoutError
from tests.helpers.ipc import MockRequest, MockResponse, MockStreamChunk


@pytest.fixture
def queues():
    """Create and cleanup multiprocessing queues."""
    request_q: mp.Queue = mp.Queue()
    response_q: mp.Queue = mp.Queue()
    yield request_q, response_q
    request_q.close()
    response_q.close()
    request_q.join_thread()
    response_q.join_thread()


class TestIPCChannelSubmit:
    """Tests for IPCChannel submit method."""

    @pytest.mark.asyncio
    async def test_submit_sends_to_queue(self, queues):
        """Test submit puts request in request queue."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig())

        request = MockRequest(id="req1", data="test")

        # Start submit but expect timeout since no response
        with pytest.raises(ChannelTimeoutError):
            await channel.submit(request, timeout=0.05)

        # Verify request was sent
        sent = request_q.get_nowait()
        assert sent.id == "req1"
        assert sent.data == "test"

    @pytest.mark.asyncio
    async def test_submit_timeout_is_builtin_timeout_error(self, queues):
        """Test submit timeout is caught by a plain `except TimeoutError`."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig())

        with pytest.raises(TimeoutError):
            await channel.submit(MockRequest(id="req1", data="test"), timeout=0.05)

    @pytest.mark.asyncio
    async def test_submit_receives_response(self, queues):
        """Test submit returns response when received."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig())

        request = MockRequest(id="req1", data="test")

        # Simulate response arriving
        async def send_response():
            await asyncio.sleep(0.01)
            response_q.put(MockResponse(id="req1", result="success"))

        task = asyncio.create_task(send_response())

        result = await channel.submit(request, timeout=1.0)
        assert result.id == "req1"
        assert result.result == "success"

        # Ensure background task completed
        await task

    @pytest.mark.asyncio
    async def test_submit_pending_count_tracks(self, queues):
        """Test pending_count increments during submit and decrements after."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig())

        request = MockRequest(id="req1", data="test")
        assert channel.pending_count == 0

        # Use Event to synchronize instead of timing-based sleep
        started = asyncio.Event()

        async def do_submit():
            try:
                # Signal that submit is starting, then yield control
                started.set()
                await channel.submit(request, timeout=0.1)
            except Exception:
                pass

        task = asyncio.create_task(do_submit())
        await started.wait()
        # Yield to let submit increment pending_count
        await asyncio.sleep(0)

        # While submit is pending
        assert channel.pending_count == 1

        # Wait for timeout
        await task
        assert channel.pending_count == 0


class TestIPCChannelStreaming:
    """Tests for streaming functionality."""

    @pytest.mark.asyncio
    async def test_submit_stream_yields_chunks(self, queues):
        """Test submit_stream yields chunks until is_final."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig())

        request = MockRequest(id="stream1", data="test")

        # Simulate chunks arriving
        async def send_chunks():
            await asyncio.sleep(0.01)
            response_q.put(MockStreamChunk(id="stream1", data="chunk1", is_final=False))
            await asyncio.sleep(0.01)
            response_q.put(MockStreamChunk(id="stream1", data="chunk2", is_final=True))

        task = asyncio.create_task(send_chunks())

        chunks = [chunk async for chunk in channel.submit_stream(request, timeout=1.0)]

        assert len(chunks) == 2
        assert chunks[0].data == "chunk1"
        assert chunks[1].data == "chunk2"
        assert chunks[1].is_final is True

        # Ensure background task completed
        await task

    @pytest.mark.asyncio
    async def test_submit_stream_timeout_is_builtin_timeout_error(self, queues):
        """Test submit_stream timeout is caught by a plain `except TimeoutError`."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig())

        with pytest.raises(TimeoutError):
            async for _ in channel.submit_stream(
                MockRequest(id="s1", data="test"), timeout=0.05
            ):
                pass
