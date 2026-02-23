"""Tests for IPCChannel."""

import asyncio
from dataclasses import dataclass
from queue import Empty
from unittest.mock import AsyncMock, MagicMock, patch

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
        request_q = MagicMock()
        response_q = MagicMock()
        config = IPCConfig(max_pending=50)

        channel = IPCChannel(request_q, response_q, config)

        assert channel.request_q is request_q
        assert channel.response_q is response_q
        assert channel.config is config
        assert channel.pending == {}
        assert channel.pending_streams == {}
        assert channel._poll_task is None

    def test_pending_count_empty(self):
        """Test pending_count with no pending requests."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())
        assert channel.pending_count == 0

    def test_pending_count_with_requests(self):
        """Test pending_count with pending requests."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())
        channel.pending["req1"] = MagicMock()
        channel.pending["req2"] = MagicMock()
        channel.pending_streams["stream1"] = MagicMock()

        assert channel.pending_count == 3

    def test_health_status_healthy(self):
        """Test health_status when under capacity."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig(max_pending=100))
        channel.pending["req1"] = MagicMock()

        status = channel.health_status

        assert status["pending_requests"] == 1
        assert status["max_pending"] == 100
        assert status["is_healthy"] is True

    def test_health_status_unhealthy(self):
        """Test health_status when at capacity."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig(max_pending=2))
        channel.pending["req1"] = MagicMock()
        channel.pending["req2"] = MagicMock()

        status = channel.health_status

        assert status["pending_requests"] == 2
        assert status["is_healthy"] is False


@pytest.mark.unit
class TestIPCChannelSubmit:
    """Tests for IPCChannel submit method."""

    @pytest.mark.asyncio
    async def test_submit_exceeds_max_pending(self):
        """Test submit raises when max_pending exceeded."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig(max_pending=1))
        channel.pending["existing"] = MagicMock()

        with pytest.raises(RuntimeError, match="Max pending requests exceeded"):
            await channel.submit("new_req", MockRequest(id="new_req", data="test"))

    @pytest.mark.asyncio
    async def test_submit_puts_request_in_queue(self):
        """Test submit puts request in request queue."""
        request_q = MagicMock()
        channel = IPCChannel(request_q, MagicMock(), IPCConfig())

        request = MockRequest(id="req1", data="test")

        # Create a task that will timeout
        with pytest.raises(TimeoutError):
            await channel.submit("req1", request, timeout=0.01)

        request_q.put.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_submit_creates_pending_future(self):
        """Test submit creates future in pending dict."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        async def submit_and_check():
            # Start submit but don't await completion
            task = asyncio.create_task(
                channel.submit("req1", MockRequest(id="req1", data="test"), timeout=0.1)
            )
            await asyncio.sleep(0.01)  # Let it register

            assert "req1" in channel.pending
            task.cancel()

        await submit_and_check()

    @pytest.mark.asyncio
    async def test_submit_timeout_cleanup(self):
        """Test submit cleans up pending on timeout."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        with pytest.raises(TimeoutError):
            await channel.submit(
                "req1", MockRequest(id="req1", data="test"), timeout=0.01
            )

        # Pending should be cleaned up
        assert "req1" not in channel.pending


@pytest.mark.unit
class TestIPCChannelResponseHandling:
    """Tests for response handling."""

    def test_handle_response_resolves_future(self):
        """Test _handle_response resolves the future."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        loop = asyncio.new_event_loop()
        future = loop.create_future()
        channel.pending["req1"] = future

        response = MockResponse(id="req1", result="success")
        channel._handle_response("req1", response)

        assert future.done()
        assert future.result() is response
        assert "req1" not in channel.pending

        loop.close()

    def test_handle_response_with_error(self):
        """Test _handle_response sets exception on error."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        loop = asyncio.new_event_loop()
        future = loop.create_future()
        channel.pending["req1"] = future

        response = MockResponse(id="req1", result="", error="Something failed")
        channel._handle_response("req1", response)

        assert future.done()
        with pytest.raises(RuntimeError, match="Something failed"):
            future.result()

        loop.close()

    def test_handle_response_unknown_request(self):
        """Test _handle_response with unknown request ID."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        # Should not raise, just log warning
        channel._handle_response("unknown", MockResponse(id="unknown", result="x"))


@pytest.mark.unit
class TestIPCChannelStreaming:
    """Tests for streaming functionality."""

    @pytest.mark.asyncio
    async def test_handle_stream_chunk(self):
        """Test _handle_stream_chunk puts chunk in queue."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        chunk_queue: asyncio.Queue = asyncio.Queue()
        channel.pending_streams["stream1"] = chunk_queue

        chunk = MockStreamChunk(id="stream1", data="chunk1")
        await channel._handle_stream_chunk("stream1", chunk)

        result = await chunk_queue.get()
        assert result is chunk

    @pytest.mark.asyncio
    async def test_handle_stream_chunk_unknown_stream(self):
        """Test _handle_stream_chunk with unknown stream ID."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        # Should not raise, just log warning
        await channel._handle_stream_chunk(
            "unknown", MockStreamChunk(id="unknown", data="x")
        )


@pytest.mark.unit
class TestIPCChannelPolling:
    """Tests for polling functionality."""

    @pytest.mark.asyncio
    async def test_start_polling_creates_task(self):
        """Test start_polling creates background task."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        with patch.object(channel, "_poll_responses", new_callable=AsyncMock):
            await channel.start_polling()

            assert channel._poll_task is not None

            await channel.stop_polling()

    @pytest.mark.asyncio
    async def test_start_polling_idempotent(self):
        """Test start_polling is idempotent."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        with patch.object(channel, "_poll_responses", new_callable=AsyncMock):
            await channel.start_polling()
            task1 = channel._poll_task

            await channel.start_polling()
            task2 = channel._poll_task

            assert task1 is task2

            await channel.stop_polling()

    @pytest.mark.asyncio
    async def test_stop_polling_cancels_task(self):
        """Test stop_polling cancels the polling task."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        with patch.object(channel, "_poll_responses", new_callable=AsyncMock):
            await channel.start_polling()
            await channel.stop_polling()

            assert channel._poll_task is None

    @pytest.mark.asyncio
    async def test_stop_polling_cancels_pending_futures(self):
        """Test stop_polling cancels pending futures."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        future = asyncio.get_event_loop().create_future()
        channel.pending["req1"] = future

        with patch.object(channel, "_poll_responses", new_callable=AsyncMock):
            await channel.start_polling()
            await channel.stop_polling()

        assert future.cancelled()
        assert len(channel.pending) == 0

    @pytest.mark.asyncio
    async def test_read_queue_item_returns_none_on_empty(self):
        """Test _read_queue_item returns None when queue is empty."""
        response_q = MagicMock()
        response_q.get.side_effect = Empty()

        channel = IPCChannel(MagicMock(), response_q, IPCConfig(poll_interval=0.001))

        loop = asyncio.get_event_loop()
        result = await channel._read_queue_item(loop)

        assert result is None

    @pytest.mark.asyncio
    async def test_dispatch_response_to_pending(self):
        """Test _dispatch_response routes to pending future."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        future = asyncio.get_event_loop().create_future()
        channel.pending["req1"] = future

        response = MockResponse(id="req1", result="success")
        await channel._dispatch_response(response)

        assert future.done()

    @pytest.mark.asyncio
    async def test_dispatch_response_to_stream(self):
        """Test _dispatch_response routes to stream queue."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        chunk_queue: asyncio.Queue = asyncio.Queue()
        channel.pending_streams["stream1"] = chunk_queue

        chunk = MockStreamChunk(id="stream1", data="data")
        await channel._dispatch_response(chunk)

        result = await chunk_queue.get()
        assert result is chunk

    @pytest.mark.asyncio
    async def test_dispatch_response_no_id(self):
        """Test _dispatch_response with item without id attribute."""
        channel = IPCChannel(MagicMock(), MagicMock(), IPCConfig())

        # Should not raise, just log warning
        await channel._dispatch_response({"no_id": True})
