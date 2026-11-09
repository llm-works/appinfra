# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for IPCChannel."""

import multiprocessing as mp
from dataclasses import dataclass

import pytest

from appinfra.app.fastapi.config.ipc import IPCConfig
from appinfra.app.fastapi.runtime.ipc import IPCChannel


@dataclass
class MockRequest:
    """Mock request for testing."""

    id: str
    data: str


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


class TestIPCChannel:
    """Tests for IPCChannel initialization and properties."""

    def test_initialization(self, queues):
        """Test channel initialization."""
        request_q, response_q = queues
        config = IPCConfig(max_pending=50)

        channel = IPCChannel(request_q, response_q, config)

        assert channel.pending_count == 0
        assert channel.health_status["max_pending"] == 50

    def test_pending_count_empty(self, queues):
        """Test pending_count with no pending requests."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig())
        assert channel.pending_count == 0

    def test_health_status_healthy(self, queues):
        """Test health_status when under capacity."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig(max_pending=100))

        status = channel.health_status

        assert status["pending_requests"] == 0
        assert status["max_pending"] == 100
        assert status["is_healthy"] is True


class TestIPCChannelSubmit:
    """Tests for IPCChannel submit method."""

    @pytest.mark.asyncio
    async def test_submit_exceeds_max_pending(self, queues):
        """Test submit raises when max_pending exceeded."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig(max_pending=0))

        with pytest.raises(RuntimeError, match="Max pending requests exceeded"):
            await channel.submit(MockRequest(id="req1", data="test"))

    @pytest.mark.asyncio
    async def test_submit_requires_id_attribute(self, queues):
        """Test submit raises if request has no id."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig())

        with pytest.raises(ValueError, match="id"):
            await channel.submit({"no_id": True})


class TestIPCChannelStreaming:
    """Tests for streaming functionality."""

    @pytest.mark.asyncio
    async def test_submit_stream_exceeds_max_pending(self, queues):
        """Test submit_stream raises when max_pending exceeded."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig(max_pending=0))

        with pytest.raises(RuntimeError, match="Max pending requests exceeded"):
            async for _ in channel.submit_stream(MockRequest(id="s1", data="test")):
                pass


class TestIPCChannelLifecycle:
    """Tests for lifecycle methods."""

    @pytest.mark.asyncio
    async def test_start_polling_is_noop(self, queues):
        """Test start_polling completes without error (no-op for this impl)."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig())
        await channel.start_polling()
        # No error = success

    @pytest.mark.asyncio
    async def test_stop_polling_closes_channel(self, queues):
        """Test stop_polling closes the underlying channel."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig())
        await channel.start_polling()
        await channel.stop_polling()

        assert channel._closed is True

    @pytest.mark.asyncio
    async def test_stop_polling_idempotent(self, queues):
        """Test stop_polling can be called multiple times."""
        request_q, response_q = queues
        channel = IPCChannel(request_q, response_q, IPCConfig())
        await channel.stop_polling()
        await channel.stop_polling()  # Should not error
