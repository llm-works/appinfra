"""Tests for IPCChannel."""

import asyncio
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


@dataclass
class MockResponse:
    """Mock response for testing."""

    id: str
    result: str
    error: str | None = None


@dataclass
class MockStreamChunk:
    """Mock stream chunk for testing."""

    id: str
    data: str
    is_final: bool = False


@pytest.mark.unit
class TestIPCChannel:
    """Tests for IPCChannel initialization and properties."""

    def test_initialization(self):
        """Test channel initialization."""
        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()
        config = IPCConfig(max_pending=50)

        channel = IPCChannel(request_q, response_q, config)

        assert channel.pending_count == 0
        assert channel.health_status["max_pending"] == 50

    def test_pending_count_empty(self):
        """Test pending_count with no pending requests."""
        channel = IPCChannel(mp.Queue(), mp.Queue(), IPCConfig())
        assert channel.pending_count == 0

    def test_health_status_healthy(self):
        """Test health_status when under capacity."""
        channel = IPCChannel(mp.Queue(), mp.Queue(), IPCConfig(max_pending=100))

        status = channel.health_status

        assert status["pending_requests"] == 0
        assert status["max_pending"] == 100
        assert status["is_healthy"] is True


@pytest.mark.unit
class TestIPCChannelSubmit:
    """Tests for IPCChannel submit method."""

    @pytest.mark.asyncio
    async def test_submit_exceeds_max_pending(self):
        """Test submit raises when max_pending exceeded."""
        channel = IPCChannel(mp.Queue(), mp.Queue(), IPCConfig(max_pending=0))

        with pytest.raises(RuntimeError, match="Max pending requests exceeded"):
            await channel.submit(MockRequest(id="req1", data="test"))

    @pytest.mark.asyncio
    async def test_submit_sends_to_queue(self):
        """Test submit puts request in request queue."""
        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()
        channel = IPCChannel(request_q, response_q, IPCConfig())

        request = MockRequest(id="req1", data="test")

        # Start submit but expect timeout since no response
        with pytest.raises(Exception):  # Will be ChannelTimeoutError or similar
            await channel.submit(request, timeout=0.05)

        # Verify request was sent
        sent = request_q.get_nowait()
        assert sent.id == "req1"
        assert sent.data == "test"

    @pytest.mark.asyncio
    async def test_submit_receives_response(self):
        """Test submit returns response when received."""
        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()
        channel = IPCChannel(request_q, response_q, IPCConfig())

        request = MockRequest(id="req1", data="test")

        # Simulate response arriving
        async def send_response():
            await asyncio.sleep(0.01)
            response_q.put(MockResponse(id="req1", result="success"))

        asyncio.create_task(send_response())

        result = await channel.submit(request, timeout=1.0)
        assert result.id == "req1"
        assert result.result == "success"

    @pytest.mark.asyncio
    async def test_submit_pending_count_tracks(self):
        """Test pending_count increments during submit and decrements after."""
        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()
        channel = IPCChannel(request_q, response_q, IPCConfig())

        request = MockRequest(id="req1", data="test")
        assert channel.pending_count == 0

        # Start submit task
        async def do_submit():
            try:
                await channel.submit(request, timeout=0.1)
            except Exception:
                pass

        task = asyncio.create_task(do_submit())
        await asyncio.sleep(0.01)

        # While submit is pending
        assert channel.pending_count == 1

        # Wait for timeout
        await task
        assert channel.pending_count == 0

    @pytest.mark.asyncio
    async def test_submit_requires_id_attribute(self):
        """Test submit raises if request has no id."""
        channel = IPCChannel(mp.Queue(), mp.Queue(), IPCConfig())

        with pytest.raises(ValueError, match="id"):
            await channel.submit({"no_id": True})


@pytest.mark.unit
class TestIPCChannelStreaming:
    """Tests for streaming functionality."""

    @pytest.mark.asyncio
    async def test_submit_stream_yields_chunks(self):
        """Test submit_stream yields chunks until is_final."""
        request_q: mp.Queue = mp.Queue()
        response_q: mp.Queue = mp.Queue()
        channel = IPCChannel(request_q, response_q, IPCConfig())

        request = MockRequest(id="stream1", data="test")

        # Simulate chunks arriving
        async def send_chunks():
            await asyncio.sleep(0.01)
            response_q.put(MockStreamChunk(id="stream1", data="chunk1", is_final=False))
            await asyncio.sleep(0.01)
            response_q.put(MockStreamChunk(id="stream1", data="chunk2", is_final=True))

        asyncio.create_task(send_chunks())

        chunks = []
        async for chunk in channel.submit_stream(request, timeout=1.0):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].data == "chunk1"
        assert chunks[1].data == "chunk2"
        assert chunks[1].is_final is True

    @pytest.mark.asyncio
    async def test_submit_stream_exceeds_max_pending(self):
        """Test submit_stream raises when max_pending exceeded."""
        channel = IPCChannel(mp.Queue(), mp.Queue(), IPCConfig(max_pending=0))

        with pytest.raises(RuntimeError, match="Max pending requests exceeded"):
            async for _ in channel.submit_stream(MockRequest(id="s1", data="test")):
                pass


@pytest.mark.unit
class TestIPCChannelLifecycle:
    """Tests for lifecycle methods."""

    @pytest.mark.asyncio
    async def test_start_polling_is_noop(self):
        """Test start_polling completes without error (no-op for this impl)."""
        channel = IPCChannel(mp.Queue(), mp.Queue(), IPCConfig())
        await channel.start_polling()
        # No error = success

    @pytest.mark.asyncio
    async def test_stop_polling_closes_channel(self):
        """Test stop_polling closes the underlying channel."""
        channel = IPCChannel(mp.Queue(), mp.Queue(), IPCConfig())
        await channel.start_polling()
        await channel.stop_polling()

        assert channel._closed is True

    @pytest.mark.asyncio
    async def test_stop_polling_idempotent(self):
        """Test stop_polling can be called multiple times."""
        channel = IPCChannel(mp.Queue(), mp.Queue(), IPCConfig())
        await channel.stop_polling()
        await channel.stop_polling()  # Should not error
